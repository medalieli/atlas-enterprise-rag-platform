import logging
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TrustedPrincipal, get_trusted_principal
from app.core.config import get_settings
from app.db.models import Collection, Membership
from app.db.session import get_session
from app.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
    create_embedding_provider,
    validate_vector,
)
from app.retrieval import (
    HybridCandidate,
    RetrievalCandidate,
    candidate_depth,
    keyword_candidates,
    reciprocal_rank_fusion,
    semantic_candidates,
)

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class SearchResult(BaseModel):
    rank: int
    similarity_score: float
    chunk_id: UUID
    document_id: UUID
    document_name: str
    content: str
    page_number: int | None
    section_path: str | None
    start_offset: int
    end_offset: int


class SemanticSearchResponse(BaseModel):
    results: list[SearchResult]


class KeywordSearchResult(BaseModel):
    rank: int
    keyword_score: float
    chunk_id: UUID
    document_id: UUID
    document_name: str
    content: str
    page_number: int | None
    section_path: str | None
    start_offset: int
    end_offset: int


class KeywordSearchResponse(BaseModel):
    results: list[KeywordSearchResult]


class HybridSearchResult(BaseModel):
    rank: int
    hybrid_score: float
    semantic_rank: int | None
    similarity_score: float | None
    keyword_rank: int | None
    keyword_score: float | None
    matched_channels: list[str]
    chunk_id: UUID
    document_id: UUID
    document_name: str
    content: str
    page_number: int | None
    section_path: str | None
    start_offset: int
    end_offset: int


class HybridSearchResponse(BaseModel):
    results: list[HybridSearchResult]


def get_embedding_provider() -> EmbeddingProvider:
    try:
        return create_embedding_provider(get_settings())
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _authorize_collection(
    session: AsyncSession,
    principal: TrustedPrincipal,
    collection_id: UUID,
) -> None:
    allowed = await session.scalar(
        select(Collection.id)
        .join(
            Membership,
            (Membership.tenant_id == Collection.tenant_id)
            & (Membership.user_id == principal.user_id),
        )
        .where(
            Collection.id == collection_id,
            Collection.tenant_id == principal.tenant_id,
        )
    )
    if allowed is None:
        raise HTTPException(status_code=404, detail="Collection not found")


async def _embed_query(provider: EmbeddingProvider, query: str) -> list[float]:
    settings = get_settings()
    try:
        return validate_vector(
            await provider.embed_query(query), settings.embedding_dimensions
        )
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TransientEmbeddingError as exc:
        raise HTTPException(
            status_code=503, detail="Embedding provider unavailable"
        ) from exc
    except PermanentEmbeddingError as exc:
        raise HTTPException(
            status_code=422, detail="Query could not be embedded"
        ) from exc


def _search_result(rank: int, item: RetrievalCandidate) -> SearchResult:
    return SearchResult(
        rank=rank,
        similarity_score=item.score,
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        document_name=item.document_name,
        content=item.content,
        page_number=item.page_number,
        section_path=item.section_path,
        start_offset=item.start_offset,
        end_offset=item.end_offset,
    )


def _keyword_result(rank: int, item: RetrievalCandidate) -> KeywordSearchResult:
    return KeywordSearchResult(
        rank=rank,
        keyword_score=item.score,
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        document_name=item.document_name,
        content=item.content,
        page_number=item.page_number,
        section_path=item.section_path,
        start_offset=item.start_offset,
        end_offset=item.end_offset,
    )


def _hybrid_result(rank: int, item: HybridCandidate) -> HybridSearchResult:
    candidate = item.candidate
    channels = []
    if item.semantic_rank is not None:
        channels.append("semantic")
    if item.keyword_rank is not None:
        channels.append("keyword")
    return HybridSearchResult(
        rank=rank,
        hybrid_score=item.hybrid_score,
        semantic_rank=item.semantic_rank,
        similarity_score=item.semantic_score,
        keyword_rank=item.keyword_rank,
        keyword_score=item.keyword_score,
        matched_channels=channels,
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        document_name=candidate.document_name,
        content=candidate.content,
        page_number=candidate.page_number,
        section_path=candidate.section_path,
        start_offset=candidate.start_offset,
        end_offset=candidate.end_offset,
    )


def _log_retrieval(
    mode: str,
    started: float,
    result_count: int,
    semantic_count: int = 0,
    keyword_count: int = 0,
) -> None:
    logger.info(
        "Retrieval completed mode=%s semantic_candidates=%s "
        "keyword_candidates=%s results=%s total_ms=%.3f",
        mode,
        semantic_count,
        keyword_count,
        result_count,
        (perf_counter() - started) * 1000,
    )


@router.post(
    "/collections/{collection_id}/semantic-search",
    response_model=SemanticSearchResponse,
)
async def semantic_search(
    collection_id: UUID,
    request: SemanticSearchRequest,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> SemanticSearchResponse:
    started = perf_counter()
    await _authorize_collection(session, principal, collection_id)
    vector = await _embed_query(provider, request.query)
    rows = await semantic_candidates(
        session,
        principal.tenant_id,
        collection_id,
        vector,
        request.top_k,
        get_settings(),
    )
    _log_retrieval("semantic", started, len(rows), semantic_count=len(rows))
    return SemanticSearchResponse(
        results=[_search_result(rank, item) for rank, item in enumerate(rows, 1)]
    )


@router.post(
    "/collections/{collection_id}/keyword-search",
    response_model=KeywordSearchResponse,
)
async def keyword_search(
    collection_id: UUID,
    request: SemanticSearchRequest,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KeywordSearchResponse:
    started = perf_counter()
    await _authorize_collection(session, principal, collection_id)
    rows = await keyword_candidates(
        session,
        principal.tenant_id,
        collection_id,
        request.query,
        request.top_k,
    )
    _log_retrieval("keyword", started, len(rows), keyword_count=len(rows))
    return KeywordSearchResponse(
        results=[_keyword_result(rank, item) for rank, item in enumerate(rows, 1)]
    )


@router.post(
    "/collections/{collection_id}/hybrid-search",
    response_model=HybridSearchResponse,
)
async def hybrid_search(
    collection_id: UUID,
    request: SemanticSearchRequest,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> HybridSearchResponse:
    started = perf_counter()
    await _authorize_collection(session, principal, collection_id)
    vector = await _embed_query(provider, request.query)
    depth = candidate_depth(request.top_k)
    semantic = await semantic_candidates(
        session,
        principal.tenant_id,
        collection_id,
        vector,
        depth,
        get_settings(),
    )
    keyword = await keyword_candidates(
        session,
        principal.tenant_id,
        collection_id,
        request.query,
        depth,
    )
    fused = reciprocal_rank_fusion(semantic, keyword, request.top_k)
    _log_retrieval(
        "hybrid",
        started,
        len(fused),
        semantic_count=len(semantic),
        keyword_count=len(keyword),
    )
    return HybridSearchResponse(
        results=[_hybrid_result(rank, item) for rank, item in enumerate(fused, 1)]
    )

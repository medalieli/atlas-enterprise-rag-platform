from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TrustedPrincipal, get_trusted_principal
from app.core.config import get_settings
from app.db.models import (
    Collection,
    Document,
    DocumentChunk,
    DocumentStatus,
    Membership,
)
from app.db.session import get_session
from app.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
    create_embedding_provider,
    validate_vector,
)

router = APIRouter(tags=["search"])


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


def get_embedding_provider() -> EmbeddingProvider:
    try:
        return create_embedding_provider(get_settings())
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    settings = get_settings()
    try:
        query_vector = validate_vector(
            await provider.embed_query(request.query), settings.embedding_dimensions
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

    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    filters = (
        DocumentChunk.tenant_id == principal.tenant_id,
        Document.collection_id == collection_id,
        Document.status == DocumentStatus.AVAILABLE,
        DocumentChunk.embedding.is_not(None),
        DocumentChunk.embedding_model == settings.embedding_model,
        DocumentChunk.embedding_dimensions == settings.embedding_dimensions,
    )
    query = (
        select(DocumentChunk, Document.filename, distance)
        .join(
            Document,
            (Document.id == DocumentChunk.document_id)
            & (Document.tenant_id == DocumentChunk.tenant_id),
        )
        .where(*filters)
        .order_by(distance, DocumentChunk.id)
        .limit(request.top_k)
    )
    await session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
    rows = (await session.execute(query)).all()
    scoped_count = await session.scalar(
        select(func.count(DocumentChunk.id))
        .join(
            Document,
            (Document.id == DocumentChunk.document_id)
            & (Document.tenant_id == DocumentChunk.tenant_id),
        )
        .where(*filters)
    )
    expected = min(request.top_k, scoped_count or 0)
    if len(rows) < expected:
        # Iterative HNSW is bounded. Fall back to an exact scan of the already-
        # authorized scope when it cannot fill top_k; predicates are never relaxed.
        await session.execute(text("SET LOCAL enable_indexscan = off"))
        await session.execute(text("SET LOCAL enable_bitmapscan = off"))
        rows = (await session.execute(query)).all()

    return SemanticSearchResponse(
        results=[
            SearchResult(
                rank=rank,
                similarity_score=1.0 - float(row.distance),
                chunk_id=row.DocumentChunk.id,
                document_id=row.DocumentChunk.document_id,
                document_name=row.filename,
                content=row.DocumentChunk.content,
                page_number=row.DocumentChunk.page_number,
                section_path=row.DocumentChunk.section,
                start_offset=row.DocumentChunk.start_offset,
                end_offset=row.DocumentChunk.end_offset,
            )
            for rank, row in enumerate(rows, 1)
        ]
    )

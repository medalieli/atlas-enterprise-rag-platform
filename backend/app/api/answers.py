import logging
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.answering import (
    AnswerGenerationError,
    AnswerGenerator,
    AnswerStatus,
    AnswerValidationError,
    GeneratedAnswer,
    GenerationResult,
    GenerationUsage,
    build_answer_context,
    generate_bounded,
    get_answer_generator,
    safe_correlation_id,
    validate_and_resolve_answer,
    validate_usage,
)
from app.api.search import (
    _embed_query,
    authorize_collection,
    get_embedding_provider,
    get_reranker_dependency,
)
from app.auth import TrustedPrincipal, get_trusted_principal
from app.core.config import get_settings
from app.db.session import get_session
from app.embeddings import EmbeddingProvider
from app.metadata import MetadataFilter, PublicDocumentMetadata
from app.reranking import RerankerError, RerankerProvider, rerank_hybrid_candidates
from app.retrieval import (
    candidate_depth,
    keyword_candidates,
    reciprocal_rank_fusion,
    semantic_candidates,
)

router = APIRouter(tags=["answers"])
logger = logging.getLogger("uvicorn.error")


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8_000)
    retrieval_count: int = Field(default=8, ge=1, le=20)
    filters: MetadataFilter | None = None

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class AnswerClaim(BaseModel):
    text: str
    citation_numbers: list[int]


class AnswerCitation(BaseModel):
    citation_number: int
    source_id: str
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str
    content_type: str
    page_number: int | None
    section_path: str | None
    start_offset: int
    end_offset: int
    metadata: PublicDocumentMetadata
    source_excerpt: str


class AnswerUsage(BaseModel):
    configured_model: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


class AnswerLatency(BaseModel):
    retrieval_ms: float
    generation_ms: float
    total_ms: float


class AskResponse(BaseModel):
    status: AnswerStatus
    answer: str
    claims: list[AnswerClaim]
    citations: list[AnswerCitation]
    retrieval_mode: str
    context_chunks_used: int
    usage: AnswerUsage
    latency: AnswerLatency


def get_answer_generator_dependency() -> AnswerGenerator:
    try:
        return get_answer_generator()
    except AnswerGenerationError as exc:
        raise HTTPException(
            status_code=503, detail="Answer provider unavailable"
        ) from exc


def _no_context_message(query: str) -> str:
    lowered = query.casefold()
    french = any(
        marker in f" {lowered} "
        for marker in (" quel ", " quelle ", " comment ", " pourquoi ", " délai ")
    )
    if french:
        return "Les documents disponibles ne contiennent pas assez d’informations."
    return "The available documents do not contain enough information."


def _empty_generation(settings_model: str, query: str) -> GenerationResult:
    return GenerationResult(
        answer=GeneratedAnswer(
            status=AnswerStatus.INSUFFICIENT_CONTEXT,
            claims=[],
            insufficient_reason=_no_context_message(query),
        ),
        configured_model=settings_model,
        actual_model=settings_model,
        usage=GenerationUsage(0, 0, 0),
    )


@router.post(
    "/collections/{collection_id}/ask",
    response_model=AskResponse,
)
async def ask(
    collection_id: UUID,
    request: AskRequest,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_provider: Annotated[
        EmbeddingProvider, Depends(get_embedding_provider)
    ],
    reranker: Annotated[RerankerProvider, Depends(get_reranker_dependency)],
    answer_generator: Annotated[
        AnswerGenerator, Depends(get_answer_generator_dependency)
    ],
) -> AskResponse:
    settings = get_settings()
    if request.retrieval_count > settings.reranker_candidate_limit:
        raise HTTPException(
            status_code=422,
            detail="retrieval_count exceeds the reranker candidate limit",
        )
    started = perf_counter()
    await authorize_collection(session, principal, collection_id)
    vector = await _embed_query(embedding_provider, request.query)
    depth = candidate_depth(settings.reranker_candidate_limit)
    semantic = await semantic_candidates(
        session,
        principal.tenant_id,
        collection_id,
        vector,
        depth,
        settings,
        request.filters,
    )
    keyword = await keyword_candidates(
        session,
        principal.tenant_id,
        collection_id,
        request.query,
        depth,
        request.filters,
    )
    fused = reciprocal_rank_fusion(
        semantic, keyword, settings.reranker_candidate_limit
    )
    try:
        reranked = await rerank_hybrid_candidates(
            request.query,
            fused,
            request.retrieval_count,
            reranker,
            settings.reranker_timeout_seconds,
        )
    except RerankerError as exc:
        raise HTTPException(status_code=503, detail="Reranker unavailable") from exc
    context = build_answer_context(
        reranked, principal.tenant_id, collection_id, settings
    )
    retrieval_ms = (perf_counter() - started) * 1_000
    generation_started = perf_counter()
    try:
        generated = (
            _empty_generation(settings.answer_model, request.query)
            if not context.sources
            else await generate_bounded(
                answer_generator,
                request.query,
                context,
                settings.answer_provider_timeout_seconds,
            )
        )
        validate_usage(generated.usage)
        validated = await validate_and_resolve_answer(
            session,
            generated.answer,
            context,
            principal.tenant_id,
            collection_id,
            settings,
        )
    except (AnswerGenerationError, AnswerValidationError) as exc:
        logger.warning(
            "Answer request failed correlation_id=%s category=%s",
            safe_correlation_id(principal.tenant_id, collection_id),
            getattr(exc, "category", type(exc).__name__),
        )
        raise HTTPException(
            status_code=503, detail="Grounded answer could not be generated"
        ) from exc
    generation_ms = (perf_counter() - generation_started) * 1_000
    total_ms = (perf_counter() - started) * 1_000
    numbers = {
        citation.source.source_id: citation.citation_number
        for citation in validated.citations
    }
    response = AskResponse(
        status=validated.status,
        answer=validated.answer,
        claims=[
            AnswerClaim(
                text=claim.text,
                citation_numbers=[numbers[source_id] for source_id in claim.source_ids],
            )
            for claim in validated.claims
        ],
        citations=[
            AnswerCitation(
                citation_number=citation.citation_number,
                source_id=citation.source.source_id,
                chunk_id=citation.source.chunk_id,
                document_id=citation.source.document_id,
                document_version_id=citation.source.document_version_id,
                document_name=citation.source.document_name,
                content_type=citation.source.content_type,
                page_number=citation.source.page_number,
                section_path=citation.source.section_path,
                start_offset=citation.source.start_offset,
                end_offset=citation.source.end_offset,
                metadata=citation.source.metadata,
                source_excerpt=citation.source.content,
            )
            for citation in validated.citations
        ],
        retrieval_mode="hybrid_reranked",
        context_chunks_used=len(context.sources),
        usage=AnswerUsage(
            configured_model=generated.configured_model,
            actual_model=generated.actual_model,
            input_tokens=generated.usage.input_tokens,
            output_tokens=generated.usage.output_tokens,
            total_tokens=generated.usage.total_tokens,
        ),
        latency=AnswerLatency(
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
        ),
    )
    logger.info(
        "Answer completed correlation_id=%s model=%s candidates=%s context=%s "
        "citations=%s input_tokens=%s output_tokens=%s retrieval_ms=%.3f "
        "generation_ms=%.3f total_ms=%.3f",
        safe_correlation_id(principal.tenant_id, collection_id),
        generated.actual_model,
        len(fused),
        len(context.sources),
        len(validated.citations),
        generated.usage.input_tokens,
        generated.usage.output_tokens,
        retrieval_ms,
        generation_ms,
        total_ms,
    )
    return response

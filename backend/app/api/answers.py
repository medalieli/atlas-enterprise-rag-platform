import logging
import re
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.answering import (
    AnswerGenerationError,
    AnswerGenerator,
    AnswerProviderUnavailableError,
    AnswerStatus,
    AnswerValidationError,
    GeneratedAnswer,
    GenerationResult,
    GenerationUsage,
    build_answer_context,
    generate_bounded,
    get_answer_generator,
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
from app.observability import (
    ANSWER_STATUS,
    CITATION_FAILURES,
    PROVIDER_DURATION,
    PROVIDER_REQUESTS,
    PROVIDER_TOKENS,
    RETRIEVAL_DURATION,
    RETRIEVAL_QUALITY,
    configured_model_label,
    request_id_var,
    stage,
)
from app.reranking import (
    RerankerError,
    RerankerProvider,
    hybrid_fallback,
    rerank_hybrid_candidates,
    select_answer_candidates,
)
from app.retrieval import (
    candidate_depth,
    extract_query_identifiers,
    identifier_candidates,
    inject_identifier_candidates,
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
    generation_id: UUID
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


def get_answer_generator_dependency() -> AnswerGenerator | None:
    try:
        return get_answer_generator()
    except AnswerGenerationError:
        return None


def get_original_question_dependency() -> str | None:
    """Internal override used only by the conversational orchestration path."""
    return None


def _raise_answer_provider_unavailable() -> GenerationResult:
    raise AnswerProviderUnavailableError("Answer provider unavailable")


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


_EXTERNAL_CURRENT_PATTERN = re.compile(
    r"\b(?:today|yesterday|current|currently|latest|live|right now|"
    r"stock price|share price|weather|exchange rate|news)\b",
    re.IGNORECASE,
)
_UNSAFE_ASSISTANT_REQUEST_PATTERN = re.compile(
    r"(?:ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"reveal\s+(?:your\s+)?(?:system\s+prompt|api\s+key)|"
    r"invent\s+(?:a\s+)?(?:source|citation)|"
    r"bypass\s+(?:access\s+)?controls?|"
    r"(?:other|another)\s+tenants?'?\s+(?:confidential\s+)?data|"
    r"treat\s+.*instructions?\s+inside\s+.*documents?\s+as\s+system)",
    re.IGNORECASE,
)
_RELEVANCE_STOPWORDS = frozenset(
    {
        "about", "according", "atlas", "could", "does", "each", "from",
        "give", "have", "include", "into", "northstar", "policy", "real",
        "requirement", "requirements", "state", "summarize", "summary", "that",
        "their", "then", "this", "what", "when", "where", "which", "with",
        "would", "your",
    }
)


def _has_meaningful_evidence(query: str, passages: list[str]) -> bool:
    if extract_query_identifiers(query):
        return True
    terms = {
        token.casefold()
        for token in re.findall(
            r"[^\W\d_][^\W_]{2,}", query.replace("-", " "), re.UNICODE
        )
        if token.casefold() not in _RELEVANCE_STOPWORDS
    }
    if not terms:
        return False
    evidence = " ".join(passages).casefold().replace("-", " ")
    return any(term in evidence for term in terms)


def _requires_external_current_data(query: str) -> bool:
    return bool(_EXTERNAL_CURRENT_PATTERN.search(query))


def _requires_safe_refusal(query: str) -> bool:
    """Reject explicit attempts to override grounding or authorization boundaries."""
    return bool(_UNSAFE_ASSISTANT_REQUEST_PATTERN.search(query))


def _normalized_retrieval_query(query: str) -> str:
    """Normalize punctuation that changes search semantics without altering IDs."""
    return re.sub(r"(?<=[^\W\d_])[-‐‑–—](?=[^\W\d_])", " ", query)


@router.post(
    "/collections/{collection_id}/ask",
    response_model=AskResponse,
)
async def ask(
    collection_id: UUID,
    request: AskRequest,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    reranker: Annotated[RerankerProvider, Depends(get_reranker_dependency)],
    answer_generator: Annotated[
        AnswerGenerator | None, Depends(get_answer_generator_dependency)
    ],
    original_question: Annotated[str | None, Depends(get_original_question_dependency)],
) -> AskResponse:
    settings = get_settings()
    if request.retrieval_count > settings.reranker_candidate_limit:
        raise HTTPException(
            status_code=422,
            detail="retrieval_count exceeds the reranker candidate limit",
        )
    started = perf_counter()
    tenant_id = await authorize_collection(session, principal, collection_id)
    retrieval_query = _normalized_retrieval_query(request.query)
    vector = await _embed_query(embedding_provider, retrieval_query)
    depth = candidate_depth(settings.reranker_candidate_limit)
    with stage("retrieval.semantic.candidates", {"rag.mode": "semantic"}):
        semantic = await semantic_candidates(
            session,
            tenant_id,
            collection_id,
            vector,
            depth,
            settings,
            request.filters,
        )
    with stage("retrieval.keyword.candidates", {"rag.mode": "keyword"}):
        keyword = await keyword_candidates(
            session,
            tenant_id,
            collection_id,
            retrieval_query,
            depth,
            request.filters,
    )
    exact = await identifier_candidates(
        session, tenant_id, collection_id, retrieval_query, request.filters
    )
    with stage("retrieval.hybrid.fusion", {"rag.mode": "hybrid"}):
        fused = inject_identifier_candidates(
            reciprocal_rank_fusion(
                semantic, keyword, settings.reranker_candidate_limit
            ),
            exact,
            settings.reranker_candidate_limit,
        )
    RETRIEVAL_QUALITY.labels(
        "identifier", "matched" if exact else "absent"
    ).inc()
    try:
        with stage("retrieval.rerank", {"rag.mode": "reranked"}):
            fully_ranked = await rerank_hybrid_candidates(
                retrieval_query,
                fused,
                len(fused),
                reranker,
                settings.reranker_timeout_seconds,
            )
    except RerankerError:
        RETRIEVAL_QUALITY.labels("reranker", "fallback").inc()
        logger.warning("Reranker unavailable; using fused retrieval order")
        fully_ranked = hybrid_fallback(fused)
    reranked = select_answer_candidates(
        retrieval_query, fully_ranked, request.retrieval_count
    )
    if exact:
        RETRIEVAL_QUALITY.labels("identifier", "preserved").inc()
    context = build_answer_context(reranked, tenant_id, collection_id, settings)
    evidence_supported = _has_meaningful_evidence(
        retrieval_query, [source.content for source in context.sources]
    )
    if (
        _requires_external_current_data(request.query)
        or _requires_safe_refusal(request.query)
        or not evidence_supported
    ):
        reason = (
            "external_current" if _requires_external_current_data(request.query)
            else "unsafe_request" if _requires_safe_refusal(request.query)
            else "low_relevance"
        )
        RETRIEVAL_QUALITY.labels("refusal", reason).inc()
        context = build_answer_context([], tenant_id, collection_id, settings)
    retrieval_ms = (perf_counter() - started) * 1_000
    generation_started = perf_counter()
    generation_question = original_question or request.query
    if original_question is not None and original_question != request.query:
        generation_question = (
            f"Current user question:\n{original_question}\n\n"
            f"Validated standalone retrieval interpretation:\n{request.query}"
        )
    try:
        validation_attempts = 2 if context.sources and answer_generator else 1
        for validation_attempt in range(validation_attempts):
            with stage("answer.generate", {"rag.operation": "answer"}):
                generated = (
                    _empty_generation(
                        settings.answer_model, original_question or request.query
                    )
                    if not context.sources
                    else await generate_bounded(
                        answer_generator,
                        generation_question,
                        context,
                        settings.answer_provider_timeout_seconds,
                    )
                    if answer_generator is not None
                    else _raise_answer_provider_unavailable()
                )
            try:
                validate_usage(generated.usage)
                with stage(
                    "answer.citations.validate", {"rag.operation": "answer"}
                ):
                    validated = await validate_and_resolve_answer(
                        session,
                        generated.answer,
                        context,
                        tenant_id,
                        collection_id,
                        settings,
                    )
                break
            except AnswerValidationError as exc:
                CITATION_FAILURES.labels("validation").inc()
                if validation_attempt + 1 < validation_attempts:
                    logger.warning(
                        "Answer validation retry correlation_id=%s reason=%s",
                        request_id_var.get(),
                        str(exc),
                    )
                    continue
                logger.warning(
                    "Answer validation fallback correlation_id=%s reason=%s",
                    request_id_var.get(),
                    str(exc),
                )
                generated = _empty_generation(
                    settings.answer_model, original_question or request.query
                )
                validated = await validate_and_resolve_answer(
                    session,
                    generated.answer,
                    context,
                    tenant_id,
                    collection_id,
                    settings,
                )
                break
    except (AnswerGenerationError, AnswerValidationError) as exc:
        category = (
            "provider" if isinstance(exc, AnswerGenerationError) else "validation"
        )
        PROVIDER_REQUESTS.labels(
            "answer", "openai", get_settings().answer_model, category
        ).inc()
        logger.warning(
            "Answer request failed correlation_id=%s category=%s",
            request_id_var.get(),
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
                generation_id=citation.source.generation_id,
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
    RETRIEVAL_DURATION.labels("reranked").observe(retrieval_ms / 1000)
    model_label = configured_model_label(generated.actual_model, settings.answer_model)
    PROVIDER_REQUESTS.labels("answer", "openai", model_label, "none").inc()
    PROVIDER_DURATION.labels("answer", "openai", model_label).observe(
        generation_ms / 1000
    )
    PROVIDER_TOKENS.labels("answer", "openai", model_label, "input").inc(
        generated.usage.input_tokens
    )
    PROVIDER_TOKENS.labels("answer", "openai", model_label, "output").inc(
        generated.usage.output_tokens
    )
    ANSWER_STATUS.labels(validated.status.value).inc()
    logger.info(
        "Answer completed correlation_id=%s model=%s candidates=%s context=%s "
        "citations=%s input_tokens=%s output_tokens=%s retrieval_ms=%.3f "
        "generation_ms=%.3f total_ms=%.3f",
        request_id_var.get(),
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

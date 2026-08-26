from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Document, DocumentChunk, DocumentStatus
from app.metadata import MetadataFilter, document_filter_predicates

TEXT_SEARCH_CONFIGURATION = "simple"
TEXT_SEARCH_REGCONFIG_SQL = text("'simple'::regconfig")
RRF_K = 60
CANDIDATE_MULTIPLIER = 4
MAX_CANDIDATES_PER_BRANCH = 200


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: UUID
    document_id: UUID
    document_name: str
    content: str
    page_number: int | None
    section_path: str | None
    start_offset: int
    end_offset: int
    score: float
    source_unit_id: UUID | None = None
    content_type: str = "application/octet-stream"
    document_created_at: datetime | None = None
    document_metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class HybridCandidate:
    candidate: RetrievalCandidate
    hybrid_score: float
    semantic_rank: int | None
    semantic_score: float | None
    keyword_rank: int | None
    keyword_score: float | None


def candidate_depth(top_k: int) -> int:
    return min(MAX_CANDIDATES_PER_BRANCH, top_k * CANDIDATE_MULTIPLIER)


def _candidate(
    chunk: DocumentChunk,
    filename: str,
    content_type: str,
    document_created_at: datetime,
    document_metadata: dict[str, object],
    score: float,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_name=filename,
        content_type=content_type,
        document_created_at=document_created_at,
        document_metadata=document_metadata,
        source_unit_id=chunk.source_unit_id,
        content=chunk.content,
        page_number=chunk.page_number,
        section_path=chunk.section,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        score=score,
    )


async def semantic_candidates(
    session: AsyncSession,
    tenant_id: UUID,
    collection_id: UUID,
    query_vector: list[float],
    limit: int,
    settings: Settings,
    filters: MetadataFilter | None = None,
) -> list[RetrievalCandidate]:
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    scope_filters = (
        DocumentChunk.tenant_id == tenant_id,
        Document.collection_id == collection_id,
        Document.status == DocumentStatus.AVAILABLE,
        DocumentChunk.embedding.is_not(None),
        DocumentChunk.embedding_model == settings.embedding_model,
        DocumentChunk.embedding_dimensions == settings.embedding_dimensions,
    )
    query = (
        select(
            DocumentChunk,
            Document.filename,
            Document.content_type,
            Document.created_at,
            Document.document_metadata,
            distance,
        )
        .join(
            Document,
            (Document.id == DocumentChunk.document_id)
            & (Document.tenant_id == DocumentChunk.tenant_id),
        )
        .where(*scope_filters, *document_filter_predicates(filters))
        .order_by(distance, DocumentChunk.id)
        .limit(limit)
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
        .where(*scope_filters, *document_filter_predicates(filters))
    )
    expected = min(limit, scoped_count or 0)
    if len(rows) < expected:
        await session.execute(text("SET LOCAL enable_indexscan = off"))
        await session.execute(text("SET LOCAL enable_bitmapscan = off"))
        rows = (await session.execute(query)).all()
    return [
        _candidate(
            chunk,
            filename,
            content_type,
            document_created_at,
            document_metadata,
            1.0 - float(distance_value),
        )
        for (
            chunk,
            filename,
            content_type,
            document_created_at,
            document_metadata,
            distance_value,
        ) in rows
    ]


async def keyword_candidates(
    session: AsyncSession,
    tenant_id: UUID,
    collection_id: UUID,
    query_text: str,
    limit: int,
    filters: MetadataFilter | None = None,
) -> list[RetrievalCandidate]:
    tsquery = func.websearch_to_tsquery(TEXT_SEARCH_REGCONFIG_SQL, query_text)
    keyword_score = func.ts_rank_cd(DocumentChunk.search_vector, tsquery).label(
        "keyword_score"
    )
    query = (
        select(
            DocumentChunk,
            Document.filename,
            Document.content_type,
            Document.created_at,
            Document.document_metadata,
            keyword_score,
        )
        .join(
            Document,
            (Document.id == DocumentChunk.document_id)
            & (Document.tenant_id == DocumentChunk.tenant_id),
        )
        .where(
            DocumentChunk.tenant_id == tenant_id,
            Document.collection_id == collection_id,
            Document.status == DocumentStatus.AVAILABLE,
            *document_filter_predicates(filters),
            func.numnode(tsquery) > 0,
            DocumentChunk.search_vector.op("@@")(tsquery),
        )
        .order_by(keyword_score.desc(), DocumentChunk.id)
        .limit(limit)
    )
    rows = (await session.execute(query)).all()
    return [
        _candidate(
            chunk,
            filename,
            content_type,
            document_created_at,
            document_metadata,
            float(score),
        )
        for (
            chunk,
            filename,
            content_type,
            document_created_at,
            document_metadata,
            score,
        ) in rows
    ]


def reciprocal_rank_fusion(
    semantic: list[RetrievalCandidate],
    keyword: list[RetrievalCandidate],
    top_k: int,
    rrf_k: int = RRF_K,
) -> list[HybridCandidate]:
    semantic_by_id = {
        candidate.chunk_id: (rank, candidate)
        for rank, candidate in enumerate(semantic, 1)
    }
    keyword_by_id = {
        candidate.chunk_id: (rank, candidate)
        for rank, candidate in enumerate(keyword, 1)
    }
    fused: list[HybridCandidate] = []
    for chunk_id in semantic_by_id.keys() | keyword_by_id.keys():
        semantic_entry = semantic_by_id.get(chunk_id)
        keyword_entry = keyword_by_id.get(chunk_id)
        semantic_rank = semantic_entry[0] if semantic_entry else None
        keyword_rank = keyword_entry[0] if keyword_entry else None
        if semantic_entry is not None:
            candidate = semantic_entry[1]
        elif keyword_entry is not None:
            candidate = keyword_entry[1]
        else:  # pragma: no cover - the union of keys guarantees one branch
            continue
        score = (1 / (rrf_k + semantic_rank) if semantic_rank else 0.0) + (
            1 / (rrf_k + keyword_rank) if keyword_rank else 0.0
        )
        fused.append(
            HybridCandidate(
                candidate=candidate,
                hybrid_score=score,
                semantic_rank=semantic_rank,
                semantic_score=semantic_entry[1].score if semantic_entry else None,
                keyword_rank=keyword_rank,
                keyword_score=keyword_entry[1].score if keyword_entry else None,
            )
        )
    fused.sort(key=lambda item: (-item.hybrid_score, str(item.candidate.chunk_id)))
    return fused[:top_k]

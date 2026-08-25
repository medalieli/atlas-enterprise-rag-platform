import asyncio
import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from celery import Task
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.models import (
    Document,
    DocumentChunk,
    DocumentSourceUnit,
    DocumentStatus,
    ProcessingJob,
    ProcessingJobStatus,
)
from app.db.session import dispose_engine, engine, session_factory
from app.embeddings import (
    EMBEDDING_INPUT_VERSION,
    EmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
    build_embedding_input,
    create_embedding_provider,
    embedding_fingerprint,
)
from app.ingestion.chunking import (
    CHUNKER_VERSION,
    ChunkingConfig,
    chunk_source_unit,
    pipeline_fingerprint,
)
from app.ingestion.cleaning import CLEANER_VERSION, clean_source_unit
from app.ingestion.parsers import ParserLimits, PermanentParserError, parse_document
from app.storage import LocalDocumentStorage
from app.worker import celery_app

SAFE_MISSING = "Stored original is missing or failed integrity verification"
SAFE_PARSE = "Document content could not be processed safely"
SAFE_TRANSIENT = "Temporary ingestion failure; retry scheduled"
SAFE_RETRY_EXHAUSTED = "Ingestion failed after retry limit"
SAFE_EMBEDDING = "Document embeddings could not be generated safely"


class TransientIngestionError(Exception):
    pass


def _advisory_key(job_id: UUID) -> int:
    value = int.from_bytes(job_id.bytes[:8], "big", signed=False)
    return value if value < 2**63 else value - 2**64


async def _mark_failed(
    tenant_id: UUID, document_id: UUID, job_id: UUID, message: str
) -> None:
    async with session_factory() as session, session.begin():
        job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id,
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.document_id == document_id,
            )
        )
        document = await session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == tenant_id
            )
        )
        if job is not None and job.status != ProcessingJobStatus.SUCCEEDED:
            job.status = ProcessingJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_message = message
        if document is not None and document.status != DocumentStatus.AVAILABLE:
            document.status = DocumentStatus.FAILED
            document.error_message = message


async def _mark_retrying(tenant_id: UUID, document_id: UUID, job_id: UUID) -> None:
    async with session_factory() as session, session.begin():
        job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id,
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.document_id == document_id,
            )
        )
        if job is not None and job.status != ProcessingJobStatus.SUCCEEDED:
            job.status = ProcessingJobStatus.RETRYING
            job.error_message = SAFE_TRANSIENT


def _limits(settings: object) -> ParserLimits:
    return ParserLimits(
        settings.parser_max_pdf_pages,
        settings.parser_max_extracted_chars,
        settings.parser_max_pdf_stream_bytes,
        settings.parser_soft_time_limit_seconds,
    )  # type: ignore[attr-defined]


def _chunk_config(settings: object) -> ChunkingConfig:
    return ChunkingConfig(
        settings.chunk_target_chars,
        settings.chunk_max_chars,
        settings.chunk_overlap_chars,
    )  # type: ignore[attr-defined]


async def process_job(
    tenant_id: UUID,
    document_id: UUID,
    job_id: UUID,
    embedding_provider: EmbeddingProvider | None = None,
) -> str:
    """Parse outside transactions and publish one deterministic chunk set atomically."""
    settings = get_settings()
    storage = LocalDocumentStorage(settings.document_storage_path)
    advisory_key = _advisory_key(job_id)
    async with engine.connect() as lock_connection:
        acquired = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": advisory_key}
        )
        if not acquired:
            return "already-running"
        try:
            async with session_factory() as session, session.begin():
                job = await session.scalar(
                    select(ProcessingJob).where(
                        ProcessingJob.id == job_id,
                        ProcessingJob.tenant_id == tenant_id,
                        ProcessingJob.document_id == document_id,
                    )
                )
                document = await session.scalar(
                    select(Document).where(
                        Document.id == document_id, Document.tenant_id == tenant_id
                    )
                )
                if job is None or document is None:
                    return "missing"
                if job.status == ProcessingJobStatus.SUCCEEDED:
                    return "already-complete"
                job.status = ProcessingJobStatus.RUNNING
                job.attempt_count += 1
                job.started_at = datetime.now(UTC)
                job.finished_at = None
                job.error_message = None
                document.status = DocumentStatus.PROCESSING
                storage_key, checksum, content_type = (
                    document.storage_key,
                    document.checksum_sha256,
                    document.content_type,
                )

            try:
                if not await storage.verify(storage_key, checksum):
                    await _mark_failed(tenant_id, document_id, job_id, SAFE_MISSING)
                    return "failed"
                parsed = parse_document(
                    storage.path_for_validation(storage_key),
                    content_type,
                    _limits(settings),
                )
                cleaned = tuple(clean_source_unit(unit) for unit in parsed.source_units)
                config = _chunk_config(settings)
                fingerprint = pipeline_fingerprint(parsed.parser_version, config)
                candidates = tuple(
                    candidate
                    for unit in cleaned
                    for candidate in chunk_source_unit(unit, config)
                )
                if not candidates:
                    raise PermanentParserError("Document has no usable normalized text")
            except PermanentParserError:
                await _mark_failed(tenant_id, document_id, job_id, SAFE_PARSE)
                return "failed"
            except OSError as exc:
                await _mark_retrying(tenant_id, document_id, job_id)
                raise TransientIngestionError from exc

            try:
                provider = embedding_provider or create_embedding_provider(settings)
                inputs = [
                    build_embedding_input(
                        candidate.content,
                        " / ".join(
                            cleaned[candidate.source_unit_index].location.section_path
                        )
                        or None,
                    )
                    for candidate in candidates
                ]
                vectors = await provider.embed_documents(inputs)
                if len(vectors) != len(candidates):
                    raise PermanentEmbeddingError("Embedding response count mismatch")
            except TransientEmbeddingError as exc:
                await _mark_retrying(tenant_id, document_id, job_id)
                raise TransientIngestionError from exc
            except PermanentEmbeddingError:
                await _mark_failed(tenant_id, document_id, job_id, SAFE_EMBEDDING)
                return "failed"

            async with session_factory() as session, session.begin():
                job = await session.scalar(
                    select(ProcessingJob)
                    .where(
                        ProcessingJob.id == job_id, ProcessingJob.tenant_id == tenant_id
                    )
                    .with_for_update()
                )
                document = await session.scalar(
                    select(Document).where(
                        Document.id == document_id, Document.tenant_id == tenant_id
                    )
                )
                if job is None or document is None:
                    return "missing"
                if job.status == ProcessingJobStatus.SUCCEEDED:
                    return "already-complete"
                await session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.tenant_id == tenant_id,
                        DocumentChunk.document_id == document_id,
                    )
                )
                await session.execute(
                    delete(DocumentSourceUnit).where(
                        DocumentSourceUnit.tenant_id == tenant_id,
                        DocumentSourceUnit.document_id == document_id,
                    )
                )
                source_rows: dict[int, DocumentSourceUnit] = {}
                for unit in cleaned:
                    row = DocumentSourceUnit(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        unit_index=unit.unit_index,
                        source_type=unit.location.source_type,
                        page_number=unit.location.page_number,
                        section_path=" / ".join(unit.location.section_path) or None,
                        normalized_text=unit.normalized_text,
                        content_hash=hashlib.sha256(
                            unit.normalized_text.encode()
                        ).hexdigest(),
                        source_metadata={"blocks": list(unit.block_boundaries)},
                    )
                    session.add(row)
                    source_rows[unit.unit_index] = row
                await session.flush()
                embedded_at = datetime.now(UTC)
                for chunk_index, (candidate, vector) in enumerate(
                    zip(candidates, vectors, strict=True)
                ):
                    unit = cleaned[candidate.source_unit_index]
                    session.add(
                        DocumentChunk(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            source_unit_id=source_rows[candidate.source_unit_index].id,
                            chunk_index=chunk_index,
                            content=candidate.content,
                            content_hash=candidate.content_hash,
                            pipeline_fingerprint=fingerprint,
                            page_number=unit.location.page_number,
                            section=" / ".join(unit.location.section_path) or None,
                            start_offset=candidate.start_offset,
                            end_offset=candidate.end_offset,
                            source_metadata={
                                "source_type": unit.location.source_type,
                                "source_unit_index": unit.unit_index,
                                "document_checksum": checksum,
                                "parser_version": parsed.parser_version,
                                "cleaner_version": CLEANER_VERSION,
                                "chunker_version": CHUNKER_VERSION,
                            },
                            embedding=vector,
                            embedding_model=settings.embedding_model,
                            embedding_dimensions=settings.embedding_dimensions,
                            embedding_input_version=EMBEDDING_INPUT_VERSION,
                            embedding_fingerprint=embedding_fingerprint(
                                hashlib.sha256(inputs[chunk_index].encode()).hexdigest(),
                                settings.embedding_model,
                                settings.embedding_dimensions,
                            ),
                            embedded_at=embedded_at,
                        )
                    )
                document.document_metadata = {
                    **document.document_metadata,
                    "pipeline_fingerprint": fingerprint,
                    "source_unit_count": len(cleaned),
                    "chunk_count": len(candidates),
                }
                document.status = DocumentStatus.AVAILABLE
                document.error_message = None
                job.status = ProcessingJobStatus.SUCCEEDED
                job.finished_at = datetime.now(UTC)
                job.error_message = None
            return "succeeded"
        finally:
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": advisory_key}
            )


async def mark_retry_exhausted(
    job_id: UUID, tenant_id: UUID, document_id: UUID
) -> None:
    await _mark_failed(tenant_id, document_id, job_id, SAFE_RETRY_EXHAUSTED)


def run_async(coroutine: object) -> object:
    try:
        return asyncio.run(coroutine)  # type: ignore[arg-type]
    finally:
        asyncio.run(dispose_engine())


@celery_app.task(
    bind=True,
    name="documents.verify_original",
    soft_time_limit=get_settings().parser_soft_time_limit_seconds,
    time_limit=get_settings().parser_hard_time_limit_seconds,
)
def verify_original_task(
    self: Task, tenant_id: str, document_id: str, job_id: str
) -> str:
    tenant_uuid, document_uuid, job_uuid = map(UUID, (tenant_id, document_id, job_id))
    try:
        return str(run_async(process_job(tenant_uuid, document_uuid, job_uuid)))
    except (TransientIngestionError, SQLAlchemyError) as exc:
        settings = get_settings()
        if self.request.retries >= settings.celery_max_retries:
            run_async(mark_retry_exhausted(job_uuid, tenant_uuid, document_uuid))
            return "failed"
        delay = min(60, 2 ** (self.request.retries + 1))
        raise self.retry(
            exc=exc,
            countdown=delay + secrets.randbelow(max(1, delay // 2 + 1)),
            max_retries=settings.celery_max_retries,
        ) from exc

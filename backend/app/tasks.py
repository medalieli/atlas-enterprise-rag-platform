import asyncio
import secrets
from datetime import UTC, datetime
from uuid import UUID

from celery import Task
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Document, DocumentStatus, ProcessingJob, ProcessingJobStatus
from app.db.session import dispose_engine, session_factory
from app.storage import LocalDocumentStorage
from app.worker import celery_app

SAFE_MISSING = "Stored original is missing or failed integrity verification"
SAFE_TRANSIENT = "Temporary ingestion failure; retry scheduled"
SAFE_RETRY_EXHAUSTED = "Ingestion failed after retry limit"


class TransientIngestionError(Exception):
    pass


async def process_job(tenant_id: UUID, document_id: UUID, job_id: UUID) -> str:
    settings = get_settings()
    storage = LocalDocumentStorage(settings.document_storage_path)
    async with session_factory() as session, session.begin():
        job = await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.document_id == document_id,
            )
            .with_for_update()
        )
        if job is None:
            return "missing"
        if job.status == ProcessingJobStatus.SUCCEEDED:
            return "already-complete"
        document = await session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == tenant_id
            )
        )
        if document is None:
            job.status = ProcessingJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_message = SAFE_MISSING
            return "failed"
        job.status = ProcessingJobStatus.RUNNING
        job.attempt_count += 1
        job.started_at = datetime.now(UTC)
        job.finished_at = None
        job.error_message = None
        document.status = DocumentStatus.PROCESSING
        try:
            valid = await storage.verify(document.storage_key, document.checksum_sha256)
        except OSError as exc:
            job.status = ProcessingJobStatus.RETRYING
            job.error_message = SAFE_TRANSIENT
            transient_error = exc
        else:
            transient_error = None
        if transient_error is not None:
            result = "retrying"
        elif not valid:
            job.status = ProcessingJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_message = SAFE_MISSING
            document.status = DocumentStatus.FAILED
            document.error_message = SAFE_MISSING
            result = "failed"
        else:
            job.status = ProcessingJobStatus.SUCCEEDED
            job.finished_at = datetime.now(UTC)
            job.error_message = None
            document.status = DocumentStatus.AVAILABLE
            document.error_message = None
            result = "succeeded"
    if transient_error is not None:
        raise TransientIngestionError from transient_error
    return result


async def mark_retry_exhausted(
    job_id: UUID, tenant_id: UUID, document_id: UUID
) -> None:
    async with session_factory() as session, session.begin():
        job = await session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.tenant_id == tenant_id)
            .with_for_update()
        )
        document = await session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == tenant_id
            )
        )
        if job is not None and job.status != ProcessingJobStatus.SUCCEEDED:
            job.status = ProcessingJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_message = SAFE_RETRY_EXHAUSTED
        if document is not None and document.status != DocumentStatus.AVAILABLE:
            document.status = DocumentStatus.FAILED
            document.error_message = SAFE_RETRY_EXHAUSTED


def run_async(coroutine: object) -> object:
    try:
        return asyncio.run(coroutine)  # type: ignore[arg-type]
    finally:
        asyncio.run(dispose_engine())


@celery_app.task(bind=True, name="documents.verify_original")
def verify_original_task(
    self: Task, tenant_id: str, document_id: str, job_id: str
) -> str:
    tenant_uuid, document_uuid, job_uuid = map(UUID, (tenant_id, document_id, job_id))
    try:
        return str(run_async(process_job(tenant_uuid, document_uuid, job_uuid)))
    except TransientIngestionError as exc:
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

"""Narrow Docker smoke check for storage integrity and duplicate delivery."""

import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Document, ProcessingJob, ProcessingJobStatus
from app.db.session import session_factory
from app.storage import LocalDocumentStorage
from app.tasks import verify_original_task

SMOKE_COLLECTION_ID = UUID("33333333-3333-4333-8333-333333333333")


async def verify() -> None:
    async with session_factory() as session:
        document = await session.scalar(
            select(Document)
            .where(Document.collection_id == SMOKE_COLLECTION_ID)
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        if document is None:
            raise RuntimeError("Smoke document not found")
        job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.document_id == document.id,
                ProcessingJob.tenant_id == document.tenant_id,
            )
        )
        if job is None or job.status != ProcessingJobStatus.SUCCEEDED:
            raise RuntimeError("Smoke job did not succeed")
        attempts = job.attempt_count
        storage = LocalDocumentStorage(get_settings().document_storage_path)
        if not await storage.verify(document.storage_key, document.checksum_sha256):
            raise RuntimeError("Stored checksum verification failed")
        verify_original_task.apply_async(
            args=[str(document.tenant_id), str(document.id), str(job.id)]
        )

    await asyncio.sleep(3)
    async with session_factory() as session:
        repeated = await session.get(ProcessingJob, job.id)
        if repeated is None or repeated.status != ProcessingJobStatus.SUCCEEDED:
            raise RuntimeError("Duplicate delivery changed terminal state")
        if repeated.attempt_count != attempts:
            raise RuntimeError("Duplicate delivery repeated completed work")
    print("storage-checksum=verified duplicate-delivery=idempotent")


if __name__ == "__main__":
    asyncio.run(verify())

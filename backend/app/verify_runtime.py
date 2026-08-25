"""Docker smoke check for chunk traceability and duplicate delivery."""

import asyncio
from uuid import UUID

from sqlalchemy import select

from app.db.models import (
    Document,
    DocumentChunk,
    DocumentSourceUnit,
    ProcessingJob,
    ProcessingJobStatus,
)
from app.db.session import session_factory
from app.tasks import verify_original_task

SMOKE_COLLECTION_ID = UUID("33333333-3333-4333-8333-333333333333")


async def signatures(document_id: UUID) -> tuple[tuple[object, ...], ...]:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        ).all()
        for chunk in rows:
            unit = await session.get(DocumentSourceUnit, chunk.source_unit_id)
            if (
                unit is None
                or unit.normalized_text[chunk.start_offset : chunk.end_offset]
                != chunk.content
            ):
                raise RuntimeError("Chunk offsets do not resolve")
        return tuple(
            (
                row.chunk_index,
                row.content_hash,
                row.pipeline_fingerprint,
                row.page_number,
                row.section,
                row.start_offset,
                row.end_offset,
            )
            for row in rows
        )


async def verify() -> None:
    async with session_factory() as session:
        documents = (
            await session.scalars(
                select(Document)
                .where(
                    Document.collection_id == SMOKE_COLLECTION_ID,
                    Document.filename.in_(["traceable.pdf", "traceable.docx"]),
                )
                .order_by(Document.created_at.desc())
                .limit(2)
            )
        ).all()
        if len(documents) != 2:
            raise RuntimeError("Expected PDF and DOCX smoke documents")
        evidence: list[tuple[str, int]] = []
        for document in documents:
            job = await session.scalar(
                select(ProcessingJob).where(ProcessingJob.document_id == document.id)
            )
            if job is None or job.status != ProcessingJobStatus.SUCCEEDED:
                raise RuntimeError("Smoke job did not succeed")
            signature = await signatures(document.id)
            if not signature:
                raise RuntimeError("Smoke document has no chunks")
            evidence.append((document.content_type, len(signature)))
        repeated_document = documents[0]
        repeated_job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.document_id == repeated_document.id
            )
        )
        assert repeated_job is not None
        attempts = repeated_job.attempt_count
        before = await signatures(repeated_document.id)
        verify_original_task.apply_async(
            args=[
                str(repeated_document.tenant_id),
                str(repeated_document.id),
                str(repeated_job.id),
            ]
        )

    await asyncio.sleep(3)
    after = await signatures(repeated_document.id)
    async with session_factory() as session:
        repeated_job = await session.get(ProcessingJob, repeated_job.id)
        if (
            repeated_job is None
            or repeated_job.attempt_count != attempts
            or before != after
        ):
            raise RuntimeError("Duplicate delivery changed deterministic output")
    summary = {
        "pdf_chunks": next(
            count for mime, count in evidence if mime == "application/pdf"
        ),
        "docx_chunks": next(
            count for mime, count in evidence if mime != "application/pdf"
        ),
    }
    print(f"traceability=verified determinism=verified counts={summary}")


if __name__ == "__main__":
    asyncio.run(verify())

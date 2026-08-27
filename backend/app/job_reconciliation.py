import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import ProcessingJob, ProcessingJobStatus
from app.db.session import dispose_engine, session_factory
from app.tasks import delete_document_task, verify_original_task


async def republish_stale_jobs(
    *, max_jobs: int = 100, stale_after_seconds: int = 60
) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    async with session_factory() as session:
        jobs = (
            await session.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.status.in_(
                        (ProcessingJobStatus.QUEUED, ProcessingJobStatus.RETRYING)
                    ),
                    ProcessingJob.updated_at <= cutoff,
                )
                .order_by(ProcessingJob.updated_at, ProcessingJob.id)
                .limit(max_jobs)
            )
        ).all()
    published = 0
    for job in jobs:
        task = (
            delete_document_task
            if job.operation == "document_deletion"
            else verify_original_task
        )
        task.apply_async(args=[str(job.tenant_id), str(job.document_id), str(job.id)])
        published += 1
    return published


def main() -> None:
    try:
        count = asyncio.run(republish_stale_jobs())
        print(f"republished_jobs={count}")
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()

import hashlib
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app import tasks
from app.db.models import (
    Collection,
    Document,
    Organization,
    ProcessingJob,
    ProcessingJobStatus,
)
from app.db.session import session_factory

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


async def make_job(storage_root: str, *, create_file: bool) -> tuple[object, ...]:
    tenant_id, collection_id, document_id, job_id = (uuid4() for _ in range(4))
    content = b"%PDF-1.7\nintegration"
    checksum = hashlib.sha256(content).hexdigest()
    key = f"{tenant_id.hex}/{document_id.hex}/original.pdf"
    if create_file:
        path = tasks.LocalDocumentStorage(storage_root).path_for_validation(key)
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    async with session_factory() as session, session.begin():
        session.add(Organization(id=tenant_id, name="Worker Test", slug=str(tenant_id)))
        await session.flush()
        session.add(Collection(id=collection_id, tenant_id=tenant_id, name="Docs"))
        await session.flush()
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                filename="test.pdf",
                storage_key=key,
                content_type="application/pdf",
                size_bytes=len(content),
                checksum_sha256=checksum,
            )
        )
        await session.flush()
        session.add(
            ProcessingJob(
                id=job_id,
                tenant_id=tenant_id,
                document_id=document_id,
                operation="verify_original",
            )
        )
    return tenant_id, document_id, job_id


async def cleanup(tenant_id: object) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(delete(Organization).where(Organization.id == tenant_id))


async def test_success_and_duplicate_delivery_are_idempotent(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(document_storage_path=root)
    )
    tenant_id, document_id, job_id = await make_job(root, create_file=True)
    try:
        assert await tasks.process_job(tenant_id, document_id, job_id) == "succeeded"
        assert (
            await tasks.process_job(tenant_id, document_id, job_id)
            == "already-complete"
        )
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status == ProcessingJobStatus.SUCCEEDED
            assert job.attempt_count == 1
            assert job.started_at is not None
            assert job.finished_at is not None
    finally:
        await cleanup(tenant_id)


async def test_missing_file_is_a_permanent_failure(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(document_storage_path=root)
    )
    tenant_id, document_id, job_id = await make_job(root, create_file=False)
    try:
        assert await tasks.process_job(tenant_id, document_id, job_id) == "failed"
        async with session_factory() as session:
            job = await session.scalar(
                select(ProcessingJob).where(ProcessingJob.id == job_id)
            )
            assert job is not None
            assert job.status == ProcessingJobStatus.FAILED
            assert job.error_message == tasks.SAFE_MISSING
    finally:
        await cleanup(tenant_id)


async def test_transient_storage_failure_moves_job_to_retrying(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(document_storage_path=root)
    )
    tenant_id, document_id, job_id = await make_job(root, create_file=True)

    async def unavailable(*_: object) -> bool:
        raise OSError("simulated transient storage outage")

    monkeypatch.setattr(tasks.LocalDocumentStorage, "verify", unavailable)
    try:
        with pytest.raises(tasks.TransientIngestionError):
            await tasks.process_job(tenant_id, document_id, job_id)
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status == ProcessingJobStatus.RETRYING
            assert job.error_message == tasks.SAFE_TRANSIENT
    finally:
        await cleanup(tenant_id)

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
    DocumentChunk,
    DocumentSourceUnit,
    Organization,
    ProcessingJob,
    ProcessingJobStatus,
)
from app.db.session import session_factory
from app.embeddings import PermanentEmbeddingError, ProviderErrorMetadata
from tests.fixture_builders import pdf_bytes

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


class FakeEmbeddingProvider:
    calls = 0

    async def embed_documents(self, texts: object) -> list[list[float]]:
        self.calls += 1
        return [[1.0] + [0.0] * 1535 for _ in texts]  # type: ignore[union-attr]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 1535


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    async def embed_documents(self, texts: object) -> list[list[float]]:
        raise PermanentEmbeddingError("synthetic permanent failure")


class QuotaEmbeddingProvider(FakeEmbeddingProvider):
    async def embed_documents(self, texts: object) -> list[list[float]]:
        self.calls += 1
        raise PermanentEmbeddingError(
            "synthetic quota failure",
            ProviderErrorMetadata(429, "insufficient_quota", "quota", False),
        )


async def make_job(
    storage_root: str, *, create_file: bool, content: bytes | None = None
) -> tuple[object, ...]:
    tenant_id, collection_id, document_id, job_id = (uuid4() for _ in range(4))
    content = content or pdf_bytes(["Integration document with traceable text."])
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


def settings(root: str) -> SimpleNamespace:
    return SimpleNamespace(
        document_storage_path=root,
        parser_max_pdf_pages=10,
        parser_max_extracted_chars=10_000,
        parser_max_pdf_stream_bytes=100_000,
        parser_soft_time_limit_seconds=10,
        chunk_target_chars=100,
        chunk_max_chars=150,
        chunk_overlap_chars=10,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )


async def test_success_and_duplicate_delivery_are_idempotent(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings(root))
    tenant_id, document_id, job_id = await make_job(root, create_file=True)
    try:
        provider = FakeEmbeddingProvider()
        assert (
            await tasks.process_job(tenant_id, document_id, job_id, provider)
            == "succeeded"
        )
        assert (
            await tasks.process_job(tenant_id, document_id, job_id, provider)
            == "already-complete"
        )
        assert provider.calls == 1
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status == ProcessingJobStatus.SUCCEEDED
            assert job.attempt_count == 1
            assert job.started_at is not None
            assert job.finished_at is not None
            units = (
                await session.scalars(
                    select(DocumentSourceUnit).where(
                        DocumentSourceUnit.document_id == document_id
                    )
                )
            ).all()
            chunks = (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id
                    )
                )
            ).all()
            assert len(units) == 1
            assert len(chunks) == 1
            assert (
                units[0].normalized_text[chunks[0].start_offset : chunks[0].end_offset]
                == chunks[0].content
            )
    finally:
        await cleanup(tenant_id)


async def test_missing_file_is_a_permanent_failure(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings(root))
    tenant_id, document_id, job_id = await make_job(root, create_file=False)
    try:
        assert (
            await tasks.process_job(
                tenant_id, document_id, job_id, FakeEmbeddingProvider()
            )
            == "failed"
        )
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
    monkeypatch.setattr(tasks, "get_settings", lambda: settings(root))
    tenant_id, document_id, job_id = await make_job(root, create_file=True)

    async def unavailable(*_: object) -> bool:
        raise OSError("simulated transient storage outage")

    monkeypatch.setattr(tasks.LocalDocumentStorage, "verify", unavailable)
    try:
        with pytest.raises(tasks.TransientIngestionError):
            await tasks.process_job(
                tenant_id, document_id, job_id, FakeEmbeddingProvider()
            )
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status == ProcessingJobStatus.RETRYING
            assert job.error_message == tasks.SAFE_TRANSIENT
    finally:
        await cleanup(tenant_id)


async def test_permanent_parser_failure_is_safe_and_observable(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings(root))
    tenant_id, document_id, job_id = await make_job(
        root, create_file=True, content=b"%PDF-1.7\nmalformed"
    )
    try:
        assert (
            await tasks.process_job(
                tenant_id, document_id, job_id, FakeEmbeddingProvider()
            )
            == "failed"
        )
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status == ProcessingJobStatus.FAILED
            assert job.error_message == tasks.SAFE_PARSE
    finally:
        await cleanup(tenant_id)


async def test_embedding_failure_publishes_no_partial_chunks(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings(root))
    tenant_id, document_id, job_id = await make_job(root, create_file=True)
    try:
        assert (
            await tasks.process_job(
                tenant_id, document_id, job_id, FailingEmbeddingProvider()
            )
            == "failed"
        )
        async with session_factory() as session:
            chunks = (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id
                    )
                )
            ).all()
            job = await session.get(ProcessingJob, job_id)
            assert chunks == []
            assert job is not None
            assert job.status == ProcessingJobStatus.FAILED
            assert job.error_message == tasks.SAFE_EMBEDDING
    finally:
        await cleanup(tenant_id)


async def test_permanent_quota_failure_has_one_attempt(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings(root))
    tenant_id, document_id, job_id = await make_job(root, create_file=True)
    provider = QuotaEmbeddingProvider()
    try:
        result = await tasks.process_job(tenant_id, document_id, job_id, provider)
        assert result == "failed"
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status == ProcessingJobStatus.FAILED
            assert job.attempt_count == 1
            assert job.error_message is not None
            assert "provider_code=insufficient_quota" in job.error_message
        assert provider.calls == 1
    finally:
        await cleanup(tenant_id)


async def test_temporary_retry_delay_respects_retry_after_and_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks.secrets, "randbelow", lambda _: 0)
    assert tasks._retry_delay(0, 7) == 7
    assert tasks._retry_delay(0, tasks.MAX_TOTAL_RETRY_DELAY_SECONDS + 1) is None
    assert all(
        (delay := tasks._retry_delay(retries, None)) is not None
        and delay <= tasks.MAX_TOTAL_RETRY_DELAY_SECONDS
        for retries in range(4)
    )

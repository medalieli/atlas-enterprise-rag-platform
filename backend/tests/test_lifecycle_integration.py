import hashlib
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.models import (
    Collection,
    Conversation,
    ConversationCitation,
    ConversationMessage,
    ConversationMessageRole,
    ConversationTurn,
    ConversationTurnStatus,
    Document,
    DocumentChunk,
    DocumentIndexGeneration,
    DocumentSourceUnit,
    DocumentStatus,
    DocumentVersion,
    DocumentVersionStatus,
    IndexGenerationStatus,
    Membership,
    Organization,
    ProcessingJob,
    ProcessingJobStatus,
    User,
)
from app.db.session import session_factory
from app.embeddings import EMBEDDING_INPUT_VERSION, embedding_fingerprint
from app.retrieval import keyword_candidates
from app.tasks import process_deletion, process_job
from tests.fixture_builders import add_active_lifecycle, pdf_bytes

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


class FakeEmbeddings:
    calls = 0

    async def embed_documents(self, texts: object) -> list[list[float]]:
        self.calls += 1
        return [[1.0] + [0.0] * 1535 for _ in texts]  # type: ignore[union-attr]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 1535


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


async def add_chunk(
    session: object,
    tenant_id: object,
    document_id: object,
    version_id: object,
    generation_id: object,
    content: str,
) -> object:
    unit_id = uuid4()
    digest = hashlib.sha256(content.encode()).hexdigest()
    session.add(  # type: ignore[attr-defined]
        DocumentSourceUnit(
            id=unit_id,
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            generation_id=generation_id,
            unit_index=0,
            source_type="pdf",
            page_number=1,
            normalized_text=content,
            content_hash=digest,
        )
    )
    await session.flush()  # type: ignore[attr-defined]
    chunk = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            generation_id=generation_id,
            source_unit_id=unit_id,
            chunk_index=0,
            content=content,
            content_hash=digest,
            pipeline_fingerprint="1" * 64,
            page_number=1,
            start_offset=0,
            end_offset=len(content),
            embedding=[1.0] + [0.0] * 1535,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            embedding_input_version=EMBEDDING_INPUT_VERSION,
            embedding_fingerprint=embedding_fingerprint(
                digest, "text-embedding-3-small", 1536
            ),
            embedded_at=datetime.now(UTC),
        )
    session.add(chunk)  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]
    return chunk.id


async def test_retrieval_follows_both_active_pointers() -> None:
    tenant_id, collection_id, document_id = uuid4(), uuid4(), uuid4()
    try:
        async with session_factory() as session, session.begin():
            session.add(
                Organization(id=tenant_id, name="Lifecycle", slug=str(tenant_id))
            )
            await session.flush()
            session.add(Collection(id=collection_id, tenant_id=tenant_id, name="Docs"))
            await session.flush()
            version_1, generation_1 = await add_active_lifecycle(
                session, tenant_id, collection_id, document_id, filename="v1.pdf"
            )
            await add_chunk(
                session, tenant_id, document_id, version_1, generation_1, "legacyterm"
            )
        async with session_factory() as session:
            before = await keyword_candidates(
                session, tenant_id, collection_id, "legacyterm", 10
            )
            assert [row.document_version_id for row in before] == [version_1]

        version_2, generation_2 = uuid4(), uuid4()
        async with session_factory() as session, session.begin():
            document = await session.get(Document, document_id)
            prior = await session.get(DocumentVersion, version_1)
            session.add(
                DocumentVersion(
                    id=version_2,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    version_number=2,
                    storage_key=f"{tenant_id.hex}/{document_id.hex}/{version_2.hex}.pdf",
                    checksum_sha256="2" * 64,
                    filename="v2.pdf",
                    content_type="application/pdf",
                    size_bytes=10,
                    status=DocumentVersionStatus.ACTIVE,
                )
            )
            await session.flush()
            session.add(
                DocumentIndexGeneration(
                    id=generation_2,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    document_version_id=version_2,
                    generation_number=1,
                    status=IndexGenerationStatus.ACTIVE,
                    parser_version="pypdf-6-v1",
                    cleaner_version="clean-v1",
                    chunker_version="chunk-v1",
                    embedding_input_version="embedding-input-v1",
                    embedding_provider="fake",
                    embedding_model="text-embedding-3-small",
                    embedding_dimensions=1536,
                    text_search_configuration="simple",
                    configuration_fingerprint="2" * 64,
                )
            )
            await session.flush()
            await add_chunk(
                session, tenant_id, document_id, version_2, generation_2, "currentterm"
            )
            assert document is not None and prior is not None
            document.active_version_id = version_2
            prior.status = DocumentVersionStatus.SUPERSEDED
            current = await session.get(DocumentVersion, version_2)
            assert current is not None
            current.active_generation_id = generation_2
        async with session_factory() as session:
            assert await keyword_candidates(
                session, tenant_id, collection_id, "legacyterm", 10
            ) == []
            after = await keyword_candidates(
                session, tenant_id, collection_id, "currentterm", 10
            )
            assert [row.document_version_id for row in after] == [version_2]
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )


async def test_reindex_switches_generation_without_changing_source(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, collection_id, document_id, job_id = (uuid4() for _ in range(4))
    content = pdf_bytes(["Reindexed source remains immutable."])
    checksum = hashlib.sha256(content).hexdigest()
    key = f"{tenant_id.hex}/{document_id.hex}/versions/{document_id.hex}/original.pdf"
    storage_class = __import__(
        "app.tasks", fromlist=["LocalDocumentStorage"]
    ).LocalDocumentStorage
    path = storage_class(str(tmp_path)).path_for_validation(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr("app.tasks.get_settings", lambda: settings(str(tmp_path)))
    try:
        async with session_factory() as session, session.begin():
            session.add(Organization(id=tenant_id, name="Reindex", slug=str(tenant_id)))
            await session.flush()
            session.add(Collection(id=collection_id, tenant_id=tenant_id, name="Docs"))
            await session.flush()
            version_id, old_generation = await add_active_lifecycle(
                session,
                tenant_id,
                collection_id,
                document_id,
                filename="source.pdf",
                size_bytes=len(content),
                checksum=checksum,
            )
            candidate = uuid4()
            session.add(
                DocumentIndexGeneration(
                    id=candidate,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    generation_number=2,
                    parser_version="pypdf-6-v1",
                    cleaner_version="clean-v1",
                    chunker_version="chunk-v1",
                    embedding_input_version="embedding-input-v1",
                    embedding_provider="fake",
                    embedding_model="text-embedding-3-small",
                    embedding_dimensions=1536,
                    text_search_configuration="simple",
                    configuration_fingerprint="3" * 64,
                    processing_job_id=job_id,
                )
            )
            await session.flush()
            session.add(
                ProcessingJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    generation_id=candidate,
                    operation="reindex",
                )
            )
        provider = FakeEmbeddings()
        result = await process_job(tenant_id, document_id, job_id, provider)
        assert result == "succeeded"
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            version = await session.get(DocumentVersion, document_id)
            old = await session.get(DocumentIndexGeneration, old_generation)
            assert document is not None and document.active_version_id == document_id
            assert version is not None and version.active_generation_id == candidate
            assert old is not None and old.status == IndexGenerationStatus.SUPERSEDED
            assert version.storage_key == key
            assert provider.calls == 1
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )


async def test_hard_deletion_keeps_only_logical_tombstone(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, collection_id, document_id, job_id, user_id = (
        uuid4() for _ in range(5)
    )
    monkeypatch.setattr("app.tasks.get_settings", lambda: settings(str(tmp_path)))
    try:
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    Organization(id=tenant_id, name="Delete", slug=str(tenant_id)),
                    User(
                        id=user_id,
                        issuer="https://issuer.test",
                        subject=str(user_id),
                        email=f"{user_id}@example.test",
                    ),
                ]
            )
            await session.flush()
            session.add(Membership(tenant_id=tenant_id, user_id=user_id, role="admin"))
            session.add(Collection(id=collection_id, tenant_id=tenant_id, name="Docs"))
            await session.flush()
            version_id, generation_id = await add_active_lifecycle(
                session, tenant_id, collection_id, document_id, filename="source.pdf"
            )
            chunk_id = await add_chunk(
                session,
                tenant_id,
                document_id,
                version_id,
                generation_id,
                "content that must be purged",
            )
            conversation_id, turn_id, message_id = uuid4(), uuid4(), uuid4()
            session.add(
                Conversation(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    created_by_user_id=user_id,
                )
            )
            await session.flush()
            session.add(
                ConversationTurn(
                    id=turn_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    conversation_id=conversation_id,
                    created_by_user_id=user_id,
                    sequence_number=1,
                    idempotency_key="turn-1",
                    request_fingerprint="a" * 64,
                    status=ConversationTurnStatus.COMPLETED,
                    original_question="What is the policy?",
                    top_k=5,
                )
            )
            await session.flush()
            session.add(
                ConversationMessage(
                    id=message_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    sequence_number=1,
                    role=ConversationMessageRole.ASSISTANT,
                    content="The retained answer text cited a source.",
                )
            )
            await session.flush()
            session.add(
                ConversationCitation(
                    assistant_message_id=message_id,
                    citation_order=1,
                    source_id="S1",
                    tenant_id=tenant_id,
                    chunk_id=chunk_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    generation_id=generation_id,
                    page_number=1,
                    start_offset=0,
                    end_offset=10,
                    document_metadata={"private": "remove"},
                    exact_excerpt="content that must be purged",
                )
            )
            document = await session.get(Document, document_id)
            assert document is not None
            document.status = DocumentStatus.DELETING
            session.add(
                ProcessingJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    operation="document_deletion",
                )
            )

        assert await process_deletion(tenant_id, document_id, job_id) == "succeeded"
        assert (
            await process_deletion(tenant_id, document_id, job_id)
            == "stale"
        )
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            job = await session.get(ProcessingJob, job_id)
            assert document is not None and document.status == DocumentStatus.DELETED
            assert document.active_version_id is None
            assert document.storage_key is None
            assert document.document_metadata == {}
            assert job is not None and job.status == ProcessingJobStatus.SUCCEEDED
            assert not (
                await session.scalars(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == document_id
                    )
                )
            ).all()
            citation = await session.scalar(
                select(ConversationCitation).where(
                    ConversationCitation.assistant_message_id == message_id
                )
            )
            message = await session.get(ConversationMessage, message_id)
            assert citation is not None and citation.source_status == "deleted"
            assert citation.document_id is None
            assert citation.document_version_id is None
            assert citation.chunk_id is None
            assert citation.exact_excerpt is None
            assert citation.document_metadata == {}
            assert message is not None
            assert message.content == "The retained answer text cited a source."
            assert not (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id
                    )
                )
            ).all()
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )
            await session.execute(delete(User).where(User.id == user_id))

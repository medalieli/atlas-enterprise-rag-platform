import os
from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Collection,
    Conversation,
    Document,
    DocumentChunk,
    DocumentSourceUnit,
    Membership,
    Organization,
    User,
)
from app.db.session import engine

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]

REVISION = "a1b2c3d4e5f6"


async def test_database_is_at_expected_alembic_revision() -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )

    assert revision == REVISION


async def test_authentication_constraints_roles_and_indexes_exist() -> None:
    async with engine.connect() as connection:
        indexes = set(
            await connection.scalars(
                text(
                    "SELECT indexname FROM pg_indexes WHERE indexname IN "
                    "('ix_users_issuer_subject', "
                    "'ix_memberships_tenant_enabled', "
                    "'ix_processing_jobs_requested_by')"
                )
            )
        )
        roles = set(
            await connection.scalars(
                text(
                    "SELECT enumlabel FROM pg_enum JOIN pg_type "
                    "ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE typname = 'membership_role'"
                )
            )
        )
    assert indexes == {
        "ix_users_issuer_subject",
        "ix_memberships_tenant_enabled",
        "ix_processing_jobs_requested_by",
    }
    assert roles == {"viewer", "editor", "admin"}


async def test_embedding_hnsw_cosine_index_exists() -> None:
    async with engine.connect() as connection:
        definition = await connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_document_chunks_embedding_hnsw_cosine'"
            )
        )
    assert definition is not None
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition
    assert "WHERE (embedding IS NOT NULL)" in definition


async def test_generated_search_vector_and_gin_index_are_explicit() -> None:
    async with engine.connect() as connection:
        generated = await connection.scalar(
            text(
                "SELECT generation_expression FROM information_schema.columns "
                "WHERE table_name = 'document_chunks' "
                "AND column_name = 'search_vector'"
            )
        )
        definition = await connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_document_chunks_search_vector_gin'"
            )
        )
    assert generated is not None
    assert "'simple'::regconfig" in generated
    assert "setweight" in generated
    assert "section" in generated
    assert "content" in generated
    assert definition is not None
    assert "USING gin (search_vector)" in definition


async def test_document_metadata_constraints_and_indexes_exist() -> None:
    expected_indexes = {
        "ix_documents_tenant_collection_created_at",
        "ix_documents_tenant_collection_content_type",
        "ix_documents_tenant_collection_filename",
        "ix_documents_metadata_tags_gin",
        "ix_documents_metadata_department",
        "ix_documents_metadata_document_type",
        "ix_documents_metadata_language",
        "ix_documents_metadata_effective_date",
    }
    async with engine.connect() as connection:
        indexes = set(
            (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'documents'"
                    )
                )
            ).scalars()
        )
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'documents'::regclass"
                    )
                )
            ).scalars()
        )
    assert expected_indexes <= indexes
    assert "ck_documents_metadata_object" in constraints
    assert "ck_documents_metadata_size" in constraints


async def test_full_text_operator_is_plannable_without_assuming_index_choice() -> None:
    async with engine.connect() as connection:
        plan_rows = (
            await connection.execute(
                text(
                    "EXPLAIN (COSTS OFF) "
                    "SELECT id FROM document_chunks "
                    "WHERE search_vector @@ "
                    "websearch_to_tsquery('simple'::regconfig, 'ENTREFUND30')"
                )
            )
        ).scalars().all()
    plan = "\n".join(plan_rows)
    assert "search_vector" in plan
    assert "@@" in plan


async def test_tenant_and_uniqueness_constraints_are_enforced() -> None:
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    user_id = uuid4()
    collection_a_id = uuid4()
    collection_b_id = uuid4()
    document_a_id = uuid4()
    source_unit_id = uuid4()

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                insert(Organization),
                [
                    {"id": tenant_a_id, "name": "Tenant A", "slug": f"a-{tenant_a_id}"},
                    {"id": tenant_b_id, "name": "Tenant B", "slug": f"b-{tenant_b_id}"},
                ],
            )
            await connection.execute(
                insert(User).values(
                    id=user_id,
                    issuer="https://issuer.test",
                    subject=str(user_id),
                    email=f"{user_id}@example.test",
                    display_name="Test User",
                )
            )
            await connection.execute(
                insert(Membership).values(tenant_id=tenant_a_id, user_id=user_id)
            )
            await connection.execute(
                insert(Collection),
                [
                    {"id": collection_a_id, "tenant_id": tenant_a_id, "name": "Docs"},
                    {"id": collection_b_id, "tenant_id": tenant_b_id, "name": "Docs"},
                ],
            )
            await connection.execute(
                insert(Document).values(
                    id=document_a_id,
                    tenant_id=tenant_a_id,
                    collection_id=collection_a_id,
                    filename="guide.pdf",
                    storage_key=f"documents/{document_a_id}",
                    content_type="application/pdf",
                    size_bytes=100,
                    checksum_sha256="0" * 64,
                )
            )
            await connection.execute(
                insert(DocumentSourceUnit).values(
                    id=source_unit_id,
                    tenant_id=tenant_a_id,
                    document_id=document_a_id,
                    unit_index=0,
                    source_type="pdf",
                    page_number=1,
                    normalized_text="First chunk",
                    content_hash="0" * 64,
                )
            )
            await connection.execute(
                insert(DocumentChunk).values(
                    tenant_id=tenant_a_id,
                    document_id=document_a_id,
                    source_unit_id=source_unit_id,
                    chunk_index=0,
                    content="First chunk",
                    content_hash="0" * 64,
                    pipeline_fingerprint="0" * 64,
                    page_number=1,
                    start_offset=0,
                    end_offset=11,
                )
            )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        insert(Collection).values(
                            tenant_id=tenant_a_id,
                            name="Docs",
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        insert(Document).values(
                            tenant_id=tenant_b_id,
                            collection_id=collection_a_id,
                            filename="cross-tenant.pdf",
                            storage_key="documents/cross-tenant",
                            content_type="application/pdf",
                            size_bytes=100,
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        insert(DocumentChunk).values(
                            tenant_id=tenant_a_id,
                            document_id=document_a_id,
                            source_unit_id=source_unit_id,
                            chunk_index=0,
                            content="Duplicate position",
                            content_hash="0" * 64,
                            pipeline_fingerprint="0" * 64,
                            start_offset=0,
                            end_offset=18,
                        )
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        insert(Conversation).values(
                            tenant_id=tenant_b_id,
                            collection_id=collection_b_id,
                            created_by_user_id=user_id,
                        )
                    )
        finally:
            await transaction.rollback()

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

REVISION = "c5d9e2f1a804"


async def test_database_is_at_expected_alembic_revision() -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )

    assert revision == REVISION


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

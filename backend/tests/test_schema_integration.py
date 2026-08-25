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

REVISION = "8b1f2d4e6a70"


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
                insert(DocumentChunk).values(
                    tenant_id=tenant_a_id,
                    document_id=document_a_id,
                    chunk_index=0,
                    content="First chunk",
                    page_number=1,
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
                            chunk_index=0,
                            content="Duplicate position",
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

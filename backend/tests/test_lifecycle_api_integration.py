import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.api import lifecycle
from app.auth import TrustedPrincipal, get_trusted_principal
from app.db.models import (
    Collection,
    DocumentVersion,
    Membership,
    Organization,
    ProcessingJob,
    User,
)
from app.db.session import session_factory
from app.main import app
from tests.fixture_builders import add_active_lifecycle, pdf_bytes

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


def settings(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        document_storage_path=str(root),
        max_upload_bytes=100_000,
        max_docx_uncompressed_bytes=100_000,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )


async def test_replacement_api_is_idempotent_tenant_safe_and_path_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, other_tenant_id, user_id = uuid4(), uuid4(), uuid4()
    collection_id, other_collection_id, document_id = uuid4(), uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Organization(id=tenant_id, name="Lifecycle", slug=str(tenant_id)),
                Organization(
                    id=other_tenant_id, name="Other", slug=str(other_tenant_id)
                ),
                User(
                    id=user_id,
                    issuer="https://issuer.test",
                    subject=str(user_id),
                    email=f"{user_id}@example.test",
                ),
            ]
        )
        await session.flush()
        session.add(Membership(tenant_id=tenant_id, user_id=user_id, role="editor"))
        session.add_all(
            [
                Collection(id=collection_id, tenant_id=tenant_id, name="Docs"),
                Collection(
                    id=other_collection_id,
                    tenant_id=other_tenant_id,
                    name="Other",
                ),
            ]
        )
        await session.flush()
        await add_active_lifecycle(
            session, tenant_id, collection_id, document_id, filename="version-1.pdf"
        )

    monkeypatch.setattr(lifecycle, "get_settings", lambda: settings(tmp_path))
    queued: list[list[str]] = []
    monkeypatch.setattr(
        lifecycle.verify_original_task,
        "apply_async",
        lambda *, args: queued.append(args),
    )
    principal = TrustedPrincipal(tenant_id, user_id)

    async def principal_override() -> TrustedPrincipal:
        return principal

    app.dependency_overrides[get_trusted_principal] = principal_override
    content = pdf_bytes(["Replacement policy version two."])
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            request = {
                "files": {"file": ("version-2.pdf", content, "application/pdf")},
                "headers": {"Idempotency-Key": "replacement-1"},
                "data": {"metadata": '{"department":"Legal"}'},
            }
            first = await client.post(
                f"/collections/{collection_id}/documents/{document_id}/versions",
                **request,
            )
            replay = await client.post(
                f"/collections/{collection_id}/documents/{document_id}/versions",
                **request,
            )
            assert first.status_code == replay.status_code == 202
            assert first.json() == replay.json()
            assert len(queued) == 1

            versions = await client.get(
                f"/collections/{collection_id}/documents/{document_id}/versions"
            )
            assert versions.status_code == 200
            assert [row["version_number"] for row in versions.json()] == [1, 2]
            assert all("storage_key" not in row for row in versions.json())

            cross_collection = await client.post(
                f"/collections/{other_collection_id}/documents/{document_id}/reindex",
                headers={"Idempotency-Key": "cross-tenant"},
            )
            assert cross_collection.status_code == 404

            async with session_factory() as session, session.begin():
                membership = await session.scalar(
                    select(Membership).where(
                        Membership.tenant_id == tenant_id,
                        Membership.user_id == user_id,
                    )
                )
                assert membership is not None
                membership.role = "viewer"
            forbidden_replacement = await client.post(
                f"/collections/{collection_id}/documents/{document_id}/versions",
                files={"file": ("version-3.pdf", content, "application/pdf")},
                headers={"Idempotency-Key": "replacement-viewer"},
            )
            forbidden_reindex = await client.post(
                f"/collections/{collection_id}/documents/{document_id}/reindex",
                headers={"Idempotency-Key": "reindex-viewer"},
            )
            forbidden_delete = await client.delete(
                f"/collections/{collection_id}/documents/{document_id}"
            )
            assert forbidden_replacement.status_code == 403
            assert forbidden_reindex.status_code == 403
            assert forbidden_delete.status_code == 403

        async with session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(DocumentVersion.id)).where(
                        DocumentVersion.document_id == document_id
                    )
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count(ProcessingJob.id)).where(
                        ProcessingJob.document_id == document_id,
                        ProcessingJob.operation == "replacement_ingestion",
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(
                    Organization.id.in_([tenant_id, other_tenant_id])
                )
            )
            await session.execute(delete(User).where(User.id == user_id))

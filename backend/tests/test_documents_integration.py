import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.api import documents
from app.auth import TrustedPrincipal, get_trusted_principal
from app.db.models import Collection, Document, Membership, Organization, User
from app.db.session import session_factory
from app.main import app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


async def seed() -> tuple[TrustedPrincipal, object, object, object, object]:
    tenant_id, other_tenant_id, user_id = uuid4(), uuid4(), uuid4()
    collection_id, other_collection_id = uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Organization(id=tenant_id, name="Upload Tenant", slug=str(tenant_id)),
                Organization(
                    id=other_tenant_id,
                    name="Other Tenant",
                    slug=str(other_tenant_id),
                ),
                User(id=user_id, email=f"{user_id}@example.test"),
            ]
        )
        await session.flush()
        session.add(Membership(tenant_id=tenant_id, user_id=user_id))
        session.add_all(
            [
                Collection(id=collection_id, tenant_id=tenant_id, name="Docs"),
                Collection(
                    id=other_collection_id,
                    tenant_id=other_tenant_id,
                    name="Other Docs",
                ),
            ]
        )
    return (
        TrustedPrincipal(tenant_id, user_id),
        collection_id,
        other_collection_id,
        other_tenant_id,
        user_id,
    )


async def test_upload_status_cross_tenant_and_queue_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        principal,
        collection_id,
        other_collection_id,
        other_tenant_id,
        user_id,
    ) = await seed()
    settings = SimpleNamespace(
        document_storage_path=str(tmp_path),
        max_upload_bytes=1024,
        max_docx_uncompressed_bytes=4096,
    )
    monkeypatch.setattr(documents, "get_settings", lambda: settings)
    monkeypatch.setattr(documents.verify_original_task, "apply_async", lambda **_: None)

    async def principal_override() -> TrustedPrincipal:
        return principal

    app.dependency_overrides[get_trusted_principal] = principal_override
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                f"/collections/{collection_id}/documents",
                files={"file": ("../safe.pdf", b"%PDF-1.7\nvalid", "application/pdf")},
            )
            assert response.status_code == 202
            body = response.json()
            assert body["original_filename"] == "safe.pdf"
            status_response = await client.get(f"/processing-jobs/{body['job_id']}")
            assert status_response.status_code == 200
            assert status_response.json()["status"] == "queued"
            cross_tenant = await client.post(
                f"/collections/{other_collection_id}/documents",
                files={"file": ("safe.pdf", b"%PDF-1.7\nvalid", "application/pdf")},
            )
            assert cross_tenant.status_code == 404

            def queue_down(**_: object) -> None:
                raise OSError("simulated broker outage")

            monkeypatch.setattr(
                documents.verify_original_task, "apply_async", queue_down
            )
            unavailable = await client.post(
                f"/collections/{collection_id}/documents",
                files={"file": ("second.pdf", b"%PDF-1.7\nvalid", "application/pdf")},
            )
            assert unavailable.status_code == 503
            async with session_factory() as session:
                count = await session.scalar(
                    select(func.count(Document.id)).where(
                        Document.tenant_id == principal.tenant_id
                    )
                )
                assert count == 1
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(
                    Organization.id.in_([principal.tenant_id, other_tenant_id])
                )
            )
            await session.execute(delete(User).where(User.id == user_id))

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.api import documents
from app.auth import TrustedPrincipal, get_trusted_principal
from app.db.models import (
    Collection,
    Document,
    DocumentVersion,
    Membership,
    Organization,
    ProcessingJob,
    User,
)
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
                User(
                    id=user_id,
                    issuer="https://issuer.test",
                    subject=str(user_id),
                    email=f"{user_id}@example.test",
                ),
            ]
        )
        await session.flush()
        session.add(Membership(tenant_id=tenant_id, user_id=user_id, role="owner"))
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
    queued: list[list[str]] = []

    def capture_queue(*, args: list[str]) -> None:
        queued.append(args)

    monkeypatch.setattr(documents.verify_original_task, "apply_async", capture_queue)

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
                data={
                    "metadata": (
                        '{"tags":["Finance","finance"],"department":"Legal",'
                        '"document_type":"policy","language":"en",'
                        '"effective_date":"2026-01-02"}'
                    )
                },
            )
            assert response.status_code == 202
            body = response.json()
            assert body["original_filename"] == "safe.pdf"
            async with session_factory() as session:
                stored = await session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == body["document_id"]
                    )
                )
            assert stored is not None
            assert stored.document_metadata == {
                "tags": ["finance"],
                "department": "legal",
                "document_type": "policy",
                "language": "en",
                "effective_date": "2026-01-02",
            }
            assert queued == [
                [str(principal.tenant_id), body["document_id"], body["job_id"]]
            ]
            async with session_factory() as session:
                audit_job = await session.scalar(
                    select(ProcessingJob).where(ProcessingJob.id == body["job_id"])
                )
            assert audit_job is not None
            assert audit_job.requested_by_user_id == principal.user_id
            status_response = await client.get(f"/processing-jobs/{body['job_id']}")
            assert status_response.status_code == 200
            assert status_response.json()["status"] == "queued"
            cross_tenant = await client.post(
                f"/collections/{other_collection_id}/documents",
                files={"file": ("safe.pdf", b"%PDF-1.7\nvalid", "application/pdf")},
            )
            assert cross_tenant.status_code == 404

            ownership_override = await client.post(
                f"/collections/{collection_id}/documents",
                files={"file": ("unsafe.pdf", b"%PDF-1.7\nvalid", "application/pdf")},
                data={
                    "metadata": ('{"tenant_id":"00000000-0000-0000-0000-000000000000"}')
                },
            )
            assert ownership_override.status_code == 422

            def queue_down(**_: object) -> None:
                raise OSError("simulated broker outage")

            monkeypatch.setattr(
                documents.verify_original_task, "apply_async", queue_down
            )
            unavailable = await client.post(
                f"/collections/{collection_id}/documents",
                files={"file": ("second.pdf", b"%PDF-1.7\nvalid", "application/pdf")},
            )
            assert unavailable.status_code == 202
            async with session_factory() as session:
                count = await session.scalar(
                    select(func.count(Document.id)).where(
                        Document.tenant_id == principal.tenant_id
                    )
                )
                assert count == 2
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(
                    Organization.id.in_([principal.tenant_id, other_tenant_id])
                )
            )
            await session.execute(delete(User).where(User.id == user_id))

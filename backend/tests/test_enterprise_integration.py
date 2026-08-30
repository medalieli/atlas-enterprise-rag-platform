import os
from hashlib import sha256
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.auth import (
    ExternalIdentity,
    TrustedPrincipal,
    get_trusted_principal,
    verify_external_identity,
)
from app.db.models import (
    AuditEvent,
    Collection,
    CollectionGrant,
    Invitation,
    Membership,
    MembershipRole,
    Organization,
    User,
)
from app.db.session import session_factory
from app.main import app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1", reason="database required"
    ),
]


def invitation_token(link: str) -> str:
    return parse_qs(urlparse(link).fragment)["token"][0]


async def test_invitation_hash_acceptance_grant_revocation_and_audit_immutability() -> (
    None
):
    tenant_id, owner_id, collection_id = uuid4(), uuid4(), uuid4()
    issuer = "https://issuer.enterprise.test"
    async with session_factory() as session, session.begin():
        session.add(
            Organization(id=tenant_id, name="Enterprise", slug=f"e-{tenant_id}")
        )
        session.add(
            User(
                id=owner_id, issuer=issuer, subject="owner", email="owner@example.test"
            )
        )
        await session.flush()
        session.add(
            Membership(tenant_id=tenant_id, user_id=owner_id, role=MembershipRole.OWNER)
        )
        session.add(
            Collection(id=collection_id, tenant_id=tenant_id, name="Restricted")
        )
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        tenant_id, owner_id
    )
    app.dependency_overrides[verify_external_identity] = lambda: ExternalIdentity(
        issuer, "viewer-sub", "viewer@example.test", True
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                f"/organizations/{tenant_id}/invitations",
                json={
                    "email": "viewer@example.test",
                    "role": "member",
                    "grants": [{"collection_id": str(collection_id), "role": "viewer"}],
                },
            )
            assert created.status_code == 201, created.text
            token = invitation_token(created.json()["invitation_link"])
            async with session_factory() as session:
                invitation = await session.scalar(
                    select(Invitation).where(Invitation.id == created.json()["id"])
                )
                assert invitation is not None
                assert invitation.token_hash == sha256(token.encode()).hexdigest()
                assert token not in invitation.token_hash
            unchanged = await client.patch(
                f"/organizations/{tenant_id}/invitations/{created.json()['id']}",
                json={
                    "email": " VIEWER@EXAMPLE.TEST ",
                    "role": "member",
                    "grants": [{"collection_id": str(collection_id), "role": "viewer"}],
                },
            )
            assert unchanged.status_code == 200
            assert unchanged.json()["token_rotated"] is False
            assert unchanged.json()["invitation_link"] is None
            app.dependency_overrides[verify_external_identity] = (
                lambda: ExternalIdentity(
                    issuer, "wrong-subject", "wrong@example.test", True
                )
            )
            wrong_identity = await client.post(
                "/invitations/accept", json={"token": token}
            )
            assert wrong_identity.status_code == 403
            app.dependency_overrides[verify_external_identity] = (
                lambda: ExternalIdentity(
                    issuer, "viewer-sub", "viewer@example.test", False
                )
            )
            unverified = await client.post(
                "/invitations/accept", json={"token": token}
            )
            assert unverified.status_code == 403
            app.dependency_overrides[verify_external_identity] = (
                lambda: ExternalIdentity(
                    "https://other-issuer.test",
                    "viewer-sub",
                    "viewer@example.test",
                    True,
                )
            )
            wrong_issuer = await client.post(
                "/invitations/accept", json={"token": token}
            )
            assert wrong_issuer.status_code == 403
            app.dependency_overrides[verify_external_identity] = (
                lambda: ExternalIdentity(
                    issuer, "viewer-sub", "viewer@example.test", True
                )
            )
            accepted = await client.post("/invitations/accept", json={"token": token})
            replay = await client.post("/invitations/accept", json={"token": token})
            assert accepted.status_code == 200
            assert replay.status_code == 200
            assert replay.json()["idempotent"] is True
        async with session_factory() as session:
            invited = await session.scalar(
                select(User).where(User.issuer == issuer, User.subject == "viewer-sub")
            )
            assert invited is not None
            membership = await session.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.user_id == invited.id
                )
            )
            assert membership is not None and membership.role == MembershipRole.MEMBER
            assert (
                await session.scalar(
                    select(CollectionGrant.id).where(
                        CollectionGrant.membership_id == membership.id
                    )
                )
                is not None
            )
            event = await session.scalar(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
            )
            assert event is not None
            with pytest.raises(DBAPIError):
                await session.execute(
                    update(AuditEvent)
                    .where(AuditEvent.id == event.id)
                    .values(outcome="failure")
                )
                await session.commit()
            await session.rollback()
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )
            await session.execute(delete(User).where(User.issuer == issuer))


async def test_invitation_edit_removal_and_filtered_csv_export() -> None:
    tenant_id, owner_id, collection_id = uuid4(), uuid4(), uuid4()
    issuer = "https://issuer.finishing.test"
    async with session_factory() as session, session.begin():
        session.add(Organization(id=tenant_id, name="Finishing", slug=f"f-{tenant_id}"))
        session.add(
            User(
                id=owner_id,
                issuer=issuer,
                subject="owner",
                email="=formula@example.test",
                display_name="=Formula",
            )
        )
        await session.flush()
        session.add(
            Membership(tenant_id=tenant_id, user_id=owner_id, role=MembershipRole.OWNER)
        )
        session.add(Collection(id=collection_id, tenant_id=tenant_id, name="Policies"))
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        tenant_id, owner_id
    )
    app.dependency_overrides[verify_external_identity] = lambda: ExternalIdentity(
        issuer, "invitee", "changed@example.test", True
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                f"/organizations/{tenant_id}/invitations",
                json={"email": "old@example.test", "role": "member", "grants": []},
            )
            old_token = invitation_token(created.json()["invitation_link"])
            edited = await client.patch(
                f"/organizations/{tenant_id}/invitations/{created.json()['id']}",
                json={
                    "email": "changed@example.test",
                    "role": "admin",
                    "grants": [{"collection_id": str(collection_id), "role": "editor"}],
                },
            )
            assert edited.status_code == 200, edited.text
            current_token = invitation_token(edited.json()["invitation_link"])
            assert (
                await client.post("/invitations/accept", json={"token": old_token})
            ).status_code == 410
            replacement_id = edited.json()["id"]
            async with session_factory() as session:
                replacement = await session.get(Invitation, replacement_id)
                assert replacement is not None
                assert replacement.token_hash == sha256(
                    current_token.encode()
                ).hexdigest()
            removed = await client.post(
                f"/organizations/{tenant_id}/invitations/{replacement_id}/remove"
            )
            assert removed.status_code == 204
            active = await client.get(f"/organizations/{tenant_id}/invitations")
            assert active.json()["items"] == []
            removed_list = await client.get(
                f"/organizations/{tenant_id}/invitations",
                params={"invitation_status": "removed"},
            )
            assert removed_list.json()["items"][0]["email"].endswith(
                "@redacted.invalid"
            )
            exported = await client.get(
                f"/organizations/{tenant_id}/audit-events/export",
                params={"action": "invitation.removed"},
            )
            assert exported.status_code == 200, exported.text
            assert exported.headers["content-disposition"].startswith(
                'attachment; filename="atlas-audit-'
            )
            assert "'=Formula" in exported.text
            assert "invitation.removed" in exported.text
            assert "old@example.test" not in exported.text
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )
            await session.execute(delete(User).where(User.issuer == issuer))

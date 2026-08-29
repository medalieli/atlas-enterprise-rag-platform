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
            token = parse_qs(urlparse(created.json()["invitation_link"]).query)[
                "token"
            ][0]
            async with session_factory() as session:
                invitation = await session.scalar(
                    select(Invitation).where(Invitation.id == created.json()["id"])
                )
                assert invitation is not None
                assert invitation.token_hash == sha256(token.encode()).hexdigest()
                assert token not in invitation.token_hash
            accepted = await client.post("/invitations/accept", json={"token": token})
            replay = await client.post("/invitations/accept", json={"token": token})
            assert accepted.status_code == 200
            assert replay.status_code == 410
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

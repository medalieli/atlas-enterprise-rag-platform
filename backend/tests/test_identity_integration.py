import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.auth import ExternalIdentity, TrustedPrincipal, get_trusted_principal
from app.bootstrap_identity import bind_identity
from app.core.config import Settings
from app.db.models import (
    AuditEvent,
    Collection,
    CollectionDeletion,
    CollectionGrant,
    CollectionRole,
    Conversation,
    Document,
    DocumentIndexGeneration,
    DocumentVersion,
    Membership,
    MembershipRole,
    Organization,
    User,
)
from app.db.session import session_factory
from app.main import app
from app.storage import LocalDocumentStorage
from tests.fixture_builders import add_active_lifecycle

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


async def seed_identity(role: MembershipRole) -> tuple:
    tenant_id, user_id, collection_id = uuid4(), uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Organization(
                id=tenant_id,
                name="Auth tenant",
                slug=f"a-{tenant_id}",
            )
        )
        session.add(
            User(
                id=user_id,
                issuer="https://issuer.integration.test",
                subject=str(user_id),
                enabled=True,
            )
        )
        await session.flush()
        membership = Membership(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            enabled=True,
        )
        session.add(membership)
        session.add(
            Collection(
                id=collection_id,
                tenant_id=tenant_id,
                name="Existing",
            )
        )
        await session.flush()
        if role == MembershipRole.MEMBER:
            session.add(
                CollectionGrant(
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    membership_id=membership.id,
                    role=CollectionRole.VIEWER,
                    created_by_user_id=user_id,
                )
            )
    return tenant_id, user_id, collection_id


async def cleanup(tenant_id: object, user_id: object) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(delete(Organization).where(Organization.id == tenant_id))
        await session.execute(delete(User).where(User.id == user_id))


async def test_viewer_identity_and_collection_permissions() -> None:
    tenant_id, user_id, _ = await seed_identity(MembershipRole.MEMBER)
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        None, user_id
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            me = await client.get("/auth/me")
            listed = await client.get("/collections", params={"tenant_id": tenant_id})
            denied = await client.post(
                "/collections",
                json={"tenant_id": str(tenant_id), "name": "Denied"},
            )
            denied_delete = await client.delete(
                f"/collections/{listed.json()[0]['id']}"
            )
        assert me.status_code == 200
        assert me.json()["principal_id"] == str(user_id)
        assert me.json()["memberships"][0]["role"] == "member"
        assert listed.status_code == 200
        assert listed.json()[0]["name"] == "Existing"
        assert denied.status_code == 403
        assert denied_delete.status_code == 403
    finally:
        app.dependency_overrides.clear()
        await cleanup(tenant_id, user_id)


async def test_admin_can_create_collection_and_cross_tenant_selector_fails() -> None:
    tenant_id, user_id, _ = await seed_identity(MembershipRole.ADMIN)
    other_tenant_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Organization(
                id=other_tenant_id,
                name="Other auth tenant",
                slug=f"o-{other_tenant_id}",
            )
        )
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        None, user_id
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            created = await client.post(
                "/collections",
                json={"tenant_id": str(tenant_id), "name": "Created"},
            )
            denied = await client.get(
                "/collections", params={"tenant_id": other_tenant_id}
            )
            removed = await client.delete(f"/collections/{created.json()['id']}")
            listed = await client.get("/collections", params={"tenant_id": tenant_id})
        assert created.status_code == 201
        assert created.json()["tenant_id"] == str(tenant_id)
        assert denied.status_code == 403
        assert removed.status_code == 204
        assert [item["name"] for item in listed.json()] == ["Existing"]
    finally:
        app.dependency_overrides.clear()
        await cleanup(tenant_id, user_id)
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == other_tenant_id)
            )


async def test_collection_deletion_is_isolated_recoverable_and_idempotent(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, user_id, retained_collection_id = await seed_identity(
        MembershipRole.ADMIN
    )
    removed_collection_id, removed_document_id, retained_document_id = (
        uuid4(),
        uuid4(),
        uuid4(),
    )
    other_tenant_id, other_user_id = uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Organization(
                id=other_tenant_id,
                name="Other deletion tenant",
                slug=f"delete-{other_tenant_id}",
            )
        )
        session.add(
            User(
                id=other_user_id,
                issuer="https://issuer.integration.test",
                subject=str(other_user_id),
                enabled=True,
            )
        )
        await session.flush()
        session.add(
            Membership(
                tenant_id=other_tenant_id,
                user_id=other_user_id,
                role=MembershipRole.OWNER,
                enabled=True,
            )
        )
        session.add(
            Collection(
                id=removed_collection_id,
                tenant_id=tenant_id,
                name="Disposable",
            )
        )
        await session.flush()
        removed_version_id, _ = await add_active_lifecycle(
            session,
            tenant_id,
            removed_collection_id,
            removed_document_id,
            filename="disposable.pdf",
        )
        retained_version_id, _ = await add_active_lifecycle(
            session,
            tenant_id,
            retained_collection_id,
            retained_document_id,
            filename="retained.pdf",
        )
        session.add(
            Conversation(
                tenant_id=tenant_id,
                collection_id=removed_collection_id,
                created_by_user_id=user_id,
            )
        )
    root = tmp_path  # type: ignore[assignment]
    removed_key = (
        f"{tenant_id.hex}/{removed_document_id.hex}/versions/"
        f"{removed_version_id.hex}/original.pdf"
    )
    retained_key = (
        f"{tenant_id.hex}/{retained_document_id.hex}/versions/"
        f"{retained_version_id.hex}/original.pdf"
    )
    for key in (removed_key, retained_key):
        target = root.joinpath(*key.split("/"))  # type: ignore[union-attr]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic")
    monkeypatch.setattr(
        "app.api.identity.get_settings",
        lambda: SimpleNamespace(document_storage_path=str(root)),
    )
    original_delete = LocalDocumentStorage.delete
    failures = 1

    async def fail_once(storage: LocalDocumentStorage, key: str) -> None:
        nonlocal failures
        if failures:
            failures -= 1
            raise OSError("synthetic storage outage")
        await original_delete(storage, key)

    monkeypatch.setattr(LocalDocumentStorage, "delete", fail_once)
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        None, user_id
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            interrupted = await client.delete(f"/collections/{removed_collection_id}")
            retried = await client.delete(f"/collections/{removed_collection_id}")
            replayed = await client.delete(f"/collections/{removed_collection_id}")
            inaccessible = await client.get(
                "/collections", params={"tenant_id": tenant_id}
            )
            app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
                None, other_user_id
            )
            cross_tenant = await client.delete(f"/collections/{removed_collection_id}")
        assert interrupted.status_code == 503
        assert retried.status_code == 204
        assert replayed.status_code == 204
        assert cross_tenant.status_code == 404
        assert [item["id"] for item in inaccessible.json()] == [
            str(retained_collection_id)
        ]
        assert not root.joinpath(*removed_key.split("/")).exists()  # type: ignore[union-attr]
        assert root.joinpath(*retained_key.split("/")).exists()  # type: ignore[union-attr]
        async with session_factory() as session:
            assert await session.get(Collection, removed_collection_id) is None
            assert await session.get(Document, removed_document_id) is None
            assert await session.get(DocumentVersion, removed_version_id) is None
            assert (
                await session.scalar(
                    select(func.count(DocumentIndexGeneration.id)).where(
                        DocumentIndexGeneration.document_id == removed_document_id
                    )
                )
                == 0
            )
            deletion = await session.scalar(
                select(CollectionDeletion).where(
                    CollectionDeletion.collection_id == removed_collection_id
                )
            )
            assert deletion is not None and deletion.status == "complete"
            assert (
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.action == "collection.deleted",
                        AuditEvent.target_id == removed_collection_id,
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        await cleanup(tenant_id, user_id)
        await cleanup(other_tenant_id, other_user_id)


async def test_disabled_membership_is_rejected() -> None:
    tenant_id, user_id, _ = await seed_identity(MembershipRole.ADMIN)
    async with session_factory() as session, session.begin():
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == user_id,
            )
        )
        assert membership is not None
        membership.enabled = False
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        None, user_id
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/collections", params={"tenant_id": tenant_id})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        await cleanup(tenant_id, user_id)


async def test_bootstrap_is_idempotent_and_does_not_create_tenant() -> None:
    tenant_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(Organization(id=tenant_id, name="Bootstrap", slug=f"b-{tenant_id}"))
    try:
        first = await bind_identity(
            "https://issuer.bootstrap.test",
            "stable-subject",
            tenant_id,
            MembershipRole.MEMBER,
        )
        second = await bind_identity(
            "https://issuer.bootstrap.test",
            "stable-subject",
            tenant_id,
            MembershipRole.MEMBER,
        )
        assert first == second
        with pytest.raises(ValueError):
            await bind_identity(
                "https://issuer.bootstrap.test",
                "other-subject",
                uuid4(),
                MembershipRole.ADMIN,
            )
    finally:
        async with session_factory() as session, session.begin():
            users = (
                await session.scalars(
                    select(User).where(User.issuer == "https://issuer.bootstrap.test")
                )
            ).all()
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )
            for user in users:
                await session.delete(user)


async def test_issuer_subject_pair_is_unique_but_subject_is_provider_scoped() -> None:
    subject = f"shared-{uuid4()}"
    first_id, second_id = uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                User(id=first_id, issuer="https://issuer-a.test", subject=subject),
                User(id=second_id, issuer="https://issuer-b.test", subject=subject),
            ]
        )
    try:
        async with session_factory() as session:
            session.add(User(issuer="https://issuer-a.test", subject=subject))
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(User).where(User.id.in_([first_id, second_id]))
            )


async def test_verified_issuer_subject_maps_to_enabled_internal_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id, _ = await seed_identity(MembershipRole.MEMBER)
    selected_subject = {"value": str(user_id)}

    class FakeVerifier:
        async def verify(self, token: str) -> ExternalIdentity:
            assert token == "opaque-test-token"
            return ExternalIdentity(
                "https://issuer.integration.test", selected_subject["value"]
            )

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_issuer="https://issuer.integration.test",
        auth_audience="rag-api",
        auth_jwks_url="https://issuer.integration.test/jwks",
    )
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.auth.get_access_token_verifier", lambda: FakeVerifier())
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            accepted = await client.get(
                "/auth/me", headers={"Authorization": "Bearer opaque-test-token"}
            )
            selected_subject["value"] = "unknown-subject"
            unknown = await client.get(
                "/auth/me", headers={"Authorization": "Bearer opaque-test-token"}
            )
            selected_subject["value"] = str(user_id)
            async with session_factory() as session, session.begin():
                user = await session.get(User, user_id)
                assert user is not None
                user.enabled = False
            disabled = await client.get(
                "/auth/me", headers={"Authorization": "Bearer opaque-test-token"}
            )
        assert accepted.status_code == 200
        assert accepted.json()["principal_id"] == str(user_id)
        assert unknown.status_code == 401
        assert disabled.status_code == 401
        assert disabled.headers["www-authenticate"].startswith("Bearer")
    finally:
        await cleanup(tenant_id, user_id)

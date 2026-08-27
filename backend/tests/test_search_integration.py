import hashlib
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete

from app.api.search import get_embedding_provider
from app.auth import TrustedPrincipal, get_trusted_principal
from app.db.models import (
    Collection,
    DocumentChunk,
    DocumentSourceUnit,
    Membership,
    Organization,
    User,
)
from app.db.session import session_factory
from app.embeddings import EMBEDDING_INPUT_VERSION, embedding_fingerprint
from app.main import app
from tests.fixture_builders import add_active_lifecycle

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


class FakeQueryProvider:
    async def embed_query(self, _: str) -> list[float]:
        return [1.0] + [0.0] * 1535

    async def embed_documents(self, texts: object) -> list[list[float]]:
        raise AssertionError("search must not embed documents")


async def seed_search() -> tuple[TrustedPrincipal, UUID, UUID, UUID]:
    tenant_id, other_tenant_id, user_id = uuid4(), uuid4(), uuid4()
    collection_id, other_collection_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Organization(id=tenant_id, name="Search Tenant", slug=str(tenant_id)),
                Organization(
                    id=other_tenant_id,
                    name="Other Search Tenant",
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
        session.add(Membership(tenant_id=tenant_id, user_id=user_id))
        session.add_all(
            [
                Collection(id=collection_id, tenant_id=tenant_id, name="Policies"),
                Collection(
                    id=other_collection_id,
                    tenant_id=other_tenant_id,
                    name="Private",
                ),
            ]
        )
        await session.flush()
        for owner, collection, label in (
            (tenant_id, collection_id, "authorized"),
            (other_tenant_id, other_collection_id, "forbidden"),
        ):
            document_id, unit_id = uuid4(), uuid4()
            version_id, generation_id = await add_active_lifecycle(
                session,
                owner,
                collection,
                document_id,
                filename=f"{label}.pdf",
            )
            session.add(
                DocumentSourceUnit(
                    id=unit_id,
                    tenant_id=owner,
                    document_id=document_id,
                    document_version_id=version_id,
                    generation_id=generation_id,
                    unit_index=0,
                    source_type="pdf",
                    page_number=1,
                    normalized_text=label,
                    content_hash=hashlib.sha256(label.encode()).hexdigest(),
                )
            )
            await session.flush()
            content_hash = hashlib.sha256(label.encode()).hexdigest()
            session.add(
                DocumentChunk(
                    tenant_id=owner,
                    document_id=document_id,
                    document_version_id=version_id,
                    generation_id=generation_id,
                    source_unit_id=unit_id,
                    chunk_index=0,
                    content=label,
                    content_hash=content_hash,
                    pipeline_fingerprint="2" * 64,
                    page_number=1,
                    start_offset=0,
                    end_offset=len(label),
                    embedding=[1.0] + [0.0] * 1535,
                    embedding_model="text-embedding-3-small",
                    embedding_dimensions=1536,
                    embedding_input_version=EMBEDDING_INPUT_VERSION,
                    embedding_fingerprint=embedding_fingerprint(
                        content_hash, "text-embedding-3-small", 1536
                    ),
                    embedded_at=now,
                )
            )
    return TrustedPrincipal(tenant_id, user_id), collection_id, other_tenant_id, user_id


async def test_semantic_search_ranks_and_isolates_tenants() -> None:
    principal, collection_id, other_tenant_id, user_id = await seed_search()

    async def principal_override() -> TrustedPrincipal:
        return principal

    app.dependency_overrides[get_trusted_principal] = principal_override
    app.dependency_overrides[get_embedding_provider] = lambda: FakeQueryProvider()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/collections/{collection_id}/semantic-search",
                json={"query": "similar wording", "top_k": 10},
            )
            assert response.status_code == 200
            results = response.json()["results"]
            assert [item["rank"] for item in results] == [1]
            assert results[0]["document_name"] == "authorized.pdf"
            assert results[0]["similarity_score"] == pytest.approx(1.0)
            assert "forbidden" not in str(results)
            invalid = await client.post(
                f"/collections/{collection_id}/semantic-search",
                json={"query": "   ", "top_k": 51},
            )
            assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(
                    Organization.id.in_([principal.tenant_id, other_tenant_id])
                )
            )
            await session.execute(delete(User).where(User.id == user_id))

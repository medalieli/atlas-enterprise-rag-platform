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
    Document,
    DocumentChunk,
    DocumentSourceUnit,
    DocumentStatus,
    Membership,
    Organization,
    User,
)
from app.db.session import session_factory
from app.embeddings import (
    EMBEDDING_INPUT_VERSION,
    TransientEmbeddingError,
    embedding_fingerprint,
)
from app.main import app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


class CountingQueryProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_query(self, _: str) -> list[float]:
        self.calls += 1
        return [1.0] + [0.0] * 1535

    async def embed_documents(self, texts: object) -> list[list[float]]:
        raise AssertionError("retrieval must not embed documents")


class FailingQueryProvider(CountingQueryProvider):
    async def embed_query(self, _: str) -> list[float]:
        self.calls += 1
        raise TransientEmbeddingError("synthetic provider outage")


async def _add_chunk(
    tenant_id: UUID,
    collection_id: UUID,
    label: str,
    content: str,
    section: str,
    vector: list[float],
) -> UUID:
    document_id, unit_id = uuid4(), uuid4()
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    async with session_factory() as session, session.begin():
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                filename=f"{label}.pdf",
                storage_key=f"{tenant_id}/{document_id}.pdf",
                content_type="application/pdf",
                size_bytes=len(content),
                checksum_sha256=hashlib.sha256(label.encode()).hexdigest(),
                status=DocumentStatus.AVAILABLE,
            )
        )
        await session.flush()
        session.add(
            DocumentSourceUnit(
                id=unit_id,
                tenant_id=tenant_id,
                document_id=document_id,
                unit_index=0,
                source_type="pdf",
                page_number=1,
                normalized_text=content,
                content_hash=content_hash,
            )
        )
        await session.flush()
        session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                source_unit_id=unit_id,
                chunk_index=0,
                content=content,
                content_hash=content_hash,
                pipeline_fingerprint="3" * 64,
                page_number=1,
                section=section,
                start_offset=0,
                end_offset=len(content),
                embedding=vector,
                embedding_model="text-embedding-3-small",
                embedding_dimensions=1536,
                embedding_input_version=EMBEDDING_INPUT_VERSION,
                embedding_fingerprint=embedding_fingerprint(
                    content_hash, "text-embedding-3-small", 1536
                ),
                embedded_at=datetime.now(UTC),
            )
        )
    return document_id


async def seed_hybrid() -> tuple[TrustedPrincipal, UUID, UUID, UUID, UUID]:
    tenant_id, other_tenant_id, user_id = uuid4(), uuid4(), uuid4()
    collection_id, other_collection_id = uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Organization(id=tenant_id, name="Hybrid Tenant", slug=str(tenant_id)),
                Organization(
                    id=other_tenant_id,
                    name="Other Hybrid Tenant",
                    slug=str(other_tenant_id),
                ),
                User(id=user_id, email=f"{user_id}@example.test"),
            ]
        )
        await session.flush()
        session.add(Membership(tenant_id=tenant_id, user_id=user_id))
        session.add_all(
            [
                Collection(id=collection_id, tenant_id=tenant_id, name="Policies"),
                Collection(
                    id=other_collection_id,
                    tenant_id=tenant_id,
                    name="Other Collection",
                ),
                Collection(
                    id=uuid4(), tenant_id=other_tenant_id, name="Private Policies"
                ),
            ]
        )
    both_id = await _add_chunk(
        tenant_id,
        collection_id,
        "both",
        "ENTREFUND30 Enterprise refund policy gives customers their money back "
        "within 30 days. Café Québec support is available.",
        "Enterprise Refund Policy",
        [1.0] + [0.0] * 1535,
    )
    await _add_chunk(
        tenant_id,
        collection_id,
        "semantic-only",
        "Large corporate clients may recover purchase funds during a "
        "thirty day window.",
        "Customer remedies",
        [0.99, 0.01] + [0.0] * 1534,
    )
    await _add_chunk(
        tenant_id,
        collection_id,
        "identifier-only",
        "ENTREFUND30 equipment appendix and ACME-SLA-42 identifier register.",
        "Exact identifiers",
        [0.0, 1.0] + [0.0] * 1534,
    )
    await _add_chunk(
        tenant_id,
        collection_id,
        "office",
        "Office opening hours are Monday through Friday. "
        "Printer maintenance is monthly.",
        "Office operations",
        [0.0, 1.0] + [0.0] * 1534,
    )
    await _add_chunk(
        tenant_id,
        other_collection_id,
        "wrong-collection",
        "ENTREFUND30 Enterprise refund policy gives customers their money back.",
        "Enterprise Refund Policy",
        [1.0] + [0.0] * 1535,
    )
    async with session_factory() as session:
        private_collection_id = await session.scalar(
            Collection.__table__.select()
            .with_only_columns(Collection.id)
            .where(Collection.tenant_id == other_tenant_id)
        )
    assert private_collection_id is not None
    await _add_chunk(
        other_tenant_id,
        private_collection_id,
        "wrong-tenant",
        "ENTREFUND30 Enterprise refund policy gives customers their money back.",
        "Enterprise Refund Policy",
        [1.0] + [0.0] * 1535,
    )
    return (
        TrustedPrincipal(tenant_id, user_id),
        collection_id,
        other_collection_id,
        other_tenant_id,
        both_id,
    )


async def _cleanup(tenant_id: UUID, other_tenant_id: UUID, user_id: UUID) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(Organization).where(
                Organization.id.in_([tenant_id, other_tenant_id])
            )
        )
        await session.execute(delete(User).where(User.id == user_id))


async def test_keyword_queries_ranking_syntax_unicode_and_isolation() -> None:
    principal, collection_id, _, other_tenant_id, _ = await seed_hybrid()

    async def principal_override() -> TrustedPrincipal:
        return principal

    app.dependency_overrides[get_trusted_principal] = principal_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            exact = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "ENTREFUND30", "top_k": 10},
            )
            assert exact.status_code == 200
            names = [item["document_name"] for item in exact.json()["results"]]
            assert set(names) == {"identifier-only.pdf", "both.pdf"}
            assert "wrong-tenant.pdf" not in names
            assert "wrong-collection.pdf" not in names
            repeated = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "ENTREFUND30", "top_k": 10},
            )
            assert repeated.json() == exact.json()

            phrase = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": '"Enterprise refund policy"', "top_k": 5},
            )
            assert [item["document_name"] for item in phrase.json()["results"]] == [
                "both.pdf"
            ]
            syntax = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "ENTREFUND30 OR ACME-SLA-42", "top_k": 5},
            )
            assert len(syntax.json()["results"]) == 2
            negated = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "ENTREFUND30 -equipment", "top_k": 5},
            )
            assert [item["document_name"] for item in negated.json()["results"]] == [
                "both.pdf"
            ]
            unicode_result = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "Café Québec", "top_k": 5},
            )
            assert unicode_result.json()["results"][0]["document_name"] == "both.pdf"
            punctuation = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "!!! ---", "top_k": 5},
            )
            assert punctuation.json() == {"results": []}
            no_match = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "NO-SUCH-ENTERPRISE-ID", "top_k": 5},
            )
            assert no_match.json() == {"results": []}
            blank = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "   ", "top_k": 5},
            )
            assert blank.status_code == 422
            too_long = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "x" * 8001, "top_k": 5},
            )
            assert too_long.status_code == 422
            invalid_top_k = await client.post(
                f"/collections/{collection_id}/keyword-search",
                json={"query": "ENTREFUND30", "top_k": 51},
            )
            assert invalid_top_k.status_code == 422
    finally:
        app.dependency_overrides.clear()
        await _cleanup(principal.tenant_id, other_tenant_id, principal.user_id)


async def test_hybrid_fuses_once_and_preserves_scope_and_semantic_endpoint() -> None:
    principal, collection_id, _, other_tenant_id, both_id = await seed_hybrid()
    provider = CountingQueryProvider()

    async def principal_override() -> TrustedPrincipal:
        return principal

    app.dependency_overrides[get_trusted_principal] = principal_override
    app.dependency_overrides[get_embedding_provider] = lambda: provider
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            hybrid = await client.post(
                f"/collections/{collection_id}/hybrid-search",
                json={"query": "ENTREFUND30 money back", "top_k": 5},
            )
            assert hybrid.status_code == 200
            results = hybrid.json()["results"]
            assert results[0]["document_id"] == str(both_id)
            assert results[0]["matched_channels"] == ["semantic", "keyword"]
            assert results[0]["semantic_rank"] == 1
            assert results[0]["keyword_rank"] == 1
            assert len({item["chunk_id"] for item in results}) == len(results)
            assert not any("wrong-" in item["document_name"] for item in results)
            assert provider.calls == 1

            semantic = await client.post(
                f"/collections/{collection_id}/semantic-search",
                json={"query": "large clients recover purchase funds", "top_k": 2},
            )
            assert semantic.status_code == 200
            assert semantic.json()["results"][0]["document_name"] == "both.pdf"
            assert provider.calls == 2
    finally:
        app.dependency_overrides.clear()
        await _cleanup(principal.tenant_id, other_tenant_id, principal.user_id)


async def test_hybrid_provider_failure_is_safe_and_does_not_downgrade() -> None:
    principal, collection_id, _, other_tenant_id, _ = await seed_hybrid()
    provider = FailingQueryProvider()

    async def principal_override() -> TrustedPrincipal:
        return principal

    app.dependency_overrides[get_trusted_principal] = principal_override
    app.dependency_overrides[get_embedding_provider] = lambda: provider
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/collections/{collection_id}/hybrid-search",
                json={"query": "ENTREFUND30", "top_k": 5},
            )
            assert response.status_code == 503
            assert response.json() == {"detail": "Embedding provider unavailable"}
            assert provider.calls == 1
    finally:
        app.dependency_overrides.clear()
        await _cleanup(principal.tenant_id, other_tenant_id, principal.user_id)

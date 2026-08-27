import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from app.api.answers import get_answer_generator_dependency
from app.api.conversations import get_rewriter_dependency
from app.api.search import get_embedding_provider, get_reranker_dependency
from app.auth import TrustedPrincipal, get_trusted_principal
from app.db.models import Collection, Membership, Organization, User
from app.db.session import session_factory
from app.main import app
from app.rewriting import RewriteOutput, RewriteResult

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 with the migrated Compose database",
    ),
]


class FakeEmbedding:
    calls = 0

    async def embed_query(self, _: str) -> list[float]:
        self.calls += 1
        return [0.01] * 1536


class ClarifyingRewriter:
    calls = 0

    async def rewrite(self, _question: str, history: tuple) -> RewriteResult:
        self.calls += 1
        return RewriteResult(
            output=RewriteOutput(
                status="clarification_required",
                clarification_question="Which synthetic policy do you mean?",
                used_history_message_ids=[str(history[-1].id)],
            ),
            configured_model="fake-luna",
            actual_model="fake-luna",
            input_tokens=10,
            output_tokens=5,
        )


async def test_owned_conversation_first_turn_and_idempotency() -> None:
    tenant_id, user_id, collection_id = uuid4(), uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Organization(
                id=tenant_id, name="Conversation tenant", slug=f"c-{tenant_id}"
            )
        )
        session.add(
            User(id=user_id, issuer="https://issuer.test", subject=str(user_id))
        )
        await session.flush()
        session.add(Membership(tenant_id=tenant_id, user_id=user_id))
        session.add(
            Collection(id=collection_id, tenant_id=tenant_id, name="Conversation docs")
        )
    embedding = FakeEmbedding()
    app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
        None, user_id
    )
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_reranker_dependency] = lambda: object()
    app.dependency_overrides[get_answer_generator_dependency] = lambda: None
    app.dependency_overrides[get_rewriter_dependency] = lambda: None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(f"/collections/{collection_id}/conversations")
            conversation_id = created.json()["id"]
            path = (
                f"/collections/{collection_id}/conversations/{conversation_id}/messages"
            )
            first = await client.post(
                path,
                headers={"Idempotency-Key": "first"},
                json={"query": "A bounded synthetic question?", "top_k": 3},
            )
            repeated = await client.post(
                path,
                headers={"Idempotency-Key": "first"},
                json={"query": "A bounded synthetic question?", "top_k": 3},
            )
            conflict = await client.post(
                path,
                headers={"Idempotency-Key": "first"},
                json={"query": "Different payload?", "top_k": 3},
            )
            clarifier = ClarifyingRewriter()
            app.dependency_overrides[get_rewriter_dependency] = lambda: clarifier
            clarification = await client.post(
                path,
                headers={"Idempotency-Key": "second"},
                json={"query": "Does that still apply?", "top_k": 3},
            )
            messages = await client.get(path)
        assert created.status_code == 201
        assert first.status_code == 200, first.text
        assert first.json()["rewriting_applied"] is False
        assert first.json()["answer"]["status"] == "insufficient_context"
        assert repeated.json() == first.json()
        assert conflict.status_code == 409
        assert clarification.status_code == 200
        assert clarification.json()["clarification_question"]
        assert clarification.json()["answer"] is None
        assert clarifier.calls == 1
        assert embedding.calls == 1
        assert [item["role"] for item in messages.json()["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )
            await session.execute(delete(User).where(User.id == user_id))

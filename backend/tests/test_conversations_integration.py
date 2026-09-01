import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.api.answers import get_answer_generator_dependency
from app.api.conversations import get_rewriter_dependency
from app.api.search import get_embedding_provider, get_reranker_dependency
from app.auth import TrustedPrincipal, get_trusted_principal
from app.db.models import (
    AuditEvent,
    Collection,
    Conversation,
    Membership,
    Organization,
    User,
)
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
    tenant_id, user_id, other_user_id, collection_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with session_factory() as session, session.begin():
        session.add(
            Organization(
                id=tenant_id, name="Conversation tenant", slug=f"c-{tenant_id}"
            )
        )
        session.add(
            User(id=user_id, issuer="https://issuer.test", subject=str(user_id))
        )
        session.add(
            User(
                id=other_user_id,
                issuer="https://issuer.test",
                subject=str(other_user_id),
            )
        )
        await session.flush()
        session.add(Membership(tenant_id=tenant_id, user_id=user_id, role="owner"))
        session.add(
            Membership(tenant_id=tenant_id, user_id=other_user_id, role="owner")
        )
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
            retained = await client.post(f"/collections/{collection_id}/conversations")
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
            workspace_action = await client.post(
                path,
                headers={"Idempotency-Key": "third"},
                json={
                    "query": "create a new temporary collection called test1",
                    "top_k": 3,
                },
            )
            messages = await client.get(path)
            removed = await client.delete(
                f"/collections/{collection_id}/conversations/{conversation_id}"
            )
            replay = await client.delete(
                f"/collections/{collection_id}/conversations/{conversation_id}"
            )
            missing = await client.get(path)
            app.dependency_overrides[get_trusted_principal] = lambda: TrustedPrincipal(
                None, other_user_id
            )
            denied = await client.delete(
                f"/collections/{collection_id}/conversations/{conversation_id}"
            )
        assert created.status_code == 201
        assert first.status_code == 200, first.text
        assert first.json()["rewriting_applied"] is False
        assert first.json()["answer"] is None
        assert first.json()["deterministic_reason"] == "empty_collection"
        assert repeated.json() == first.json()
        assert conflict.status_code == 409
        assert clarification.status_code == 200
        assert clarification.json()["deterministic_reason"] == "empty_collection"
        assert clarification.json()["answer"] is None
        assert workspace_action.status_code == 200
        assert workspace_action.json()["deterministic_reason"] == "workspace_action"
        assert workspace_action.json()["answer"] is None
        assert "No collection was changed" in workspace_action.json()[
            "deterministic_message"
        ]
        assert clarifier.calls == 0
        assert embedding.calls == 0
        assert [item["role"] for item in messages.json()["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert removed.status_code == 204
        assert replay.status_code == 204
        assert denied.status_code == 404
        assert missing.status_code == 404
        async with session_factory() as session:
            assert await session.get(Conversation, retained.json()["id"]) is not None
            assert (
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.action == "conversation.deleted",
                        AuditEvent.target_id == conversation_id,
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(Organization).where(Organization.id == tenant_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.execute(delete(User).where(User.id == other_user_id))

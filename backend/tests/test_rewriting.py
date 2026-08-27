from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.rewriting import (
    HistoryMessage,
    RewriteOutput,
    RewriteStatus,
    bounded_history,
)


def test_rewrite_schema_accepts_grounded_rewrite() -> None:
    message_id = uuid4()
    output = RewriteOutput(
        status="rewritten",
        standalone_query="Does the enterprise refund policy apply to contractors?",
        used_history_message_ids=[str(message_id)],
    )
    assert output.status == RewriteStatus.REWRITTEN


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "rewritten", "standalone_query": None},
        {"status": "clarification_required", "standalone_query": "not allowed"},
        {"status": "standalone", "standalone_query": "   "},
        {"status": "standalone", "standalone_query": "valid", "extra": True},
    ],
)
def test_rewrite_schema_rejects_invalid_combinations(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RewriteOutput.model_validate(payload)


def test_bounded_history_is_deterministic_and_drops_oldest() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        conversation_history_max_messages=2,
        conversation_history_max_tokens=128,
        conversation_history_max_chars=1024,
    )
    messages = [
        HistoryMessage(uuid4(), "user", f"message {number}") for number in range(3)
    ]
    first = bounded_history(messages, settings)
    second = bounded_history(messages, settings)
    assert first == second
    assert first == tuple(messages[-2:])


def test_bounded_history_preserves_complete_messages() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        conversation_history_max_messages=12,
        conversation_history_max_tokens=128,
        conversation_history_max_chars=1024,
    )
    recent = HistoryMessage(uuid4(), "assistant", "short")
    old = HistoryMessage(uuid4(), "user", "word " * 1_000)
    assert bounded_history([old, recent], settings) == (recent,)

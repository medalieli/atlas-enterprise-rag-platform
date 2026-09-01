from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.rewriting import (
    HistoryMessage,
    RewriteOutput,
    RewriteStatus,
    bounded_history,
    deterministic_identifier_follow_up,
)


def test_rewriter_prompt_prefers_searchable_topics_and_resolves_confirmations() -> None:
    from app.rewriting import REWRITER_INSTRUCTIONS

    assert "named topic is searchable" in REWRITER_INSTRUCTIONS
    assert "short confirmations" in REWRITER_INSTRUCTIONS


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


def test_deterministic_identifier_follow_up_resolves_clear_pronoun() -> None:
    source = HistoryMessage(uuid4(), "user", "What does SEC-004 require?")
    assistant = HistoryMessage(uuid4(), "assistant", "A grounded answer.")
    output = deterministic_identifier_follow_up(
        "How often is it reviewed?", (source, assistant)
    )
    assert output is not None
    assert output.status == RewriteStatus.REWRITTEN
    assert output.standalone_query == "Regarding SEC-004: How often is it reviewed?"
    assert output.used_history_message_ids == [str(source.id)]


def test_deterministic_identifier_follow_up_leaves_ambiguous_turn_for_model() -> None:
    history = (
        HistoryMessage(uuid4(), "user", "Compare SEC-004 and RSK-014."),
    )
    assert (
        deterministic_identifier_follow_up("How often are they reviewed?", history)
        is None
    )

import pytest

from app.assistant_intents import deterministic_intent, deterministic_message


@pytest.mark.parametrize(
    "message, expected",
    [
        ("hi", "greeting"),
        (" Hello! ", "greeting"),
        ("bonjour", "greeting"),
        ("Salut...", "greeting"),
        ("salam", "greeting"),
        ("مرحبا", "greeting"),
        ("السلام عليكم!", "greeting"),
        ("help", "help"),
        ("aide", "help"),
        ("مساعدة", "help"),
    ],
)
def test_supported_deterministic_intents(message: str, expected: str) -> None:
    assert deterministic_intent(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "hello, what is our refund policy?",
        "bonjour quelle est notre politique?",
        "مرحبا ما هي سياسة الشركة؟",
        "help me find the leave policy",
        "",
    ],
)
def test_real_questions_are_not_classified_as_intents(message: str) -> None:
    assert deterministic_intent(message) is None


def test_deterministic_messages_make_no_factual_claim_or_citation() -> None:
    assert "authorized" in deterministic_message("greeting")
    assert "no ready documents" in deterministic_message("empty_collection")

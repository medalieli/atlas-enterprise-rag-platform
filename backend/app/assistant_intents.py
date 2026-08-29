import re
import unicodedata

_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "bonjour",
    "salut",
    "salam",
    "مرحبا",
    "السلام عليكم",
}
_HELP = {"help", "aide", "مساعدة"}


def deterministic_intent(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[\s]+", " ", normalized)
    normalized = re.sub(r"[.!?,;:،؟]+$", "", normalized).strip()
    if normalized in _GREETINGS:
        return "greeting"
    if normalized in _HELP:
        return "help"
    return None


def deterministic_message(reason: str) -> str:
    if reason == "empty_collection":
        return (
            "This collection has no ready documents yet. Upload an authorized "
            "company document, or ask a collection manager for help."
        )
    return (
        "Hi! I'm Atlas. I answer questions using documents you are authorized "
        "to access. Select a collection or upload documents, then ask about your "
        "company knowledge."
    )

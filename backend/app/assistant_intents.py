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


_COLLECTION_ACTION = re.compile(
    r"^(?:(?:please|kindly)\s+|(?:can|could|would)\s+you\s+|"
    r"i\s+(?:want|need)\s+you\s+to\s+)?"
    r"(?:create|add|make|delete|remove)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:new\s+|temporary\s+|temp\s+)*collection\b"
)


def deterministic_intent(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[\s]+", " ", normalized)
    normalized = re.sub(r"[.!?,;:،؟]+$", "", normalized).strip()
    if normalized in _GREETINGS:
        return "greeting"
    if normalized in _HELP:
        return "help"
    if _COLLECTION_ACTION.search(normalized):
        return "workspace_action"
    return None


def deterministic_message(reason: str) -> str:
    if reason == "empty_collection":
        return (
            "This collection has no ready documents yet. Upload an authorized "
            "company document, or ask a collection manager for help."
        )
    if reason == "workspace_action":
        return (
            "Chat answers questions from the selected collection and cannot change "
            "workspace data. Use the New collection or Delete collection control in "
            "the collection sidebar; Atlas will apply your current role's real "
            "permissions and confirmation requirements there. No collection was "
            "changed."
        )
    return (
        "Hi! I'm Atlas. I answer questions using documents you are authorized "
        "to access. Select a collection or upload documents, then ask about your "
        "company knowledge."
    )

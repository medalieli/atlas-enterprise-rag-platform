import hashlib
import json
from dataclasses import dataclass

from app.core.config import Settings
from app.embeddings import EMBEDDING_INPUT_VERSION
from app.ingestion.chunking import CHUNKER_VERSION
from app.ingestion.cleaning import CLEANER_VERSION
from app.retrieval import TEXT_SEARCH_CONFIGURATION


@dataclass(frozen=True)
class IndexConfiguration:
    parser_version: str
    cleaner_version: str
    chunker_version: str
    embedding_input_version: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    text_search_configuration: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.__dict__, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def index_configuration(content_type: str, settings: Settings) -> IndexConfiguration:
    parser = "pypdf-6-v1" if content_type == "application/pdf" else "python-docx-1-v1"
    return IndexConfiguration(
        parser_version=parser,
        cleaner_version=CLEANER_VERSION,
        chunker_version=CHUNKER_VERSION,
        embedding_input_version=EMBEDDING_INPUT_VERSION,
        embedding_provider=getattr(settings, "embedding_provider", "openai"),
        embedding_model=getattr(settings, "embedding_model", "text-embedding-3-small"),
        embedding_dimensions=getattr(settings, "embedding_dimensions", 1536),
        text_search_configuration=TEXT_SEARCH_CONFIGURATION,
    )


DOCUMENT_TRANSITIONS = {
    "pending": frozenset({"processing", "available", "failed", "deleting"}),
    "processing": frozenset({"available", "failed", "deleting"}),
    "available": frozenset({"deleting"}),
    "failed": frozenset({"deleting"}),
    "deleting": frozenset({"deleted"}),
    "deleted": frozenset(),
}

VERSION_TRANSITIONS = {
    "pending": frozenset({"processing", "failed"}),
    "processing": frozenset({"ready", "failed"}),
    "ready": frozenset({"active", "failed"}),
    "active": frozenset({"superseded"}),
    "superseded": frozenset({"active"}),
    "failed": frozenset(),
}

GENERATION_TRANSITIONS = VERSION_TRANSITIONS

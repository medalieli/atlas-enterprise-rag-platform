from types import SimpleNamespace
from uuid import uuid4

from app.lifecycle import (
    DOCUMENT_TRANSITIONS,
    GENERATION_TRANSITIONS,
    VERSION_TRANSITIONS,
    index_configuration,
)
from app.storage import version_storage_key


def test_configuration_fingerprint_is_deterministic_and_versioned() -> None:
    settings = SimpleNamespace(
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )
    first = index_configuration("application/pdf", settings)
    second = index_configuration("application/pdf", settings)
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    assert first.parser_version == "pypdf-6-v1"
    assert first.text_search_configuration == "simple"


def test_state_machines_make_deletion_terminal() -> None:
    assert "deleted" in DOCUMENT_TRANSITIONS["deleting"]
    assert DOCUMENT_TRANSITIONS["deleted"] == frozenset()
    assert "active" in VERSION_TRANSITIONS["ready"]
    assert "active" in GENERATION_TRANSITIONS["ready"]
    assert "processing" not in VERSION_TRANSITIONS["superseded"]


def test_version_storage_keys_isolate_every_snapshot() -> None:
    tenant_id, document_id, first, second = (uuid4() for _ in range(4))
    first_key = version_storage_key(tenant_id, document_id, first, ".pdf")
    second_key = version_storage_key(tenant_id, document_id, second, ".pdf")
    assert first_key != second_key
    assert first.hex in first_key
    assert second.hex not in first_key


from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.metadata import DocumentMetadataInput, MetadataFilter


def test_metadata_normalizes_and_deduplicates() -> None:
    value = DocumentMetadataInput.model_validate(
        {
            "tags": [" Finance ", "finance", "ENTREFUND30"],
            "department": " Legal ",
            "document_type": "policy",
            "language": "FR-ca",
            "effective_date": "2026-01-02",
        }
    )
    assert value.to_storage() == {
        "tags": ["finance", "entrefund30"],
        "department": "legal",
        "document_type": "policy",
        "language": "fr-ca",
        "effective_date": "2026-01-02",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"tenant_id": str(uuid4())},
        {"collection_id": str(uuid4())},
        {"tags": {"nested": "unsafe"}},
        {"effective_date": "not-a-date"},
        {"tags": ["x"] * 21},
    ],
)
def test_metadata_rejects_unknown_unsafe_or_invalid_values(payload: object) -> None:
    with pytest.raises(ValidationError):
        DocumentMetadataInput.model_validate(payload)


def test_filter_contract_normalizes_empty_lists_and_validates_ranges() -> None:
    document_id = uuid4()
    value = MetadataFilter.model_validate(
        {
            "document_ids": [str(document_id), str(document_id)],
            "tags_any": [" HR ", "hr"],
            "tags_all": [],
            "departments": ["Legal", "legal"],
        }
    )
    assert value.document_ids == [document_id]
    assert value.tags_any == ["hr"]
    assert value.tags_all is None
    assert value.departments == ["legal"]

    with pytest.raises(ValidationError):
        MetadataFilter(
            created_from=datetime(2026, 2, 1, tzinfo=UTC),
            created_to=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        MetadataFilter(
            effective_from=date(2026, 2, 1),
            effective_to=date(2026, 1, 1),
        )


def test_filter_rejects_unknown_fields_and_malicious_structures() -> None:
    for payload in (
        {"tenant_id": str(uuid4())},
        {"json_path": "$.tags[*] ? (@ like_regex '.*')"},
        {"tags_any": [{"$sql": "drop table documents"}]},
    ):
        with pytest.raises(ValidationError):
            MetadataFilter.model_validate(payload)

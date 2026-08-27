import json
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from sqlalchemy import ColumnElement
from sqlalchemy.dialects import postgresql

from app.db.models import Document

MAX_METADATA_JSON_BYTES = 4096
MAX_FILTER_JSON_BYTES = 8192
MAX_TAGS = 20
MAX_FILTER_VALUES = 50

TagValue = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
MetadataValue = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
FilenameValue = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
ContentTypeValue = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class DocumentType(StrEnum):
    POLICY = "policy"
    CONTRACT = "contract"
    FAQ = "faq"
    MANUAL = "manual"
    OTHER = "other"


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.casefold() for value in values))


class DocumentMetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[TagValue] = Field(default_factory=list, max_length=MAX_TAGS)
    department: MetadataValue | None = None
    document_type: DocumentType | None = None
    language: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                to_lower=True,
                min_length=2,
                max_length=16,
                pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$",
            ),
        ]
        | None
    ) = None
    effective_date: date | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return _deduplicate(value)

    @field_validator("department")
    @classmethod
    def normalize_department(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: object) -> object:
        return value.casefold() if isinstance(value, str) else value

    @model_validator(mode="after")
    def bound_serialized_size(self) -> "DocumentMetadataInput":
        payload = self.model_dump(mode="json", exclude_none=True)
        size = len(json.dumps(payload, separators=(",", ":")).encode())
        if size > MAX_METADATA_JSON_BYTES:
            raise ValueError("metadata is too large")
        return self

    def to_storage(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class MetadataFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] | None = Field(default=None, max_length=MAX_FILTER_VALUES)
    content_types: list[ContentTypeValue] | None = Field(
        default=None, max_length=MAX_FILTER_VALUES
    )
    filenames: list[FilenameValue] | None = Field(
        default=None, max_length=MAX_FILTER_VALUES
    )
    created_from: datetime | None = None
    created_to: datetime | None = None
    tags_any: list[TagValue] | None = Field(default=None, max_length=MAX_TAGS)
    tags_all: list[TagValue] | None = Field(default=None, max_length=MAX_TAGS)
    departments: list[MetadataValue] | None = Field(
        default=None, max_length=MAX_FILTER_VALUES
    )
    document_types: list[DocumentType] | None = Field(
        default=None, max_length=len(DocumentType)
    )
    languages: list[MetadataValue] | None = Field(
        default=None, max_length=MAX_FILTER_VALUES
    )
    effective_from: date | None = None
    effective_to: date | None = None

    @field_validator(
        "content_types", "tags_any", "tags_all", "departments", "languages"
    )
    @classmethod
    def normalize_string_lists(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return _deduplicate(value)

    @field_validator("filenames")
    @classmethod
    def deduplicate_filenames(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return list(dict.fromkeys(value))

    @field_validator("document_ids", "document_types")
    @classmethod
    def deduplicate_typed_lists(cls, value: list[object] | None) -> list[object] | None:
        if not value:
            return None
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_ranges_and_size(self) -> "MetadataFilter":
        if (
            self.created_from
            and self.created_to
            and self.created_from > self.created_to
        ):
            raise ValueError("created_from must not be after created_to")
        if (
            self.effective_from
            and self.effective_to
            and self.effective_from > self.effective_to
        ):
            raise ValueError("effective_from must not be after effective_to")
        payload = self.model_dump(mode="json", exclude_none=True)
        size = len(json.dumps(payload, separators=(",", ":")).encode())
        if size > MAX_FILTER_JSON_BYTES:
            raise ValueError("filters are too large")
        return self


class PublicDocumentMetadata(BaseModel):
    tags: list[str] = Field(default_factory=list)
    department: str | None = None
    document_type: DocumentType | None = None
    language: str | None = None
    effective_date: date | None = None


def public_document_metadata(
    value: dict[str, object] | None,
) -> PublicDocumentMetadata:
    value = value or {}
    allowed = {
        key: value[key]
        for key in ("tags", "department", "document_type", "language", "effective_date")
        if key in value
    }
    return PublicDocumentMetadata.model_validate(allowed)


def document_filter_predicates(
    filters: MetadataFilter | None,
) -> tuple[ColumnElement[bool], ...]:
    if filters is None:
        return ()
    predicates: list[ColumnElement[bool]] = []
    if filters.document_ids:
        predicates.append(Document.id.in_(filters.document_ids))
    if filters.content_types:
        predicates.append(Document.content_type.in_(filters.content_types))
    if filters.filenames:
        predicates.append(Document.filename.in_(filters.filenames))
    if filters.created_from:
        predicates.append(Document.created_at >= filters.created_from)
    if filters.created_to:
        predicates.append(Document.created_at <= filters.created_to)
    if filters.tags_any:
        predicates.append(
            Document.document_metadata["tags"].op("?|")(
                postgresql.array(filters.tags_any)
            )
        )
    if filters.tags_all:
        predicates.append(
            Document.document_metadata["tags"].op("?&")(
                postgresql.array(filters.tags_all)
            )
        )
    if filters.departments:
        predicates.append(
            Document.document_metadata["department"]
            .as_string()
            .in_(filters.departments)
        )
    if filters.document_types:
        predicates.append(
            Document.document_metadata["document_type"]
            .as_string()
            .in_([value.value for value in filters.document_types])
        )
    if filters.languages:
        predicates.append(
            Document.document_metadata["language"].as_string().in_(filters.languages)
        )
    # Normalized ISO dates sort chronologically as text and keep the matching
    # expression index immutable regardless of the database DateStyle.
    effective_date = Document.document_metadata["effective_date"].as_string()
    if filters.effective_from:
        predicates.append(effective_date >= filters.effective_from.isoformat())
    if filters.effective_to:
        predicates.append(effective_date <= filters.effective_to.isoformat())
    return tuple(predicates)

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MembershipRole(StrEnum):
    VIEWER = "viewer"
    MEMBER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AVAILABLE = "available"
    FAILED = "failed"


class ProcessingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConversationTurnStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ConversationMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
        Index("ix_users_issuer_subject", "issuer", "subject"),
    )

    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        Index("ix_memberships_user_id", "user_id"),
        Index("ix_memberships_tenant_enabled", "tenant_id", "enabled"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole,
            name="membership_role",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=MembershipRole.VIEWER,
        server_default=MembershipRole.VIEWER.value,
    )
    enabled: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_collections_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_collections_tenant_name"),
        Index("ix_collections_tenant_created_at", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            name="fk_documents_tenant_collection",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "storage_key", name="uq_documents_tenant_storage_key"
        ),
        CheckConstraint("size_bytes >= 0", name="ck_documents_size_nonnegative"),
        CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_documents_checksum_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_documents_metadata_object",
        ),
        CheckConstraint(
            "pg_column_size(metadata) <= 8192",
            name="ck_documents_metadata_size",
        ),
        Index("ix_documents_tenant_collection", "tenant_id", "collection_id"),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
        Index(
            "ix_documents_tenant_collection_created_at",
            "tenant_id",
            "collection_id",
            "created_at",
        ),
        Index(
            "ix_documents_tenant_collection_content_type",
            "tenant_id",
            "collection_id",
            "content_type",
        ),
        Index(
            "ix_documents_tenant_collection_filename",
            "tenant_id",
            "collection_id",
            "filename",
        ),
        Index(
            "ix_documents_metadata_tags_gin",
            text("(metadata -> 'tags')"),
            postgresql_using="gin",
        ),
        Index("ix_documents_metadata_department", text("(metadata ->> 'department')")),
        Index(
            "ix_documents_metadata_document_type",
            text("(metadata ->> 'document_type')"),
        ),
        Index("ix_documents_metadata_language", text("(metadata ->> 'language')")),
        Index(
            "ix_documents_metadata_effective_date",
            text("(metadata ->> 'effective_date')"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    collection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=DocumentStatus.PENDING,
        server_default=DocumentStatus.PENDING.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_chunks_tenant_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "source_unit_id"],
            [
                "document_source_units.tenant_id",
                "document_source_units.document_id",
                "document_source_units.id",
            ],
            name="fk_document_chunks_tenant_source_unit",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "chunk_index",
            name="uq_document_chunks_tenant_document_index",
        ),
        CheckConstraint(
            "chunk_index >= 0", name="ck_document_chunks_index_nonnegative"
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_document_chunks_page_positive",
        ),
        CheckConstraint(
            "start_offset IS NULL OR start_offset >= 0",
            name="ck_document_chunks_start_nonnegative",
        ),
        CheckConstraint(
            "end_offset IS NULL OR end_offset >= start_offset",
            name="ck_document_chunks_offset_order",
        ),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL AND "
            "embedding_dimensions IS NULL AND embedding_input_version IS NULL AND "
            "embedding_fingerprint IS NULL AND embedded_at IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL AND "
            "embedding_dimensions = 1536 AND embedding_input_version IS NOT NULL AND "
            "embedding_fingerprint IS NOT NULL AND embedded_at IS NOT NULL)",
            name="ck_document_chunks_embedding_complete",
        ),
        Index("ix_document_chunks_tenant_document", "tenant_id", "document_id"),
        Index(
            "ix_document_chunks_tenant_page", "tenant_id", "document_id", "page_number"
        ),
        Index(
            "ix_document_chunks_tenant_embedding",
            "tenant_id",
            "document_id",
            postgresql_where=text("embedding IS NOT NULL"),
        ),
        Index(
            "ix_document_chunks_embedding_hnsw_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
        Index(
            "ix_document_chunks_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    source_unit_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple'::regconfig, "
            "coalesce(section, '')), 'A') || "
            "setweight(to_tsvector('simple'::regconfig, content), 'B')",
            persisted=True,
        ),
        nullable=False,
    )
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(1536))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding_input_version: Mapped[str | None] = mapped_column(String(50))
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentSourceUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_source_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_source_units_tenant_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "document_id", "id", name="uq_source_units_tenant_document_id"
        ),
        UniqueConstraint(
            "tenant_id", "document_id", "unit_index", name="uq_source_units_index"
        ),
        CheckConstraint("unit_index >= 0", name="ck_source_units_index_nonnegative"),
        Index("ix_source_units_tenant_document", "tenant_id", "document_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(1000))
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class ProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_processing_jobs_tenant_document",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_processing_jobs_attempt_nonnegative"
        ),
        Index("ix_processing_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_processing_jobs_tenant_document", "tenant_id", "document_id"),
        Index("ix_processing_jobs_requested_by", "requested_by_user_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(
            ProcessingJobStatus,
            name="processing_job_status",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=ProcessingJobStatus.QUEUED,
        server_default=ProcessingJobStatus.QUEUED.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "collection_id",
            "id",
            "created_by_user_id",
            name="uq_conversations_owned_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_conversations_tenant_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            name="fk_conversations_tenant_collection",
            ondelete="CASCADE",
        ),
        Index("ix_conversations_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_conversations_tenant_user", "tenant_id", "created_by_user_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    collection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(300))


class ConversationTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "collection_id", "conversation_id", "created_by_user_id"],
            [
                "conversations.tenant_id",
                "conversations.collection_id",
                "conversations.id",
                "conversations.created_by_user_id",
            ],
            name="fk_conversation_turns_owned_conversation",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "conversation_id", "sequence_number", name="uq_conversation_turn_sequence"
        ),
        UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_conversation_turn_idempotency",
        ),
        CheckConstraint("sequence_number >= 1", name="ck_conversation_turn_sequence"),
        CheckConstraint("top_k BETWEEN 1 AND 20", name="ck_conversation_turn_top_k"),
        CheckConstraint(
            "char_length(original_question) BETWEEN 1 AND 8000",
            name="ck_conversation_turn_question_length",
        ),
        Index(
            "ix_conversation_turns_owner",
            "tenant_id",
            "collection_id",
            "created_by_user_id",
        ),
        Index(
            "uq_conversation_turn_one_pending",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    collection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ConversationTurnStatus] = mapped_column(
        Enum(
            ConversationTurnStatus,
            name="conversation_turn_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=ConversationTurnStatus.PENDING,
        server_default=ConversationTurnStatus.PENDING.value,
    )
    original_question: Mapped[str] = mapped_column(Text, nullable=False)
    standalone_question: Mapped[str | None] = mapped_column(Text)
    rewrite_status: Mapped[str | None] = mapped_column(String(32))
    clarification_question: Mapped[str | None] = mapped_column(String(1000))
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    filters: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    response: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    failure_category: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_message_sequence",
        ),
        CheckConstraint(
            "sequence_number >= 1", name="ck_conversation_message_sequence"
        ),
        CheckConstraint(
            "char_length(content) BETWEEN 1 AND 16000",
            name="ck_conversation_message_content",
        ),
        Index("ix_conversation_messages_history", "conversation_id", "sequence_number"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[ConversationMessageRole] = mapped_column(
        Enum(
            ConversationMessageRole,
            name="conversation_message_role",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationCitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_citations"
    __table_args__ = (
        UniqueConstraint(
            "assistant_message_id",
            "citation_order",
            name="uq_conversation_citation_order",
        ),
        CheckConstraint("citation_order >= 1", name="ck_conversation_citation_order"),
        Index("ix_conversation_citations_message", "assistant_message_id"),
    )

    assistant_message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(1000))
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    exact_excerpt: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = [
    "Collection",
    "Conversation",
    "ConversationCitation",
    "ConversationMessage",
    "ConversationMessageRole",
    "ConversationTurn",
    "ConversationTurnStatus",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "DocumentSourceUnit",
    "Membership",
    "MembershipRole",
    "Organization",
    "ProcessingJob",
    "ProcessingJobStatus",
    "User",
]

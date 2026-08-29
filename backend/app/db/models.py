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
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class CollectionRole(StrEnum):
    MANAGER = "manager"
    EDITOR = "editor"
    VIEWER = "viewer"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AVAILABLE = "available"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class DocumentVersionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class IndexGenerationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
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
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        CheckConstraint(
            "status IN ('active','suspended','revoked')",
            name="ck_memberships_status",
        ),
        CheckConstraint("version >= 1", name="ck_memberships_version"),
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
        default=MembershipRole.MEMBER,
        server_default=MembershipRole.MEMBER.value,
    )
    enabled: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        CheckConstraint(
            "status IN ('pending','accepted','expired','revoked','replaced')",
            name="ck_invitations_status",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 10", name="ck_invitations_attempts"
        ),
        Index(
            "ix_invitations_tenant_status_created", "tenant_id", "status", "created_at"
        ),
        Index("ix_invitations_tenant_email", "tenant_id", "email_normalized"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole,
            name="membership_role",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    initial_grants: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class CollectionGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collection_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            name="fk_grants_tenant_collection",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_grants_tenant_membership",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "collection_id",
            "membership_id",
            name="uq_collection_grants_scope",
        ),
        Index(
            "ix_collection_grants_member_collection", "membership_id", "collection_id"
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    collection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    membership_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    role: Mapped[CollectionRole] = mapped_column(
        Enum(
            CollectionRole,
            name="collection_role",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success','denied','failure')", name="ck_audit_outcome"
        ),
        CheckConstraint(
            "pg_column_size(metadata) <= 2048", name="ck_audit_metadata_size"
        ),
        Index("ix_audit_tenant_created_id", "tenant_id", "created_at", "id"),
        Index("ix_audit_tenant_actor", "tenant_id", "actor_user_id", "created_at"),
        Index("ix_audit_tenant_action", "tenant_id", "action", "created_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AnswerFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "answer_feedback"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "assistant_message_id",
            name="uq_feedback_user_answer",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "collection_id", "conversation_id", "user_id"],
            [
                "conversations.tenant_id",
                "conversations.collection_id",
                "conversations.id",
                "conversations.created_by_user_id",
            ],
            name="fk_feedback_owned_conversation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "assistant_message_id"],
            ["conversation_messages.conversation_id", "conversation_messages.id"],
            name="fk_feedback_conversation_message",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "rating IN ('helpful','not_helpful')", name="ck_feedback_rating"
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN "
            "('incorrect','incomplete','irrelevant_sources','citation_problem',"
            "'outdated_source','other')",
            name="ck_feedback_reason",
        ),
        Index("ix_feedback_tenant_created", "tenant_id", "created_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    assistant_message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32))


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
            "tenant_id", "collection_id", "id", name="uq_documents_tenant_collection_id"
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
    active_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
    )
    next_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Deprecated Milestone 3 snapshot fields retained only for downgrade.
    filename: Mapped[str | None] = mapped_column(String(512))
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    content_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column()
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
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
    document_metadata: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "collection_id", "document_id"],
            ["documents.tenant_id", "documents.collection_id", "documents.id"],
            name="fk_document_versions_tenant_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "document_id", "id", name="uq_document_versions_identity"
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "version_number",
            name="uq_document_versions_order",
        ),
        UniqueConstraint(
            "tenant_id", "storage_key", name="uq_document_versions_storage_key"
        ),
        CheckConstraint("version_number >= 1", name="ck_document_versions_order"),
        CheckConstraint("size_bytes >= 0", name="ck_document_versions_size"),
        CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_checksum",
        ),
        Index("ix_document_versions_document", "tenant_id", "document_id"),
        Index("ix_document_versions_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    collection_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[DocumentVersionStatus] = mapped_column(
        Enum(
            DocumentVersionStatus,
            name="document_version_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=DocumentVersionStatus.PENDING,
        server_default=DocumentVersionStatus.PENDING.value,
    )
    active_generation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_index_generations.id", ondelete="RESTRICT"),
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(100))


class DocumentIndexGeneration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_index_generations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "document_version_id"],
            [
                "document_versions.tenant_id",
                "document_versions.document_id",
                "document_versions.id",
            ],
            name="fk_generations_tenant_version",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version_id",
            "id",
            name="uq_generations_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_version_id",
            "generation_number",
            name="uq_generations_order",
        ),
        CheckConstraint("generation_number >= 1", name="ck_generations_order"),
        Index("ix_generations_version", "tenant_id", "document_version_id"),
        Index("ix_generations_status", "tenant_id", "status"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[IndexGenerationStatus] = mapped_column(
        Enum(
            IndexGenerationStatus,
            name="index_generation_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=IndexGenerationStatus.PENDING,
        server_default=IndexGenerationStatus.PENDING.value,
    )
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    cleaner_version: Mapped[str] = mapped_column(String(100), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_input_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    text_search_configuration: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_job_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(100))


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
            ["tenant_id", "document_id", "document_version_id", "generation_id"],
            [
                "document_index_generations.tenant_id",
                "document_index_generations.document_id",
                "document_index_generations.document_version_id",
                "document_index_generations.id",
            ],
            name="fk_chunks_generation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "document_id",
                "document_version_id",
                "generation_id",
                "source_unit_id",
            ],
            [
                "document_source_units.tenant_id",
                "document_source_units.document_id",
                "document_source_units.document_version_id",
                "document_source_units.generation_id",
                "document_source_units.id",
            ],
            name="fk_document_chunks_tenant_source_unit",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "generation_id",
            "chunk_index",
            name="uq_document_chunks_generation_index",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version_id",
            "generation_id",
            "id",
            name="uq_document_chunks_lifecycle_identity",
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
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    generation_id: Mapped[UUID] = mapped_column(
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
            ["tenant_id", "document_id", "document_version_id", "generation_id"],
            [
                "document_index_generations.tenant_id",
                "document_index_generations.document_id",
                "document_index_generations.document_version_id",
                "document_index_generations.id",
            ],
            name="fk_source_units_generation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_source_units_tenant_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version_id",
            "generation_id",
            "id",
            name="uq_source_units_lifecycle_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "generation_id",
            "unit_index",
            name="uq_source_units_generation_index",
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
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    generation_id: Mapped[UUID] = mapped_column(
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
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "document_version_id"],
            [
                "document_versions.tenant_id",
                "document_versions.document_id",
                "document_versions.id",
            ],
            name="fk_processing_jobs_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "document_version_id", "generation_id"],
            [
                "document_index_generations.tenant_id",
                "document_index_generations.document_id",
                "document_index_generations.document_version_id",
                "document_index_generations.id",
            ],
            name="fk_processing_jobs_generation",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "operation",
            "idempotency_key",
            name="uq_processing_jobs_idempotency",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_processing_jobs_attempt_nonnegative"
        ),
        Index("ix_processing_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_processing_jobs_tenant_document", "tenant_id", "document_id"),
        Index("ix_processing_jobs_requested_by", "requested_by_user_id"),
        Index(
            "uq_processing_jobs_active_lifecycle",
            "tenant_id",
            "document_id",
            unique=True,
            postgresql_where=text(
                "operation IN ('replacement_ingestion', 'reindex') "
                "AND status IN ('queued', 'running', 'retrying')"
            ),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True)
    )
    generation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    failure_category: Mapped[str | None] = mapped_column(String(100))
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
        UniqueConstraint(
            "conversation_id", "id", name="uq_conversation_messages_conversation_id"
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
        CheckConstraint(
            "(source_status = 'available' AND tenant_id IS NOT NULL AND "
            "chunk_id IS NOT NULL AND document_id IS NOT NULL AND "
            "document_version_id IS NOT NULL AND generation_id IS NOT NULL AND "
            "exact_excerpt IS NOT NULL) OR (source_status = 'deleted' AND "
            "tenant_id IS NULL AND chunk_id IS NULL AND document_id IS NULL AND "
            "document_version_id IS NULL AND generation_id IS NULL AND "
            "exact_excerpt IS NULL)",
            name="ck_citations_source_state",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "document_id",
                "document_version_id",
                "generation_id",
                "chunk_id",
            ],
            [
                "document_chunks.tenant_id",
                "document_chunks.document_id",
                "document_chunks.document_version_id",
                "document_chunks.generation_id",
                "document_chunks.id",
            ],
            name="fk_citations_chunk_lifecycle",
            ondelete="RESTRICT",
        ),
        Index("ix_conversation_citations_message", "assistant_message_id"),
    )

    assistant_message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="available", server_default="available"
    )
    tenant_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    chunk_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="RESTRICT"),
        nullable=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=True,
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    generation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(1000))
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    exact_excerpt: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "AnswerFeedback",
    "AuditEvent",
    "Collection",
    "CollectionGrant",
    "CollectionRole",
    "Conversation",
    "ConversationCitation",
    "ConversationMessage",
    "ConversationMessageRole",
    "ConversationTurn",
    "ConversationTurnStatus",
    "Document",
    "DocumentChunk",
    "DocumentIndexGeneration",
    "DocumentStatus",
    "DocumentSourceUnit",
    "DocumentVersion",
    "DocumentVersionStatus",
    "IndexGenerationStatus",
    "Invitation",
    "Membership",
    "MembershipRole",
    "Organization",
    "ProcessingJob",
    "ProcessingJobStatus",
    "User",
]

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MembershipRole(StrEnum):
    MEMBER = "member"
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


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        Index("ix_memberships_user_id", "user_id"),
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
        Index("ix_documents_tenant_collection", "tenant_id", "collection_id"),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
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
        Index("ix_document_chunks_tenant_document", "tenant_id", "document_id"),
        Index(
            "ix_document_chunks_tenant_page", "tenant_id", "document_id", "page_number"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
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
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
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


__all__ = [
    "Collection",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "Membership",
    "MembershipRole",
    "Organization",
    "ProcessingJob",
    "ProcessingJobStatus",
    "User",
]

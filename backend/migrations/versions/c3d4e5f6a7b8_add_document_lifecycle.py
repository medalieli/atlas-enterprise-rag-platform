"""add immutable document versions and indexing generations

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'deleting'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'deleted'")
    version_status = postgresql.ENUM(
        "pending",
        "processing",
        "ready",
        "active",
        "superseded",
        "failed",
        name="document_version_status",
        create_type=False,
    )
    generation_status = postgresql.ENUM(
        "pending",
        "processing",
        "ready",
        "active",
        "superseded",
        "failed",
        name="index_generation_status",
        create_type=False,
    )
    version_status.create(op.get_bind(), checkfirst=True)
    generation_status.create(op.get_bind(), checkfirst=True)

    op.create_unique_constraint(
        "uq_documents_tenant_collection_id",
        "documents",
        ["tenant_id", "collection_id", "id"],
    )
    op.add_column("documents", sa.Column("active_version_id", sa.UUID()))
    op.add_column(
        "documents",
        sa.Column(
            "next_version_number", sa.Integer(), server_default="2", nullable=False
        ),
    )
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True)))

    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.UUID()),
        sa.Column("status", version_status, server_default="pending", nullable=False),
        sa.Column("active_generation_id", sa.UUID()),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_category", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("version_number >= 1", name="ck_document_versions_order"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_versions_size"),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_versions_checksum"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id", "document_id"],
            ["documents.tenant_id", "documents.collection_id", "documents.id"],
            name="fk_document_versions_tenant_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id", "document_id", "id", name="uq_document_versions_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "version_number",
            name="uq_document_versions_order",
        ),
        sa.UniqueConstraint(
            "tenant_id", "storage_key", name="uq_document_versions_storage_key"
        ),
    )
    op.create_index(
        "ix_document_versions_document",
        "document_versions",
        ["tenant_id", "document_id"],
    )
    op.create_index(
        "ix_document_versions_status", "document_versions", ["tenant_id", "status"]
    )

    op.create_table(
        "document_index_generations",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("generation_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", generation_status, server_default="pending", nullable=False
        ),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("cleaner_version", sa.String(100), nullable=False),
        sa.Column("chunker_version", sa.String(100), nullable=False),
        sa.Column("embedding_input_version", sa.String(100), nullable=False),
        sa.Column("embedding_provider", sa.String(100), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("text_search_configuration", sa.String(100), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("processing_job_id", sa.UUID()),
        sa.Column("requested_by_user_id", sa.UUID()),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_category", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("generation_number >= 1", name="ck_generations_order"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id", "document_version_id"],
            [
                "document_versions.tenant_id",
                "document_versions.document_id",
                "document_versions.id",
            ],
            name="fk_generations_tenant_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "document_version_id",
            "id",
            name="uq_generations_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_version_id",
            "generation_number",
            name="uq_generations_order",
        ),
    )
    op.create_index(
        "ix_generations_version",
        "document_index_generations",
        ["tenant_id", "document_version_id"],
    )
    op.create_index(
        "ix_generations_status", "document_index_generations", ["tenant_id", "status"]
    )

    # The existing document UUID intentionally becomes the initial version UUID.
    op.execute("""
        INSERT INTO document_versions (
          id, tenant_id, collection_id, document_id, version_number, storage_key,
          checksum_sha256, filename, content_type, size_bytes, metadata, status,
          ready_at, activated_at, failed_at, failure_category, created_at, updated_at
        ) SELECT id, tenant_id, collection_id, id, 1, storage_key,
          checksum_sha256, filename, content_type, size_bytes, metadata,
          CASE status::text WHEN 'available' THEN 'active'::document_version_status
            WHEN 'processing' THEN 'processing'::document_version_status
            WHEN 'failed' THEN 'failed'::document_version_status
            ELSE 'pending'::document_version_status END,
          CASE WHEN status::text = 'available' THEN updated_at END,
          CASE WHEN status::text = 'available' THEN updated_at END,
          CASE WHEN status::text = 'failed' THEN updated_at END,
          CASE WHEN status::text = 'failed' THEN 'legacy_ingestion_failed' END,
          created_at, updated_at FROM documents
    """)
    op.execute("""
        INSERT INTO document_index_generations (
          tenant_id, document_id, document_version_id, generation_number, status,
          parser_version, cleaner_version, chunker_version, embedding_input_version,
          embedding_provider, embedding_model, embedding_dimensions,
          text_search_configuration, configuration_fingerprint, ready_at, activated_at
        ) SELECT d.tenant_id, d.id, d.id, 1,
          CASE WHEN d.status::text = 'available' AND EXISTS (
            SELECT 1 FROM document_chunks c WHERE c.tenant_id=d.tenant_id AND c.document_id=d.id
          ) THEN 'active'::index_generation_status
          WHEN d.status::text = 'failed' THEN 'failed'::index_generation_status
          WHEN d.status::text = 'processing' THEN 'processing'::index_generation_status
          ELSE 'pending'::index_generation_status END,
          CASE WHEN d.content_type='application/pdf' THEN 'pypdf-6-v1' ELSE 'python-docx-1-v1' END,
          'clean-v1', 'chunk-v1', 'embedding-input-v1', 'openai',
          COALESCE((SELECT c.embedding_model FROM document_chunks c
                    WHERE c.tenant_id=d.tenant_id AND c.document_id=d.id
                    AND c.embedding_model IS NOT NULL LIMIT 1), 'text-embedding-3-small'),
          COALESCE((SELECT c.embedding_dimensions FROM document_chunks c
                    WHERE c.tenant_id=d.tenant_id AND c.document_id=d.id
                    AND c.embedding_dimensions IS NOT NULL LIMIT 1), 1536),
          'simple', md5(d.id::text || '-legacy-generation-1') ||
                    md5(d.id::text || '-legacy-generation-1-secondary'),
          CASE WHEN d.status::text='available' THEN d.updated_at END,
          CASE WHEN d.status::text='available' THEN d.updated_at END
        FROM documents d
    """)

    for table in ("document_source_units", "document_chunks"):
        op.add_column(table, sa.Column("document_version_id", sa.UUID()))
        op.add_column(table, sa.Column("generation_id", sa.UUID()))
        op.execute(
            f"UPDATE {table} t SET document_version_id=t.document_id, generation_id=g.id FROM document_index_generations g WHERE g.tenant_id=t.tenant_id AND g.document_id=t.document_id AND g.document_version_id=t.document_id AND g.generation_number=1"
        )
        op.alter_column(table, "document_version_id", nullable=False)
        op.alter_column(table, "generation_id", nullable=False)
        op.create_foreign_key(
            f"fk_{'chunks' if table == 'document_chunks' else 'source_units'}_generation",
            table,
            "document_index_generations",
            ["tenant_id", "document_id", "document_version_id", "generation_id"],
            ["tenant_id", "document_id", "document_version_id", "id"],
            ondelete="CASCADE",
        )
    op.drop_constraint(
        "fk_document_chunks_tenant_source_unit",
        "document_chunks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_document_chunks_tenant_document_index",
        "document_chunks",
        type_="unique",
    )
    op.drop_constraint(
        "uq_source_units_tenant_document_id",
        "document_source_units",
        type_="unique",
    )
    op.drop_constraint("uq_source_units_index", "document_source_units", type_="unique")
    op.create_unique_constraint(
        "uq_source_units_lifecycle_identity",
        "document_source_units",
        ["tenant_id", "document_id", "document_version_id", "generation_id", "id"],
    )
    op.create_unique_constraint(
        "uq_source_units_generation_index",
        "document_source_units",
        ["tenant_id", "document_id", "generation_id", "unit_index"],
    )
    op.create_unique_constraint(
        "uq_document_chunks_lifecycle_identity",
        "document_chunks",
        ["tenant_id", "document_id", "document_version_id", "generation_id", "id"],
    )
    op.create_unique_constraint(
        "uq_document_chunks_generation_index",
        "document_chunks",
        ["tenant_id", "document_id", "generation_id", "chunk_index"],
    )
    op.create_foreign_key(
        "fk_document_chunks_tenant_source_unit",
        "document_chunks",
        "document_source_units",
        [
            "tenant_id",
            "document_id",
            "document_version_id",
            "generation_id",
            "source_unit_id",
        ],
        ["tenant_id", "document_id", "document_version_id", "generation_id", "id"],
        ondelete="CASCADE",
    )

    op.add_column("processing_jobs", sa.Column("document_version_id", sa.UUID()))
    op.add_column("processing_jobs", sa.Column("generation_id", sa.UUID()))
    op.add_column("processing_jobs", sa.Column("idempotency_key", sa.String(128)))
    op.add_column("processing_jobs", sa.Column("request_fingerprint", sa.String(64)))
    op.add_column("processing_jobs", sa.Column("failure_category", sa.String(100)))
    op.execute("""
        UPDATE processing_jobs j SET document_version_id=j.document_id, generation_id=g.id
        FROM document_index_generations g WHERE g.tenant_id=j.tenant_id
          AND g.document_id=j.document_id AND g.generation_number=1
    """)
    op.create_unique_constraint(
        "uq_processing_jobs_idempotency",
        "processing_jobs",
        ["tenant_id", "document_id", "operation", "idempotency_key"],
    )
    op.create_index(
        "uq_processing_jobs_active_lifecycle",
        "processing_jobs",
        ["tenant_id", "document_id"],
        unique=True,
        postgresql_where=sa.text(
            "operation IN ('replacement_ingestion', 'reindex') "
            "AND status IN ('queued', 'running', 'retrying')"
        ),
    )
    op.create_foreign_key(
        "fk_processing_jobs_version",
        "processing_jobs",
        "document_versions",
        ["tenant_id", "document_id", "document_version_id"],
        ["tenant_id", "document_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_processing_jobs_generation",
        "processing_jobs",
        "document_index_generations",
        ["tenant_id", "document_id", "document_version_id", "generation_id"],
        ["tenant_id", "document_id", "document_version_id", "id"],
        ondelete="CASCADE",
    )

    op.add_column(
        "conversation_citations",
        sa.Column(
            "source_status", sa.String(32), server_default="available", nullable=False
        ),
    )
    op.add_column("conversation_citations", sa.Column("tenant_id", sa.UUID()))
    op.add_column("conversation_citations", sa.Column("generation_id", sa.UUID()))
    op.execute("""
        UPDATE conversation_citations cc
        SET tenant_id=c.tenant_id, generation_id=c.generation_id
        FROM document_chunks c WHERE c.id=cc.chunk_id
    """)
    op.alter_column("conversation_citations", "chunk_id", nullable=True)
    op.alter_column("conversation_citations", "document_id", nullable=True)
    op.alter_column("conversation_citations", "document_version_id", nullable=True)
    op.alter_column("conversation_citations", "exact_excerpt", nullable=True)
    op.create_foreign_key(
        "fk_citations_document_version",
        "conversation_citations",
        "document_versions",
        ["document_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_citations_chunk_lifecycle",
        "conversation_citations",
        "document_chunks",
        [
            "tenant_id",
            "document_id",
            "document_version_id",
            "generation_id",
            "chunk_id",
        ],
        ["tenant_id", "document_id", "document_version_id", "generation_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_citations_source_state",
        "conversation_citations",
        "(source_status='available' AND tenant_id IS NOT NULL AND chunk_id IS NOT NULL AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND generation_id IS NOT NULL AND exact_excerpt IS NOT NULL) OR (source_status='deleted' AND tenant_id IS NULL AND chunk_id IS NULL AND document_id IS NULL AND document_version_id IS NULL AND generation_id IS NULL AND exact_excerpt IS NULL)",
    )

    op.execute("""
        UPDATE document_versions v SET active_generation_id=g.id
        FROM document_index_generations g WHERE g.document_version_id=v.id AND g.status::text='active'
    """)
    op.execute("""
        UPDATE documents d SET active_version_id=v.id
        FROM document_versions v WHERE v.document_id=d.id AND v.status::text='active'
    """)
    op.create_foreign_key(
        "fk_documents_active_version",
        "documents",
        "document_versions",
        ["active_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_versions_active_generation",
        "document_versions",
        "document_index_generations",
        ["active_generation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Retained only for downgrade compatibility; runtime authority moves to
    # document_versions and these legacy snapshot columns become nullable.
    op.drop_constraint("ck_documents_size_nonnegative", "documents", type_="check")
    op.drop_constraint("ck_documents_checksum_sha256", "documents", type_="check")
    op.drop_constraint("uq_documents_tenant_storage_key", "documents", type_="unique")
    for column in (
        "filename",
        "storage_key",
        "content_type",
        "size_bytes",
        "checksum_sha256",
        "metadata",
    ):
        op.alter_column("documents", column, nullable=True)


def downgrade() -> None:
    # Downgrade is intentionally limited to databases that still contain only
    # the backfilled version/generation. Refuse instead of discarding history.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM document_versions WHERE version_number > 1)
             OR EXISTS (SELECT 1 FROM document_index_generations WHERE generation_number > 1) THEN
            RAISE EXCEPTION 'Milestone 12 downgrade would discard lifecycle history';
          END IF;
        END $$
    """)
    op.execute("""
        UPDATE documents d SET
          filename=v.filename, storage_key=v.storage_key,
          content_type=v.content_type, size_bytes=v.size_bytes,
          checksum_sha256=v.checksum_sha256, metadata=v.metadata
        FROM document_versions v
        WHERE v.document_id=d.id AND v.version_number=1
    """)
    for column in (
        "metadata",
        "checksum_sha256",
        "size_bytes",
        "content_type",
        "storage_key",
        "filename",
    ):
        op.alter_column("documents", column, nullable=False)
    op.create_unique_constraint(
        "uq_documents_tenant_storage_key",
        "documents",
        ["tenant_id", "storage_key"],
    )
    op.create_check_constraint(
        "ck_documents_checksum_sha256",
        "documents",
        "checksum_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_documents_size_nonnegative", "documents", "size_bytes >= 0"
    )
    op.drop_constraint(
        "fk_versions_active_generation", "document_versions", type_="foreignkey"
    )
    op.drop_constraint("fk_documents_active_version", "documents", type_="foreignkey")
    op.drop_constraint(
        "ck_citations_source_state", "conversation_citations", type_="check"
    )
    op.drop_constraint(
        "fk_citations_chunk_lifecycle", "conversation_citations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_citations_document_version", "conversation_citations", type_="foreignkey"
    )
    op.alter_column("conversation_citations", "exact_excerpt", nullable=False)
    op.alter_column("conversation_citations", "document_version_id", nullable=False)
    op.alter_column("conversation_citations", "document_id", nullable=False)
    op.alter_column("conversation_citations", "chunk_id", nullable=False)
    op.drop_column("conversation_citations", "source_status")
    op.drop_column("conversation_citations", "generation_id")
    op.drop_column("conversation_citations", "tenant_id")
    op.drop_constraint(
        "uq_processing_jobs_idempotency", "processing_jobs", type_="unique"
    )
    op.execute("DROP INDEX IF EXISTS uq_processing_jobs_active_lifecycle")
    op.execute(
        "ALTER TABLE processing_jobs DROP CONSTRAINT IF EXISTS "
        "fk_processing_jobs_generation"
    )
    op.execute(
        "ALTER TABLE processing_jobs DROP CONSTRAINT IF EXISTS "
        "fk_processing_jobs_version"
    )
    for column in (
        "failure_category",
        "request_fingerprint",
        "idempotency_key",
        "generation_id",
        "document_version_id",
    ):
        op.drop_column("processing_jobs", column)
    op.drop_constraint(
        "fk_document_chunks_tenant_source_unit",
        "document_chunks",
        type_="foreignkey",
    )
    for table, names in (
        (
            "document_chunks",
            (
                "uq_document_chunks_generation_index",
                "uq_document_chunks_lifecycle_identity",
            ),
        ),
        (
            "document_source_units",
            (
                "uq_source_units_generation_index",
                "uq_source_units_lifecycle_identity",
            ),
        ),
    ):
        for name in names:
            op.drop_constraint(name, table, type_="unique")
    for table in ("document_chunks", "document_source_units"):
        op.drop_constraint(
            f"fk_{'chunks' if table == 'document_chunks' else 'source_units'}_generation",
            table,
            type_="foreignkey",
        )
        op.drop_column(table, "generation_id")
        op.drop_column(table, "document_version_id")
    op.create_unique_constraint(
        "uq_source_units_tenant_document_id",
        "document_source_units",
        ["tenant_id", "document_id", "id"],
    )
    op.create_unique_constraint(
        "uq_source_units_index",
        "document_source_units",
        ["tenant_id", "document_id", "unit_index"],
    )
    op.create_unique_constraint(
        "uq_document_chunks_tenant_document_index",
        "document_chunks",
        ["tenant_id", "document_id", "chunk_index"],
    )
    op.create_foreign_key(
        "fk_document_chunks_tenant_source_unit",
        "document_chunks",
        "document_source_units",
        ["tenant_id", "document_id", "source_unit_id"],
        ["tenant_id", "document_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_table("document_index_generations")
    op.drop_table("document_versions")
    op.drop_column("documents", "deleted_at")
    op.drop_column("documents", "next_version_number")
    op.drop_column("documents", "active_version_id")
    op.drop_constraint("uq_documents_tenant_collection_id", "documents", type_="unique")
    postgresql.ENUM(name="index_generation_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="document_version_status").drop(op.get_bind(), checkfirst=True)

"""add normalized source units and deterministic chunk traceability

Revision ID: c5d9e2f1a804
Revises: 8b1f2d4e6a70
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5d9e2f1a804"
down_revision: str | None = "8b1f2d4e6a70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_source_units",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("unit_index", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_path", sa.String(1000), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("unit_index >= 0", name="ck_source_units_index_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_source_units_tenant_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "id",
            name="uq_source_units_tenant_document_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "document_id", "unit_index", name="uq_source_units_index"
        ),
    )
    op.create_index(
        "ix_source_units_tenant_document",
        "document_source_units",
        ["tenant_id", "document_id"],
    )
    op.add_column(
        "document_chunks", sa.Column("source_unit_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "document_chunks", sa.Column("content_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column("pipeline_fingerprint", sa.String(64), nullable=True),
    )
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM document_chunks) THEN
            RAISE EXCEPTION
              'cannot migrate existing chunks without reproducible source units';
          END IF;
        END $$
    """)
    for column in (
        "source_unit_id",
        "content_hash",
        "pipeline_fingerprint",
        "start_offset",
        "end_offset",
    ):
        op.alter_column("document_chunks", column, nullable=False)
    op.create_foreign_key(
        "fk_document_chunks_tenant_source_unit",
        "document_chunks",
        "document_source_units",
        ["tenant_id", "document_id", "source_unit_id"],
        ["tenant_id", "document_id", "id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_document_chunks_tenant_source_unit", "document_chunks", type_="foreignkey"
    )
    op.drop_column("document_chunks", "pipeline_fingerprint")
    op.drop_column("document_chunks", "content_hash")
    op.drop_column("document_chunks", "source_unit_id")
    op.drop_index("ix_source_units_tenant_document", table_name="document_source_units")
    op.drop_table("document_source_units")

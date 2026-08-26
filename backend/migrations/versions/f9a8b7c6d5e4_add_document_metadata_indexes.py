"""add bounded document metadata constraints and filter indexes

Revision ID: f9a8b7c6d5e4
Revises: e8f7a6b5c4d3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a8b7c6d5e4"
down_revision: str | None = "e8f7a6b5c4d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_documents_metadata_object",
        "documents",
        "jsonb_typeof(metadata) = 'object'",
    )
    op.create_check_constraint(
        "ck_documents_metadata_size",
        "documents",
        "pg_column_size(metadata) <= 8192",
    )
    op.create_index(
        "ix_documents_tenant_collection_created_at",
        "documents",
        ["tenant_id", "collection_id", "created_at"],
    )
    op.create_index(
        "ix_documents_tenant_collection_content_type",
        "documents",
        ["tenant_id", "collection_id", "content_type"],
    )
    op.create_index(
        "ix_documents_tenant_collection_filename",
        "documents",
        ["tenant_id", "collection_id", "filename"],
    )
    op.create_index(
        "ix_documents_metadata_tags_gin",
        "documents",
        [sa.text("(metadata -> 'tags')")],
        postgresql_using="gin",
    )
    for name, expression in (
        ("department", "(metadata ->> 'department')"),
        ("document_type", "(metadata ->> 'document_type')"),
        ("language", "(metadata ->> 'language')"),
        ("effective_date", "(metadata ->> 'effective_date')"),
    ):
        op.create_index(
            f"ix_documents_metadata_{name}",
            "documents",
            [sa.text(expression)],
        )


def downgrade() -> None:
    for name in ("effective_date", "language", "document_type", "department"):
        op.drop_index(f"ix_documents_metadata_{name}", table_name="documents")
    op.drop_index("ix_documents_metadata_tags_gin", table_name="documents")
    op.drop_index(
        "ix_documents_tenant_collection_filename", table_name="documents"
    )
    op.drop_index(
        "ix_documents_tenant_collection_content_type", table_name="documents"
    )
    op.drop_index(
        "ix_documents_tenant_collection_created_at", table_name="documents"
    )
    op.drop_constraint("ck_documents_metadata_size", "documents", type_="check")
    op.drop_constraint("ck_documents_metadata_object", "documents", type_="check")

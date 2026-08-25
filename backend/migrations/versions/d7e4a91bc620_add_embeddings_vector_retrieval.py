"""add embeddings vector retrieval

Revision ID: d7e4a91bc620
Revises: c5d9e2f1a804
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "d7e4a91bc620"
down_revision: str | None = "c5d9e2f1a804"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("embedding", VECTOR(1536)))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(200)))
    op.add_column("document_chunks", sa.Column("embedding_dimensions", sa.Integer()))
    op.add_column(
        "document_chunks", sa.Column("embedding_input_version", sa.String(50))
    )
    op.add_column("document_chunks", sa.Column("embedding_fingerprint", sa.String(64)))
    op.add_column(
        "document_chunks", sa.Column("embedded_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_complete",
        "document_chunks",
        "(embedding IS NULL AND embedding_model IS NULL AND "
        "embedding_dimensions IS NULL "
        "AND embedding_input_version IS NULL AND embedding_fingerprint IS NULL AND "
        "embedded_at IS NULL) OR (embedding IS NOT NULL AND "
        "embedding_model IS NOT NULL "
        "AND embedding_dimensions = 1536 AND embedding_input_version IS NOT NULL AND "
        "embedding_fingerprint IS NOT NULL AND embedded_at IS NOT NULL)",
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw_cosine",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )
    op.create_index(
        "ix_document_chunks_tenant_embedding",
        "document_chunks",
        ["tenant_id", "document_id"],
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_tenant_embedding", table_name="document_chunks")
    op.drop_index(
        "ix_document_chunks_embedding_hnsw_cosine", table_name="document_chunks"
    )
    op.drop_constraint(
        "ck_document_chunks_embedding_complete", "document_chunks", type_="check"
    )
    for column in (
        "embedded_at",
        "embedding_fingerprint",
        "embedding_input_version",
        "embedding_dimensions",
        "embedding_model",
        "embedding",
    ):
        op.drop_column("document_chunks", column)

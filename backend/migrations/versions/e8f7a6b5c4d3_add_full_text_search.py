"""add generated full-text search vector and GIN index

Revision ID: e8f7a6b5c4d3
Revises: d7e4a91bc620
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f7a6b5c4d3"
down_revision: str | None = "d7e4a91bc620"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_VECTOR_EXPRESSION = (
    "setweight(to_tsvector('simple'::regconfig, coalesce(section, '')), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_search_vector_gin", table_name="document_chunks"
    )
    op.drop_column("document_chunks", "search_vector")

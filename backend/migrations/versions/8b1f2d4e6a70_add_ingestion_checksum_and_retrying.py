"""add ingestion checksum and retrying status

Revision ID: 8b1f2d4e6a70
Revises: 3f2a1c9d8b7e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b1f2d4e6a70"
down_revision: str | None = "3f2a1c9d8b7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE processing_job_status ADD VALUE IF NOT EXISTS "
        "'retrying' AFTER 'running'"
    )
    op.add_column(
        "documents", sa.Column("checksum_sha256", sa.String(64), nullable=True)
    )
    op.execute(
        "UPDATE documents SET checksum_sha256 = repeat('0', 64) "
        "WHERE checksum_sha256 IS NULL"
    )
    op.alter_column("documents", "checksum_sha256", nullable=False)
    op.create_check_constraint(
        "ck_documents_checksum_sha256",
        "documents",
        "checksum_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_checksum_sha256", "documents", type_="check")
    op.drop_column("documents", "checksum_sha256")
    # PostgreSQL enum values cannot be safely removed in place; this value remains.

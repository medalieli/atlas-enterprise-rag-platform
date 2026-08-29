"""Add secure invitation removal state.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_invitations_status", "invitations", type_="check")
    op.create_check_constraint(
        "ck_invitations_status",
        "invitations",
        "status IN ('pending','accepted','expired','revoked','replaced','removed')",
    )
    op.add_column("invitations", sa.Column("removed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.execute("UPDATE invitations SET status = 'revoked' WHERE status = 'removed'")
    op.drop_column("invitations", "removed_at")
    op.drop_constraint("ck_invitations_status", "invitations", type_="check")
    op.create_check_constraint(
        "ck_invitations_status",
        "invitations",
        "status IN ('pending','accepted','expired','revoked','replaced')",
    )

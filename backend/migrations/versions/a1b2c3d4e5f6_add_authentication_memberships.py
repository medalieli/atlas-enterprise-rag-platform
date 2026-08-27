"""add external identities and authorized tenant memberships

Revision ID: a1b2c3d4e5f6
Revises: f9a8b7c6d5e4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f9a8b7c6d5e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("issuer", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("subject", sa.String(500), nullable=True))
    op.add_column(
        "users",
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.execute(
        "UPDATE users SET issuer = 'urn:production-rag-assistant:legacy', "
        "subject = id::text WHERE issuer IS NULL OR subject IS NULL"
    )
    op.alter_column("users", "issuer", nullable=False)
    op.alter_column("users", "subject", nullable=False)
    op.alter_column("users", "email", nullable=True)
    op.create_unique_constraint(
        "uq_users_issuer_subject", "users", ["issuer", "subject"]
    )
    op.create_index("ix_users_issuer_subject", "users", ["issuer", "subject"])

    op.execute("CREATE TYPE membership_role_v2 AS ENUM ('viewer', 'editor', 'admin')")
    op.execute("ALTER TABLE memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE memberships ALTER COLUMN role TYPE membership_role_v2 "
        "USING (CASE WHEN role::text = 'member' THEN 'viewer' "
        "ELSE role::text END)::membership_role_v2"
    )
    op.execute("DROP TYPE membership_role")
    op.execute("ALTER TYPE membership_role_v2 RENAME TO membership_role")
    op.execute("ALTER TABLE memberships ALTER COLUMN role SET DEFAULT 'viewer'")
    op.add_column(
        "memberships",
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index(
        "ix_memberships_tenant_enabled", "memberships", ["tenant_id", "enabled"]
    )

    op.add_column(
        "processing_jobs",
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_processing_jobs_requested_by_user",
        "processing_jobs",
        "users",
        ["requested_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_processing_jobs_requested_by",
        "processing_jobs",
        ["requested_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_requested_by", table_name="processing_jobs")
    op.drop_constraint(
        "fk_processing_jobs_requested_by_user",
        "processing_jobs",
        type_="foreignkey",
    )
    op.drop_column("processing_jobs", "requested_by_user_id")

    op.drop_index("ix_memberships_tenant_enabled", table_name="memberships")
    op.drop_column("memberships", "enabled")
    op.execute("CREATE TYPE membership_role_v1 AS ENUM ('member', 'admin')")
    op.execute("ALTER TABLE memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE memberships ALTER COLUMN role TYPE membership_role_v1 "
        "USING (CASE WHEN role::text = 'admin' THEN 'admin' "
        "ELSE 'member' END)::membership_role_v1"
    )
    op.execute("DROP TYPE membership_role")
    op.execute("ALTER TYPE membership_role_v1 RENAME TO membership_role")
    op.execute("ALTER TABLE memberships ALTER COLUMN role SET DEFAULT 'member'")

    op.drop_index("ix_users_issuer_subject", table_name="users")
    op.drop_constraint("uq_users_issuer_subject", "users", type_="unique")
    op.execute(
        "UPDATE users SET email = 'legacy-' || id::text || '@invalid.local' "
        "WHERE email IS NULL"
    )
    op.alter_column("users", "email", nullable=False)
    op.drop_column("users", "enabled")
    op.drop_column("users", "subject")
    op.drop_column("users", "issuer")

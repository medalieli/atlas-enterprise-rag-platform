"""add post-v1 enterprise administration

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE collection_role AS ENUM ('manager','editor','viewer')")
    op.add_column(
        "memberships",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "memberships",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_memberships_status",
        "memberships",
        "status IN ('active','suspended','revoked')",
    )
    op.create_check_constraint("ck_memberships_version", "memberships", "version >= 1")
    op.create_unique_constraint(
        "uq_memberships_tenant_id_id", "memberships", ["tenant_id", "id"]
    )

    op.create_table(
        "collection_grants",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "manager", "editor", "viewer", name="collection_role", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.UUID()),
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
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            name="fk_grants_tenant_collection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_grants_tenant_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "collection_id",
            "membership_id",
            name="uq_collection_grants_scope",
        ),
    )
    op.create_index(
        "ix_collection_grants_member_collection",
        "collection_grants",
        ["membership_id", "collection_id"],
    )
    # Preserve prior editor/viewer access exactly before replacing the organization role enum.
    op.execute("""INSERT INTO collection_grants (tenant_id,collection_id,membership_id,role,created_by_user_id)
        SELECT m.tenant_id,c.id,m.id,CASE WHEN m.role::text='editor' THEN 'editor'::collection_role ELSE 'viewer'::collection_role END,m.user_id
        FROM memberships m JOIN collections c ON c.tenant_id=m.tenant_id WHERE m.role::text IN ('editor','viewer')""")
    op.execute("CREATE TYPE membership_role_v3 AS ENUM ('owner','admin','member')")
    op.execute("ALTER TABLE memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE memberships ALTER COLUMN role TYPE membership_role_v3 USING (CASE WHEN role::text='admin' THEN 'owner' ELSE 'member' END)::membership_role_v3"
    )
    op.execute("DROP TYPE membership_role")
    op.execute("ALTER TYPE membership_role_v3 RENAME TO membership_role")
    op.execute("ALTER TABLE memberships ALTER COLUMN role SET DEFAULT 'member'")

    op.create_table(
        "invitations",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "owner", "admin", "member", name="membership_role", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.UUID()),
        sa.Column("accepted_by_user_id", sa.UUID()),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "initial_grants",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        sa.CheckConstraint(
            "status IN ('pending','accepted','expired','revoked','replaced')",
            name="ck_invitations_status",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 10", name="ck_invitations_attempts"
        ),
    )
    op.create_index(
        "ix_invitations_tenant_status_created",
        "invitations",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_invitations_tenant_email", "invitations", ["tenant_id", "email_normalized"]
    )

    op.create_table(
        "audit_events",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID()),
        sa.Column("actor_role", sa.String(32)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.UUID()),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('success','denied','failure')", name="ck_audit_outcome"
        ),
        sa.CheckConstraint(
            "pg_column_size(metadata) <= 2048", name="ck_audit_metadata_size"
        ),
    )
    op.create_index(
        "ix_audit_tenant_created_id", "audit_events", ["tenant_id", "created_at", "id"]
    )
    op.create_index(
        "ix_audit_tenant_actor",
        "audit_events",
        ["tenant_id", "actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_audit_tenant_action", "audit_events", ["tenant_id", "action", "created_at"]
    )
    op.execute(
        """CREATE FUNCTION prevent_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM organizations WHERE id = OLD.tenant_id) THEN RETURN OLD; END IF; RAISE EXCEPTION 'audit events are append-only'; END $$"""
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation()"
    )

    op.create_unique_constraint(
        "uq_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id", "id"],
    )
    op.create_table(
        "answer_feedback",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("assistant_message_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32)),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id", "conversation_id", "user_id"],
            ["conversations.tenant_id", "conversations.collection_id", "conversations.id", "conversations.created_by_user_id"],
            name="fk_feedback_owned_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "assistant_message_id"],
            ["conversation_messages.conversation_id", "conversation_messages.id"],
            name="fk_feedback_conversation_message",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "assistant_message_id",
            name="uq_feedback_user_answer",
        ),
        sa.CheckConstraint(
            "rating IN ('helpful','not_helpful')", name="ck_feedback_rating"
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('incorrect','incomplete','irrelevant_sources','citation_problem','outdated_source','other')",
            name="ck_feedback_reason",
        ),
    )
    op.create_index(
        "ix_feedback_tenant_created", "answer_feedback", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("answer_feedback")
    op.execute(
        "ALTER TABLE conversation_messages DROP CONSTRAINT IF EXISTS "
        "uq_conversation_messages_conversation_id"
    )
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION prevent_audit_mutation()")
    op.drop_table("audit_events")
    op.drop_table("invitations")
    op.execute("CREATE TYPE membership_role_v2 AS ENUM ('viewer','editor','admin')")
    op.execute("ALTER TABLE memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE memberships ALTER COLUMN role TYPE membership_role_v2 USING (CASE WHEN role::text IN ('owner','admin') THEN 'admin' ELSE 'viewer' END)::membership_role_v2"
    )
    op.execute("DROP TYPE membership_role")
    op.execute("ALTER TYPE membership_role_v2 RENAME TO membership_role")
    op.execute("ALTER TABLE memberships ALTER COLUMN role SET DEFAULT 'viewer'")
    op.drop_table("collection_grants")
    op.execute("DROP TYPE collection_role")
    op.drop_constraint("uq_memberships_tenant_id_id", "memberships", type_="unique")
    op.drop_constraint("ck_memberships_version", "memberships", type_="check")
    op.drop_constraint("ck_memberships_status", "memberships", type_="check")
    op.drop_column("memberships", "version")
    op.drop_column("memberships", "status")

"""add conversation turns and messages

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_conversations_owned_identity",
        "conversations",
        ["tenant_id", "collection_id", "id", "created_by_user_id"],
    )
    turn_status = postgresql.ENUM(
        "pending",
        "completed",
        "failed",
        name="conversation_turn_status",
        create_type=False,
    )
    message_role = postgresql.ENUM(
        "user", "assistant", name="conversation_message_role", create_type=False
    )
    turn_status.create(op.get_bind(), checkfirst=True)
    message_role.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", turn_status, server_default="pending", nullable=False),
        sa.Column("original_question", sa.Text(), nullable=False),
        sa.Column("standalone_question", sa.Text()),
        sa.Column("rewrite_status", sa.String(32)),
        sa.Column("clarification_question", sa.String(1000)),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("response", postgresql.JSONB()),
        sa.Column("failure_category", sa.String(100)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "sequence_number >= 1", name="ck_conversation_turn_sequence"
        ),
        sa.CheckConstraint("top_k BETWEEN 1 AND 20", name="ck_conversation_turn_top_k"),
        sa.CheckConstraint(
            "char_length(original_question) BETWEEN 1 AND 8000",
            name="ck_conversation_turn_question_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id", "conversation_id", "created_by_user_id"],
            [
                "conversations.tenant_id",
                "conversations.collection_id",
                "conversations.id",
                "conversations.created_by_user_id",
            ],
            name="fk_conversation_turns_owned_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "sequence_number", name="uq_conversation_turn_sequence"
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_conversation_turn_idempotency",
        ),
    )
    op.create_index(
        "ix_conversation_turns_owner",
        "conversation_turns",
        ["tenant_id", "collection_id", "created_by_user_id"],
    )
    op.create_index(
        "uq_conversation_turn_one_pending",
        "conversation_turns",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "sequence_number >= 1", name="ck_conversation_message_sequence"
        ),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 16000",
            name="ck_conversation_message_content",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_message_sequence",
        ),
    )
    op.create_index(
        "ix_conversation_messages_history",
        "conversation_messages",
        ["conversation_id", "sequence_number"],
    )
    op.create_table(
        "conversation_citations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("assistant_message_id", sa.UUID(), nullable=False),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("section_path", sa.String(1000)),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column(
            "document_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("exact_excerpt", sa.Text(), nullable=False),
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
        sa.CheckConstraint(
            "citation_order >= 1", name="ck_conversation_citation_order"
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"], ["conversation_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["document_chunks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistant_message_id",
            "citation_order",
            name="uq_conversation_citation_order",
        ),
    )
    op.create_index(
        "ix_conversation_citations_message",
        "conversation_citations",
        ["assistant_message_id"],
    )


def downgrade() -> None:
    op.drop_table("conversation_citations")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_turns")
    op.drop_constraint(
        "uq_conversations_owned_identity", "conversations", type_="unique"
    )
    postgresql.ENUM(name="conversation_message_role").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="conversation_turn_status").drop(
        op.get_bind(), checkfirst=True
    )

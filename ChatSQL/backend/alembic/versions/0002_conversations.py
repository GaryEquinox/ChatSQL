"""Conversation lifecycle tables.

Revision ID: 0002_conversations
Revises: 0001_initial
Create Date: 2026-07-19
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_conversations"
down_revision: Optional[str] = "0001_initial"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("selected_dataset_id", sa.String(length=36), nullable=False),
        sa.Column("scroll_position", sa.Integer(), nullable=False),
        sa.Column("query_summary", sa.Text(), nullable=False),
        sa.Column("last_user_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_created_at"), "conversations", ["created_at"], unique=False)
    op.create_index(op.f("ix_conversations_last_activity_at"), "conversations", ["last_activity_at"], unique=False)
    op.create_index(op.f("ix_conversations_status"), "conversations", ["status"], unique=False)

    op.create_table(
        "context_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("query_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_context_segments_conversation_id"), "context_segments", ["conversation_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("context_segment_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("query_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["context_segment_id"], ["context_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_context_segment_id"), "messages", ["context_segment_id"], unique=False)
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_messages_created_at"), "messages", ["created_at"], unique=False)

    op.create_table(
        "debug_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("context_segment_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["context_segment_id"], ["context_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_debug_records_context_segment_id"), "debug_records", ["context_segment_id"], unique=False)
    op.create_index(op.f("ix_debug_records_conversation_id"), "debug_records", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_debug_records_message_id"), "debug_records", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_debug_records_message_id"), table_name="debug_records")
    op.drop_index(op.f("ix_debug_records_conversation_id"), table_name="debug_records")
    op.drop_index(op.f("ix_debug_records_context_segment_id"), table_name="debug_records")
    op.drop_table("debug_records")
    op.drop_index(op.f("ix_messages_created_at"), table_name="messages")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_context_segment_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_context_segments_conversation_id"), table_name="context_segments")
    op.drop_table("context_segments")
    op.drop_index(op.f("ix_conversations_status"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_last_activity_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_created_at"), table_name="conversations")
    op.drop_table("conversations")

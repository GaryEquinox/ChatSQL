"""add llm configs

Revision ID: 0003_llm_configs
Revises: 0002_conversations
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_llm_configs"
down_revision = "0002_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("provider_type", sa.String(length=16), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="1200"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0"),
        sa.Column("structured_output_mode", sa.String(length=24), nullable=False, server_default="auto"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_configs_name", "llm_configs", ["name"], unique=True)
    op.create_index("ix_llm_configs_is_enabled", "llm_configs", ["is_enabled"])
    op.create_index("ix_llm_configs_created_at", "llm_configs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_configs_created_at", table_name="llm_configs")
    op.drop_index("ix_llm_configs_is_enabled", table_name="llm_configs")
    op.drop_index("ix_llm_configs_name", table_name="llm_configs")
    op.drop_table("llm_configs")

"""Initial dataset registry.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-19
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Optional[str] = None
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("short_code", sa.String(length=4), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("dialect", sa.String(length=32), nullable=False),
        sa.Column("db_version", sa.String(length=80), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_datasets_created_at"), "datasets", ["created_at"], unique=False)
    op.create_index(op.f("ix_datasets_name"), "datasets", ["name"], unique=True)
    op.create_index(op.f("ix_datasets_short_code"), "datasets", ["short_code"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_datasets_short_code"), table_name="datasets")
    op.drop_index(op.f("ix_datasets_name"), table_name="datasets")
    op.drop_index(op.f("ix_datasets_created_at"), table_name="datasets")
    op.drop_table("datasets")

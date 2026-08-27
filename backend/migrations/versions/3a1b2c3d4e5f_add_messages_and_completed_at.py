"""add messages table and completed_at to runs

Revision ID: 3a1b2c3d4e5f
Revises: b9f3a1c72d08
Create Date: 2026-07-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "b9f3a1c72d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── messages table ──────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("thread_id", sqlmodel.sql.sqltypes.AutoString(length=150), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_type", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column("tool_name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("tool_input", sa.Text(), nullable=True),
        sa.Column("tool_output", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_thread_id"), "messages", ["thread_id"], unique=False)
    op.create_index(op.f("ix_messages_user_id"), "messages", ["user_id"], unique=False)
    op.create_foreign_key("messages_user_id_fkey", "messages", "users", ["user_id"], ["id"])

    # ── runs: add completed_at ──────────────────────────────────────────
    op.add_column("runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    # ── runs: make user_id nullable (will be populated when auth is wired in) ─
    op.alter_column("runs", "user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Revert user_id to NOT NULL
    op.alter_column("runs", "user_id", existing_type=sa.Integer(), nullable=False)

    # Drop messages
    op.drop_constraint("messages_user_id_fkey", "messages", type_="foreignkey")
    op.drop_index(op.f("ix_messages_user_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_thread_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_column("runs", "completed_at")
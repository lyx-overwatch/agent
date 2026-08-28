"""add hashed_password and unique email to users

Revision ID: 3f5a8b2c1d9e
Revises: 9bab26aea54c
Create Date: 2026-08-28 10:00:00.000000

Changes:
  - users: add ``hashed_password`` VARCHAR(200) nullable（邮箱登录用，Java 用户无密码为 NULL）
  - users.email: add UNIQUE index（Postgres 唯一索引允许多个 NULL，不影响既有 Java 用户的 NULL email）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3f5a8b2c1d9e'
down_revision: str | Sequence[str] | None = '9bab26aea54c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("hashed_password", sa.String(length=200), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "hashed_password")

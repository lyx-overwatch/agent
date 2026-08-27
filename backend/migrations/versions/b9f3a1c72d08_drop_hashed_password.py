"""drop hashed_password from users

Revision ID: b9f3a1c72d08
Revises: 4e84e424260b
Create Date: 2026-04-07 18:00:00.000000

用户认证改为代理到外部 Java 系统，本系统不再存储密码。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9f3a1c72d08"
down_revision: str | Sequence[str] | None = "4e84e424260b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "hashed_password")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "hashed_password",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )
    # 恢复后 server_default 不再需要，移除以保持原始约束
    op.alter_column("users", "hashed_password", server_default=None)

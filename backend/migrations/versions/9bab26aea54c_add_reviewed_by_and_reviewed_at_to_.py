"""add reviewed_by and reviewed_at to skills

Revision ID: 9bab26aea54c
Revises: a54b98e5cd18
Create Date: 2026-08-25 16:00:18.961629

Changes:
  - skills: add ``reviewed_by`` VARCHAR(100) NULL（审核人 user_id）
  - skills: add ``reviewed_at`` TIMESTAMPTZ NULL（审核时间）
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9bab26aea54c'
down_revision: str | Sequence[str] | None = 'a54b98e5cd18'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("skills", sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True))
    op.add_column("skills", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("skills", "reviewed_at")
    op.drop_column("skills", "reviewed_by")

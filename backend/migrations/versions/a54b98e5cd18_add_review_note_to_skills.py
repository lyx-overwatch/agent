"""add review_note to skills

Revision ID: a54b98e5cd18
Revises: 311e49d8b58b
Create Date: 2026-08-25 15:42:55.254519

Changes:
  - skills: add ``review_note`` TEXT NULL（审核驳回原因，reject 时写入、approve/publish 时清空）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a54b98e5cd18'
down_revision: str | Sequence[str] | None = '311e49d8b58b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("skills", sa.Column("review_note", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("skills", "review_note")

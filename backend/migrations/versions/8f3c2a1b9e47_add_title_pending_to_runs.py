"""add title_pending to runs

Revision ID: 8f3c2a1b9e47
Revises: ed97e83b55ca
Create Date: 2026-08-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3c2a1b9e47"
down_revision: str | Sequence[str] | None = "ed97e83b55ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add title_pending flag to track in-flight background title generation."""
    op.add_column("runs", sa.Column("title_pending", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Drop title_pending flag."""
    op.drop_column("runs", "title_pending")

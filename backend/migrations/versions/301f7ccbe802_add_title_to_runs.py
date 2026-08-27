"""add title to runs

Revision ID: 301f7ccbe802
Revises: b69146de9e4c
Create Date: 2026-07-16 16:42:52.788609

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '301f7ccbe802'
down_revision: str | Sequence[str] | None = 'b69146de9e4c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('runs', sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('runs', 'title')
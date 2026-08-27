"""add total_tokens to runs

Revision ID: 4e06803e30bc
Revises: 301f7ccbe802
Create Date: 2026-07-16 17:24:54.634207

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4e06803e30bc'
down_revision: str | Sequence[str] | None = '301f7ccbe802'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('runs', sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('runs', 'total_tokens')
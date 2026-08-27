"""add cache_read and cache_creation to runs

Revision ID: 14ff6b5da46f
Revises: bdee07cca022
Create Date: 2026-07-21 17:29:22.462427

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '14ff6b5da46f'
down_revision: str | Sequence[str] | None = 'bdee07cca022'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('cache_read', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('runs', sa.Column('cache_creation', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('runs', 'cache_creation')
    op.drop_column('runs', 'cache_read')

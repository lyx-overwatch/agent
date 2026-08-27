"""add_description_to_messages

Revision ID: bb719104baf5
Revises: aa2071cd9bbd
Create Date: 2026-07-24 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bb719104baf5'
down_revision: str | Sequence[str] | None = 'aa2071cd9bbd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'description')

"""add duration_ms to messages

Revision ID: ed97e83b55ca
Revises: bb719104baf5
Create Date: 2026-07-27 14:38:11.132603

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ed97e83b55ca'
down_revision: str | Sequence[str] | None = 'bb719104baf5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('duration_ms', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'duration_ms')

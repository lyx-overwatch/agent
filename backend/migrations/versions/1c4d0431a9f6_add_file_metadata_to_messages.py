"""add_file_metadata_to_messages

Revision ID: 1c4d0431a9f6
Revises: 2651d3f6bd13
Create Date: 2026-07-21 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1c4d0431a9f6'
down_revision: str | Sequence[str] | None = '2651d3f6bd13'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('file_metadata', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'file_metadata')

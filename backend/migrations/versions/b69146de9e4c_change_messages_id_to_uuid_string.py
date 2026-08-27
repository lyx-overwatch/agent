"""change messages id to uuid string

Revision ID: b69146de9e4c
Revises: 3a1b2c3d4e5f
Create Date: 2026-07-16 16:32:36.400985

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b69146de9e4c'
down_revision: str | Sequence[str] | None = '3a1b2c3d4e5f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('messages', 'id',
               existing_type=sa.INTEGER(),
               type_=sqlmodel.sql.sqltypes.AutoString(length=36),
               existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('messages', 'id',
               existing_type=sqlmodel.sql.sqltypes.AutoString(length=36),
               type_=sa.INTEGER(),
               existing_nullable=False)
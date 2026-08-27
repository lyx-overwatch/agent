"""drop_thinking_enabled_from_runs

Revision ID: bdee07cca022
Revises: 1c4d0431a9f6
Create Date: 2026-07-21 16:26:27.257144

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bdee07cca022'
down_revision: str | Sequence[str] | None = '1c4d0431a9f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — safe for both fresh databases and incremental upgrades."""
    # The column may not exist on a fresh database created from current
    # SQLModel metadata (where thinking_enabled has already been removed).
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("runs")]
    if "thinking_enabled" in columns:
        op.drop_column("runs", "thinking_enabled")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('runs', sa.Column('thinking_enabled', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False))

"""change_runs_id_to_uuid_and_add_conversation_id_to_messages

Revision ID: 2651d3f6bd13
Revises: 4e06803e30bc
Create Date: 2026-07-17 11:00:25.412526

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2651d3f6bd13'
down_revision: str | Sequence[str] | None = '4e06803e30bc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop orphaned LangGraph checkpoint tables (not used by current code).
    #    if_exists=True：全新库上这些表可能不存在（由旧版 checkpointer 自建），跳过即可。
    op.drop_table('checkpoint_migrations', if_exists=True)
    op.drop_index(op.f('checkpoint_blobs_thread_id_idx'), table_name='checkpoint_blobs', if_exists=True)
    op.drop_table('checkpoint_blobs', if_exists=True)
    op.drop_index(op.f('checkpoint_writes_thread_id_idx'), table_name='checkpoint_writes', if_exists=True)
    op.drop_table('checkpoint_writes', if_exists=True)
    op.drop_index(op.f('checkpoints_thread_id_idx'), table_name='checkpoints', if_exists=True)
    op.drop_table('checkpoints', if_exists=True)

    # 2. Add conversation_id to messages (nullable — existing rows get NULL)
    op.add_column('messages', sa.Column('conversation_id', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=True))
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)

    # 3. Alter runs.id from SERIAL/INTEGER to UUID string
    #    Drop the auto-increment default first, then convert the column.
    op.execute("ALTER TABLE runs ALTER COLUMN id DROP DEFAULT")
    op.alter_column('runs', 'id',
               existing_type=sa.INTEGER(),
               type_=sqlmodel.sql.sqltypes.AutoString(length=36),
               existing_nullable=False,
               postgresql_using='id::text')

    # 4. Add FK constraint (runs.id is now the correct type)
    op.create_foreign_key(None, 'messages', 'runs', ['conversation_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(None, 'messages', type_='foreignkey')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_column('messages', 'conversation_id')

    # Revert runs.id to INTEGER — existing string values will be lost
    op.alter_column('runs', 'id',
               existing_type=sqlmodel.sql.sqltypes.AutoString(length=36),
               type_=sa.INTEGER(),
               existing_nullable=False,
               postgresql_using='0')

    op.create_table('checkpoints',
    sa.Column('thread_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('checkpoint_ns', sa.TEXT(), server_default=sa.text("''::text"), autoincrement=False, nullable=False),
    sa.Column('checkpoint_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('parent_checkpoint_id', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('type', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id', name=op.f('checkpoints_pkey'))
    )
    op.create_index(op.f('checkpoints_thread_id_idx'), 'checkpoints', ['thread_id'], unique=False)
    op.create_table('checkpoint_writes',
    sa.Column('thread_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('checkpoint_ns', sa.TEXT(), server_default=sa.text("''::text"), autoincrement=False, nullable=False),
    sa.Column('checkpoint_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('task_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('idx', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('channel', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('type', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('blob', postgresql.BYTEA(), autoincrement=False, nullable=False),
    sa.Column('task_path', sa.TEXT(), server_default=sa.text("''::text"), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id', 'task_id', 'idx', name=op.f('checkpoint_writes_pkey'))
    )
    op.create_index(op.f('checkpoint_writes_thread_id_idx'), 'checkpoint_writes', ['thread_id'], unique=False)
    op.create_table('checkpoint_blobs',
    sa.Column('thread_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('checkpoint_ns', sa.TEXT(), server_default=sa.text("''::text"), autoincrement=False, nullable=False),
    sa.Column('channel', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('version', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('type', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('blob', postgresql.BYTEA(), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'channel', 'version', name=op.f('checkpoint_blobs_pkey'))
    )
    op.create_index(op.f('checkpoint_blobs_thread_id_idx'), 'checkpoint_blobs', ['thread_id'], unique=False)
    op.create_table('checkpoint_migrations',
    sa.Column('v', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('v', name=op.f('checkpoint_migrations_pkey'))
    )
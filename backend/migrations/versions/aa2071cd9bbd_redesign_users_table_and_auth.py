"""redesign_users_table_and_auth

Revision ID: aa2071cd9bbd
Revises: 14ff6b5da46f
Create Date: 2026-07-22 09:09:01.263047

Changes:
  - users.id: INT auto-increment → VARCHAR(100) (now = Java login_user_key)
  - users.username / users.email: NOT NULL → nullable
  - users.email: drop UNIQUE index
  - user_skills.user_id: INT → VARCHAR(100) FK→users.id
  - runs.user_id / messages.user_id: add FK→users.id (columns already VARCHAR)
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'aa2071cd9bbd'
down_revision: str | Sequence[str] | None = '14ff6b5da46f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Redesign users table to use login_user_key as PK."""

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_fks = _get_foreign_keys(inspector, "users")

    # 1. Drop all FKs pointing to users.id before touching the PK.
    #    Different database states may have different subsets; check each.
    for fk_name, source_table in [
        ("user_skills_user_id_fkey", "user_skills"),
        ("runs_user_id_fkey", "runs"),
        ("messages_user_id_fkey", "messages"),
    ]:
        if fk_name in existing_fks:
            op.drop_constraint(fk_name, source_table, type_="foreignkey")

    # 2. Drop users.id default (SERIAL sequence) and PK constraint
    op.execute("ALTER TABLE users ALTER COLUMN id DROP DEFAULT")
    op.drop_constraint('users_pkey', 'users', type_='primary')

    # 3. Alter INT → VARCHAR where needed
    #    Check each column first — on fresh databases all are INTEGER;
    #    on incrementally-migrated databases some may already be VARCHAR.
    _alter_int_to_varchar("users", "id")
    _alter_int_to_varchar("user_skills", "user_id")
    _alter_int_to_varchar("runs", "user_id")
    _alter_int_to_varchar("messages", "user_id")

    # 4. Re-create PK on users(id)
    op.create_primary_key('users_pkey', 'users', ['id'])

    # 5. Make username / email nullable; drop UNIQUE on email
    op.alter_column('users', 'username', existing_type=sa.VARCHAR(length=50), nullable=True)
    op.alter_column('users', 'email', existing_type=sa.VARCHAR(length=200), nullable=True)
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.create_index('ix_users_username', 'users', ['username'], unique=False)

    # 6. Create FKs: runs.user_id → users.id, messages.user_id → users.id,
    #    user_skills.user_id → users.id
    op.create_foreign_key(None, 'runs', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'messages', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'user_skills', 'users', ['user_id'], ['id'])


def _get_foreign_keys(inspector, table_name: str) -> set[str]:
    """Return FK constraint names from any table that references *table_name*."""
    fks: set[str] = set()
    # Check each known source table for FKs pointing to our target table
    for src_table in ("runs", "messages", "user_skills"):
        for fk in inspector.get_foreign_keys(src_table) or []:
            if fk.get("referred_table") == table_name:
                name = fk.get("name")
                if name:
                    fks.add(name)
    return fks


def _alter_int_to_varchar(table: str, column: str) -> None:
    """Alter a column from INTEGER to VARCHAR, but only if it's still INT."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"]: c for c in inspector.get_columns(table)}
    col_info = cols.get(column)
    if col_info is None:
        return  # column doesn't exist, nothing to do
    col_type = col_info.get("type")
    if col_type is None:
        return
    # Check if the column type is integer-like
    type_str = str(col_type).upper()
    if "INT" not in type_str and "INTEGER" not in type_str:
        return  # already VARCHAR or other type, skip
    op.alter_column(
        table, column,
        existing_type=sa.INTEGER(),
        type_=sqlmodel.sql.sqltypes.AutoString(length=100),
        existing_nullable=col_info.get("nullable", True),
        postgresql_using=f"{column}::varchar",
    )


def downgrade() -> None:
    """Revert to INT auto-increment PK.  **Destroys non-numeric user_id values.**"""

    # 1. Drop FKs
    op.drop_constraint('user_skills_user_id_fkey', 'user_skills', type_='foreignkey')
    op.drop_constraint('messages_user_id_fkey', 'messages', type_='foreignkey')
    op.drop_constraint('runs_user_id_fkey', 'runs', type_='foreignkey')

    # 2. Drop PK
    op.drop_constraint('users_pkey', 'users', type_='primary')

    # 3. Revert VARCHAR → INT
    op.alter_column('user_skills', 'user_id',
                    existing_type=sqlmodel.sql.sqltypes.AutoString(length=100),
                    type_=sa.INTEGER(),
                    existing_nullable=False,
                    postgresql_using='user_id::integer')
    op.alter_column('users', 'id',
                    existing_type=sqlmodel.sql.sqltypes.AutoString(length=100),
                    type_=sa.INTEGER(),
                    existing_nullable=False,
                    postgresql_using='id::integer')

    # 4. Restore SERIAL default + PK
    op.execute("CREATE SEQUENCE IF NOT EXISTS users_id_seq OWNED BY users.id")
    op.execute("ALTER TABLE users ALTER COLUMN id SET DEFAULT nextval('users_id_seq')")
    op.execute("SELECT setval('users_id_seq', COALESCE((SELECT MAX(id) FROM users), 1))")
    op.create_primary_key('users_pkey', 'users', ['id'])

    # 5. Re-enforce NOT NULL + UNIQUE
    op.alter_column('users', 'email', existing_type=sa.VARCHAR(length=200), nullable=False)
    op.alter_column('users', 'username', existing_type=sa.VARCHAR(length=50), nullable=False)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.drop_index('ix_users_username', table_name='users')
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    # 6. Re-create FKs (runs/messages remain VARCHAR, no need to revert type)
    op.create_foreign_key(None, 'user_skills', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'messages', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'runs', 'users', ['user_id'], ['id'])

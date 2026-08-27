"""add skills table and users role

Revision ID: 311e49d8b58b
Revises: 8f3c2a1b9e47
Create Date: 2026-08-25 09:17:08.706760

Changes:
  - users: add ``role`` VARCHAR(20) NOT NULL DEFAULT 'user'（管理员由运维手动置 'admin'）
  - skills: new table —— 用户创作（自定义）技能的元数据；技能文件本体存 OBS，本表只记录元数据与审核状态
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '311e49d8b58b'
down_revision: str | Sequence[str] | None = '8f3c2a1b9e47'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── users: add role ─────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "role",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default="user",
        ),
    )

    # ── skills table ────────────────────────────────────────────────────
    op.create_table(
        "skills",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=36), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("author_name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("review_status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default="draft"),
        sa.Column("version", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False, server_default="1.0.0"),
        sa.Column("storage_key", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skills_name"), "skills", ["name"], unique=True)
    op.create_index(op.f("ix_skills_author_id"), "skills", ["author_id"], unique=False)
    op.create_foreign_key("skills_author_id_fkey", "skills", "users", ["author_id"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("skills_author_id_fkey", "skills", type_="foreignkey")
    op.drop_index(op.f("ix_skills_author_id"), table_name="skills")
    op.drop_index(op.f("ix_skills_name"), table_name="skills")
    op.drop_table("skills")
    op.drop_column("users", "role")

"""Skill repository — pure database CRUD for the ``skills`` table.

技能文件本体存 OBS，本仓库只读写 ``skills`` 表的元数据（名称、描述、
作者、审核状态等）。归属/使用权由 ``skills.author_id`` 与 ``user_skills``
表表达——文件在 OBS 里单副本共享，不随用户复制。
"""

from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import desc
from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Skill, UserSkill


class SkillRepo:
    """Data access for the ``skills`` table."""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        name: str,
        display_name: str,
        description: str,
        author_id: str,
        author_name: str | None = None,
        review_status: str = "draft",
        version: str = "1.0.0",
        storage_key: str = "",
    ) -> Skill:
        """插入一个新的自定义技能记录，默认 ``review_status='draft'``。"""
        skill = Skill(
            name=name,
            display_name=display_name,
            description=description,
            author_id=author_id,
            author_name=author_name,
            review_status=review_status,
            version=version,
            storage_key=storage_key,
        )
        db.add(skill)
        return skill

    @staticmethod
    async def get_by_name(db: AsyncSession, name: str) -> Skill | None:
        """按 ``name``（全局唯一）查单个技能，不存在返回 ``None``。"""
        result = await db.execute(sa_select(Skill).where(Skill.name == name))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_author(db: AsyncSession, author_id: str) -> list[Skill]:
        """列出某作者创建的全部技能（各状态），最新创建的在前。"""
        result = await db.execute(sa_select(Skill).where(Skill.author_id == author_id).order_by(desc(Skill.created_at)))
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db: AsyncSession,
        name: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
    ) -> None:
        """更新技能的展示名/描述（仅作者，权限判断在 service 层）。

        只在传入字段非 ``None`` 时才覆盖，并刷新 ``updated_at``。
        """
        values: dict = {"updated_at": datetime.now(UTC)}
        if display_name is not None:
            values["display_name"] = display_name
        if description is not None:
            values["description"] = description
        await db.execute(sa_update(Skill).where(Skill.name == name).values(**values))

    @staticmethod
    async def delete(db: AsyncSession, name: str) -> None:
        """按 ``name`` 删除技能记录（OBS 对象删除在 service 层）。"""
        await db.execute(sa_delete(Skill).where(Skill.name == name))

    @staticmethod
    async def list_pending(db: AsyncSession) -> list[Skill]:
        """列出所有待审核的技能（审核队列），最新提交的在前。"""
        result = await db.execute(sa_select(Skill).where(Skill.review_status == "pending").order_by(desc(Skill.created_at)))
        return list(result.scalars().all())

    @staticmethod
    async def list_approved(db: AsyncSession) -> list[Skill]:
        """列出所有审核通过的技能（技能广场），最新通过的在前。"""
        result = await db.execute(sa_select(Skill).where(Skill.review_status == "approved").order_by(desc(Skill.updated_at)))
        return list(result.scalars().all())

    @staticmethod
    async def list_added_by_user(db: AsyncSession, user_id: str) -> list[Skill]:
        """列出某用户已「添加」且审核通过的技能（``user_skills.enabled=True`` 与 ``skills`` 联表）。"""
        stmt = (
            sa_select(Skill)
            .join(UserSkill, UserSkill.skill_name == Skill.name)
            .where(
                UserSkill.user_id == user_id,
                UserSkill.enabled.is_(True),
                Skill.review_status == "approved",
            )
            .order_by(Skill.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def set_review_status(
        db: AsyncSession,
        name: str,
        status: str,
        *,
        review_note: str | None = None,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> None:
        """更新技能审核状态（并写驳回原因 + 审核人/时间），刷新 ``updated_at``。

        ``review_note`` / ``reviewed_by`` / ``reviewed_at`` 在 publish 时传 ``None`` 以清空；
        review 通过/驳回时写入具体值。
        """
        await db.execute(
            sa_update(Skill)
            .where(Skill.name == name)
            .values(
                review_status=status,
                review_note=review_note,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                updated_at=datetime.now(UTC),
            )
        )

    @staticmethod
    async def add_to_user(db: AsyncSession, user_id: str, skill_name: str) -> None:
        """幂等地把技能「添加」到用户（``user_skills`` 已存在则置 ``enabled=True``）。"""
        result = await db.execute(sa_select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.skill_name == skill_name))
        existing = result.scalar_one_or_none()
        if existing is not None:
            if not existing.enabled:
                await db.execute(sa_update(UserSkill).where(UserSkill.id == existing.id).values(enabled=True))
            return
        db.add(UserSkill(user_id=user_id, skill_name=skill_name, enabled=True))

    @staticmethod
    async def remove_from_user(db: AsyncSession, user_id: str, skill_name: str) -> None:
        """取消某用户的「添加」（删除 ``user_skills`` 行）。"""
        await db.execute(sa_delete(UserSkill).where(UserSkill.user_id == user_id, UserSkill.skill_name == skill_name))

    @staticmethod
    async def delete_user_skills_by_skill(db: AsyncSession, skill_name: str) -> None:
        """删除所有引用该技能的 ``user_skills`` 行（作者删技能时清理）。"""
        await db.execute(sa_delete(UserSkill).where(UserSkill.skill_name == skill_name))

    @staticmethod
    async def get_added_names(db: AsyncSession, user_id: str) -> set[str]:
        """返回某用户已启用（``enabled=True``）的技能名集合。"""
        result = await db.execute(sa_select(UserSkill.skill_name).where(UserSkill.user_id == user_id, UserSkill.enabled.is_(True)))
        return set(result.scalars().all())

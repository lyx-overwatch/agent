"""User repository — pure database CRUD for the ``users`` table."""

import uuid

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import User


class UserRepo:
    """Data access for the ``users`` table."""

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        """按 email 查单个用户，不存在返回 ``None``。"""
        result = await db.execute(sa_select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
        """按 id 查单个用户，不存在返回 ``None``。"""
        result = await db.execute(sa_select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        email: str,
        username: str | None,
        hashed_password: str,
    ) -> User:
        """插入一个新用户（``id`` 由 UUID 生成），返回该用户。"""
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            username=username,
            hashed_password=hashed_password,
            is_active=True,
        )
        db.add(user)
        return user

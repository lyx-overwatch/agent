"""Auth service — 邮箱注册 / 登录的业务编排。"""

from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.auth import create_access_token, hash_password, verify_password
from app.models.database import SessionLocal, User
from app.repositories.user_repo import UserRepo


class AuthService:
    """Handle email/password registration and login, issuing a JWT on success."""

    def __init__(self) -> None:
        self._user_repo = UserRepo()

    async def register(self, email: str, password: str) -> dict[str, Any]:
        """注册新用户并签发 access_token。

        Raises:
            409: email 已被注册。
        """
        async with SessionLocal() as db:
            existing = await self._user_repo.get_by_email(db, email)
            if existing is not None:
                raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")

            user = await self._user_repo.create(
                db,
                email=email,
                username=email.split("@", 1)[0],
                hashed_password=hash_password(password),
            )
            await db.commit()

        logger.info("User registered: id={} email={}", user.id, email)
        return self._build_auth_response(user)

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """校验凭证并签发 access_token。

        Raises:
            401: 邮箱不存在或密码错误。
            403: 账号被禁用。
        """
        async with SessionLocal() as db:
            user = await self._user_repo.get_by_email(db, email)
            if user is None or user.hashed_password is None or not verify_password(password, user.hashed_password):
                raise HTTPException(status_code=401, detail="邮箱或密码错误")

            if not user.is_active:
                raise HTTPException(status_code=403, detail="账号已被禁用")

        logger.info("User logged in: id={} email={}", user.id, email)
        return self._build_auth_response(user)

    @staticmethod
    def _build_auth_response(user: User) -> dict[str, Any]:
        token = create_access_token(user.id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "user_id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
            },
        }

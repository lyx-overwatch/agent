"""FastAPI 鉴权依赖 —— 所有业务接口通过 get_current_user 注入当前用户。

get_current_user 只做校验（JWT + 用户是否存在），不负责注册。
用户注册由 ``POST /py/api/auth/verify`` 独立完成，前端在调用业务接口前必须
先调用 verify 接口。

此外，该依赖还会将当前用户绑定到 agent_sdk 的 ContextVar 中
(:func:`agent_sdk.runtime.user_context.set_current_user`)，以便下游的
PathProvider、SandboxProvider 等组件可以拿到用户信息进行文件系统隔离。

ContextVar 生命周期
-------------------
``get_current_user`` 实现了 FastAPI 的 yield-based 依赖协议，请求结束后会
触发 ``finally`` 分支，调用 ``reset_current_user(token)`` 把 ContextVar 恢复
到请求前的状态。这避免了在 FastAPI 复用 asyncio task slot 时，user 身份泄漏
到下一个无关请求。
"""

from collections.abc import AsyncIterator

from agent_sdk.runtime.user_context import reset_current_user, set_current_user
from fastapi import Depends, HTTPException
from loguru import logger
from sqlalchemy import select as sa_select

from app.core.auth import check_is_authenticated
from app.models.database import SessionLocal, User


class _SimpleUser:
    """Lightweight user object satisfying agent_sdk's ``CurrentUser`` Protocol.

    The Protocol only requires an ``.id: str`` attribute; this class
    exists so we can bind user identity to the agent_sdk ContextVar
    without pulling the full SQLModel ``User`` into the SDK layer.
    """

    __slots__ = ("id",)

    def __init__(self, id: str) -> None:
        self.id = id


async def get_current_user(user_id: str = Depends(check_is_authenticated)) -> AsyncIterator[str]:
    """验证 JWT + 用户已注册，返回 user_id 并绑定到 SDK ContextVar。

    仅做校验，不自动注册。前端必须先调 ``POST /py/api/auth/verify`` 完成注册。

    Yields:
        user_id str — 已验证用户标识。

    Raises:
        401: Token 无效 / 缺失 / 用户未注册。

    Note:
        这是 yield-based FastAPI 依赖：请求结束后会进入 ``finally`` 分支，
        调用 ``reset_current_user`` 清掉 ContextVar，防止用户身份在 task
        slot 复用时泄漏到下一个请求。
    """
    async with SessionLocal() as db:
        result = await db.execute(sa_select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if user is None:
        logger.warning("用户 {} 未注册（users 表中无记录），拒绝访问", user_id)
        raise HTTPException(status_code=401, detail=f"用户 {user_id} 未注册，请先调用 /auth/verify")
    if not user.is_active:
        logger.warning("用户 {} 已被禁用，拒绝访问", user_id)
        raise HTTPException(status_code=401, detail=f"用户 {user_id} 已被禁用")

    logger.debug("Authenticated user {}", user.id)

    # Bind user identity to the agent_sdk ContextVar so downstream
    # PathProvider / SandboxProvider calls can derive per-user paths.
    # The yielded ``finally`` cleanup guarantees we don't leak the
    # user identity into a subsequent request that reuses the same
    # asyncio task slot.
    token = set_current_user(_SimpleUser(id=user.id))
    try:
        yield user.id
    finally:
        reset_current_user(token)

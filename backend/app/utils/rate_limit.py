"""基于 Redis 的会话创建限流。

前端 ``sendMessage`` 已有防重入锁，但服务端仍需兜底：同一用户在极短时间内
连续创建会话（前端异常、连点、代理重试等）时，直接 429 拒绝，避免批量产生
一模一样的空会话。

用 Redis ``SET key 1 NX EX window`` 的原子性做「检查并占用」：
并发请求只有一个能拿到锁，其余在窗口期内一律拒绝。
"""

from fastapi import HTTPException
from loguru import logger

from app.core.auth import redis_client
from app.core.config import settings

#: Redis key 前缀，key 形如 ``skillhub:conv_create:{user_id}``
_KEY_PREFIX = "skillhub:conv_create:"


async def check_conversation_create(user_id: str) -> None:
    """若用户在窗口期内已创建过会话则抛出 429，否则占用该窗口。"""
    window = settings.conversation_create_min_interval_seconds
    if window <= 0:
        return

    key = f"{_KEY_PREFIX}{user_id}"
    # NX：仅当 key 不存在时才设置成功（拿到窗口）；返回 None 表示已被占用。
    acquired = await redis_client.set(key, "1", nx=True, ex=window)
    if not acquired:
        logger.warning("用户 {} 创建会话过于频繁，已限流（{}s 窗口）", user_id, window)
        raise HTTPException(
            status_code=429,
            detail="创建会话过于频繁，请稍后再试",
        )

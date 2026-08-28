"""会话创建限流：memory / redis 可切换的抽象。

前端 ``sendMessage`` 已有防重入锁，但服务端仍需兜底：同一用户在极短时间内
连续创建会话（前端异常、连点、代理重试等）时，直接 429 拒绝，避免批量产生
一模一样的空会话。

通过 :func:`get_rate_limiter` 按配置 ``rate_limit_backend`` 选择后端：

- ``memory``：进程内字典 + 固定窗口时间戳，单实例 / 本地开发即可用，零依赖。
- ``redis``：``SET key 1 NX EX window`` 的原子性做「检查并占用」，多副本
  部署下共享窗口；Redis 不可用时（连接失败 / 超时）直接放行。

限流是兜底优化，不应因依赖不可用而阻断会话创建主流程。
"""

import asyncio
import time
from abc import ABC, abstractmethod

from fastapi import HTTPException
from loguru import logger
from redis.exceptions import RedisError

from app.core.auth import redis_client
from app.core.config import settings

#: Redis key 前缀，key 形如 ``skillhub:conv_create:{user_id}``
_KEY_PREFIX = "skillhub:conv_create:"

#: 429 提示文案
_DETAIL = "创建会话过于频繁，请稍后再试"


class RateLimiter(ABC):
    """会话创建限流后端抽象。"""

    @abstractmethod
    async def check_conversation_create(self, user_id: str) -> None:
        """窗口内重复创建则抛 429，否则占用该窗口。"""


class MemoryRateLimiter(RateLimiter):
    """进程内固定窗口限流：``{user_id: 上次窗口起点}``。

    仅适用于单实例部署；多副本 / 负载均衡下各进程窗口不共享，需改用 Redis 后端。
    """

    def __init__(self) -> None:
        self._windows: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check_conversation_create(self, user_id: str) -> None:
        window = settings.conversation_create_min_interval_seconds
        if window <= 0:
            return
        now = time.monotonic()
        async with self._lock:
            last = self._windows.get(user_id)
            if last is not None and now - last < window:
                logger.warning("用户 {} 创建会话过于频繁，已限流（{}s 窗口）", user_id, window)
                raise HTTPException(status_code=429, detail=_DETAIL)
            self._windows[user_id] = now
            self._prune(now, window)

    def _prune(self, now: float, window: float) -> None:
        """长期运行避免内存无限增长：每积累 1000 条清理一次已过期项。"""
        if len(self._windows) >= 1000:
            for key, ts in list(self._windows.items()):
                if now - ts >= window:
                    del self._windows[key]


class RedisRateLimiter(RateLimiter):
    """Redis 固定窗口限流：``SET key 1 NX EX window``。

    多副本部署下共享窗口；Redis 不可用时（未启动 / 连接失败 / 超时）直接放行。
    """

    async def check_conversation_create(self, user_id: str) -> None:
        window = settings.conversation_create_min_interval_seconds
        if window <= 0:
            return
        key = f"{_KEY_PREFIX}{user_id}"
        # NX：仅当 key 不存在时才设置成功（拿到窗口）；返回 None 表示已被占用。
        try:
            acquired = await redis_client.set(key, "1", nx=True, ex=window)
        except RedisError as exc:
            # Redis 不可用——限流是兜底优化，直接放行。
            logger.warning("Redis 不可用，跳过会话创建限流（放行）: {}", exc)
            return
        if not acquired:
            logger.warning("用户 {} 创建会话过于频繁，已限流（{}s 窗口）", user_id, window)
            raise HTTPException(status_code=429, detail=_DETAIL)


_limiter: RateLimiter | None = None


def _build_rate_limiter() -> RateLimiter:
    backend = settings.rate_limit_backend.lower()
    if backend == "redis":
        return RedisRateLimiter()
    if backend == "memory":
        return MemoryRateLimiter()
    logger.warning("未知限流 backend '{}'，回退到 memory", settings.rate_limit_backend)
    return MemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    """返回按配置选择的限流后端单例（懒初始化）。"""
    global _limiter
    if _limiter is None:
        _limiter = _build_rate_limiter()
    return _limiter


async def check_conversation_create(user_id: str) -> None:
    """会话创建限流入口：委派给配置选择的限流后端。"""
    await get_rate_limiter().check_conversation_create(user_id)

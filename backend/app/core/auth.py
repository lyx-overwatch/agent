"""JWT 验证 —— 对应 Java 端 HMAC512 (HS512) 签发的 token 格式。

Java 端 token 结构:
    Header:  {"alg": "HS512", "typ": "JWT"}
    Claims:  {"login_user_key": "<userId>", "timestamp": <epochMillis>}
    (无 exp 过期时间)

Python 端只做验证，不再自行签发 token。

Token 仅通过 Header ``Authorization: Bearer <token>`` 传递。
"""

import warnings

import jwt
import redis.asyncio as redis
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from app.core.config import settings

# 抑制 PyJWT key 长度不足的警告。
# 当前 SECRET_KEY 为 32 bytes，HS512 建议 64 bytes。
# Key 由上游 Java 系统签发，长度不在 Python 端控制范围内。
warnings.filterwarnings("ignore", category=jwt.InsecureKeyLengthWarning)

redis_client = redis.from_url(settings.redis_url)


async def check_is_authenticated(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> str:
    """验证 JWT Token 并校验 Redis 登录态，返回 user_id。

    Token 必须通过 ``Authorization: Bearer <token>`` Header 传递。

    Raises:
        401: Token 缺失 / 无效 / 格式错误 / Redis 会话过期。
    """
    token = credentials.credentials

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT 解码失败: {}", exc)
        raise HTTPException(status_code=401, detail=f"Token 无效: {exc}")

    user_id: str | None = payload.get(settings.login_user_key)
    if not user_id:
        logger.warning("Token 缺少 {} 字段", settings.login_user_key)
        raise HTTPException(status_code=401, detail="Token 无效: 缺少 login_user_key")

    exists = await redis_client.exists(f"login_tokens:{user_id}")
    if not exists:
        logger.warning("Redis 登录态缺失: user_id={}", user_id)
        raise HTTPException(
            status_code=401,
            detail="Redis 无登录态，请先在主系统登录",
        )

    logger.debug("认证成功: user_id={}", user_id)
    return user_id

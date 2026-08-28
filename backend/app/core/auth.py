"""JWT 验证与签发 —— HS512 对称签名，与 Java 端 HMAC512 (HS512) 的 token 格式兼容。

Java 端 token 结构:
    Header:  {"alg": "HS512", "typ": "JWT"}
    Claims:  {"login_user_key": "<userId>", "timestamp": <epochMillis>}
    (无 exp 过期时间)

Python 端既可验证 Java 签发的 token，也可为「邮箱登录」用户自行签发 token
（claim 同为 ``login_user_key``，签名用同一 ``SECRET_KEY``），保证 ``get_current_user``
无需区分来源即可识别。邮箱登录不再依赖 Redis 登录态——JWT 本身即凭证。

Token 仅通过 Header ``Authorization: Bearer <token>`` 传递。
"""

import warnings
from datetime import UTC, datetime, timedelta

import bcrypt
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

# 供 rate_limit 等非鉴权场景复用（Redis 仅用于限流，不再参与登录态校验）。
redis_client = redis.from_url(settings.redis_url)


def hash_password(password: str) -> str:
    """用 bcrypt 对明文密码做哈希，返回可直接落库的字符串。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码与 bcrypt 哈希是否匹配（哈希非法时返回 False）。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    """为邮箱登录用户签发 HS512 JWT，claim 结构与 Java 端一致。"""
    now = datetime.now(UTC)
    payload = {
        settings.login_user_key: user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


async def check_is_authenticated(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> str:
    """验证 JWT Token 并返回 user_id。

    Token 必须通过 ``Authorization: Bearer <token>`` Header 传递。

    Raises:
        401: Token 缺失 / 无效 / 格式错误。
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

    logger.debug("认证成功: user_id={}", user_id)
    return user_id

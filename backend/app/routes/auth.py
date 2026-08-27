"""Auth endpoints —— token 校验 + 用户注册。

前端在调用任何业务接口之前，必须先调 ``POST /py/api/auth/verify``：
  1. 验证 Java 签发的 JWT (HS512)
  2. 校验 Redis 登录态
  3. 首次调用自动在本地 users 表注册（已注册则跳过）
  4. 返回 user_id 和注册状态
"""

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel

from app.core.auth import check_is_authenticated
from app.models.database import SessionLocal, get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])


class VerifyResponse(BaseModel):
    user_id: str
    is_new_user: bool  # 是否本次新注册
    role: str  # "user" | "admin"，前端据此决定是否展示审核入口


@router.post("/verify", response_model=VerifyResponse)
async def verify_token(user_id: str = Depends(check_is_authenticated)):
    """校验 Token 并自动注册用户。

    前端在调用任何业务接口之前必须先调此接口。
    首次调用时自动在 users 表注册，再次调用时跳过注册直接返回。
    """
    async with SessionLocal() as db:
        user, is_new = await get_or_create_user(db, user_id)
        await db.commit()

    logger.info("User {} verified (new={})", user.id, is_new)
    return VerifyResponse(user_id=user.id, is_new_user=is_new, role=user.role)

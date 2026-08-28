"""Auth endpoints —— 邮箱注册 / 登录 / token 校验。

前端在调用任何业务接口之前，先通过「邮箱注册」或「邮箱登录」拿到 access_token，
存入 localStorage，之后所有请求带上 ``Authorization: Bearer <token>``。

``POST /auth/verify`` 仍保留：校验 token 并（首次）自动注册，返回 user_id / role，
供前端在启动时确认身份与角色。
"""

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel

from app.core.auth import check_is_authenticated
from app.models.database import SessionLocal, get_or_create_user
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


class VerifyResponse(BaseModel):
    user_id: str
    is_new_user: bool  # 是否本次新注册
    role: str  # "user" | "admin"，前端据此决定是否展示审核入口


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest):
    """邮箱注册：创建用户并签发 access_token。"""
    svc = AuthService()
    return await svc.register(body.email, body.password)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    """邮箱登录：校验凭证并签发 access_token。"""
    svc = AuthService()
    return await svc.login(body.email, body.password)


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

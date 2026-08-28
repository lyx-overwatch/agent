"""Auth schemas —— 邮箱注册 / 登录。"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        n = len(v.encode("utf-8"))
        if n < 8:
            raise ValueError("密码至少 8 位")
        if n > 72:
            raise ValueError("密码过长（最多 72 字节）")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v


class AuthUser(BaseModel):
    user_id: str
    email: str | None
    username: str | None
    role: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser

"""Skill schemas — request/response models for skill management + marketplace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── 上传 ──────────────────────────────────────────────────────────────


class SkillUploadResponse(BaseModel):
    skill_name: str
    display_name: str
    review_status: str


# ── 技能条目表示 ──────────────────────────────────────────────────────


class BuiltinSkillItem(BaseModel):
    name: str
    description: str


class SkillItem(BaseModel):
    """自定义技能条目（「我的技能」列表 / 技能广场）。"""

    name: str
    display_name: str
    description: str
    author_id: str | None = None
    author_name: str | None = None
    review_status: str | None = None
    review_note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    version: str | None = None
    created_at: str | None = None
    added: bool = False  # 当前用户是否已添加（仅广场列表有意义）


class AvailableSkillItem(BaseModel):
    """当前用户可用技能集中的一项，``origin`` 标记来源。"""

    name: str
    display_name: str | None = None
    description: str
    origin: Literal["builtin", "mine", "added"]
    review_status: str | None = None
    review_note: str | None = None
    version: str | None = None


# ── 请求体 ────────────────────────────────────────────────────────────


class SkillUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1024)


class SkillReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)  # reject 时的驳回原因（approve 忽略）

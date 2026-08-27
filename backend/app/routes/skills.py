"""Skill endpoints — upload, manage, publish, review, marketplace, availability.

⚠️ 路由注册顺序：``/builtin``、``/mine``、``/marketplace``、``/available`` 等
静态段必须先于 ``/{name}`` 注册，否则会被 ``{name}`` 捕获成技能名。
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.dependencies import get_current_user
from app.schemas.skill import (
    AvailableSkillItem,
    BuiltinSkillItem,
    SkillItem,
    SkillReviewRequest,
    SkillUpdateRequest,
    SkillUploadResponse,
)
from app.services.skill_service import SkillService

router = APIRouter(prefix="/skills", tags=["skills"])


@router.post("", response_model=SkillUploadResponse, status_code=201)
async def upload_skill(
    file: UploadFile = File(...),
    display_name: str | None = Form(None),
    description: str | None = Form(None),
    user_id: str = Depends(get_current_user),
):
    """上传 .zip/.skill 压缩包或 .md 单文件 → 安装到 OBS → 落库为 draft。"""
    content = await file.read()
    svc = SkillService()
    result = await svc.upload(user_id, file.filename or "", content, display_name, description)
    return SkillUploadResponse(**result)


@router.get("", response_model=list[BuiltinSkillItem])
async def list_skills_alias(user_id: str = Depends(get_current_user)):
    """内置技能列表（向后兼容别名，等价于 GET /skills/builtin）。"""
    svc = SkillService()
    result = await svc.list_builtin()
    return result["skills"]


@router.get("/builtin", response_model=list[BuiltinSkillItem])
async def list_builtin(user_id: str = Depends(get_current_user)):
    """官方内置技能（只读列表）。"""
    svc = SkillService()
    result = await svc.list_builtin()
    return result["skills"]


@router.get("/mine", response_model=list[SkillItem])
async def list_mine(user_id: str = Depends(get_current_user)):
    """我创建的技能（各状态）。"""
    svc = SkillService()
    result = await svc.list_mine(user_id)
    return result["skills"]


@router.get("/marketplace", response_model=list[SkillItem])
async def list_marketplace(user_id: str = Depends(get_current_user)):
    """技能广场：所有审核通过的技能，附带「是否已添加」。"""
    svc = SkillService()
    result = await svc.list_marketplace(user_id)
    return result["skills"]


@router.get("/pending", response_model=list[SkillItem])
async def list_pending(user_id: str = Depends(get_current_user)):
    """待审核技能队列（仅管理员）。"""
    svc = SkillService()
    result = await svc.list_pending(user_id)
    return result["skills"]


@router.get("/available", response_model=list[AvailableSkillItem])
async def list_available(user_id: str = Depends(get_current_user)):
    """当前用户可用技能全量（内置 + 我的 + 已添加）。"""
    svc = SkillService()
    result = await svc.list_available(user_id)
    return result["skills"]


@router.put("/{name}")
async def update_skill(
    name: str,
    body: SkillUpdateRequest,
    user_id: str = Depends(get_current_user),
):
    """更新技能展示名/描述（仅作者）。"""
    svc = SkillService()
    return await svc.update_skill(user_id, name, body.display_name, body.description)


@router.delete("/{name}")
async def delete_skill(name: str, user_id: str = Depends(get_current_user)):
    """删除技能（仅作者）。"""
    svc = SkillService()
    return await svc.delete_skill(user_id, name)


@router.post("/{name}/publish")
async def publish_skill(name: str, user_id: str = Depends(get_current_user)):
    """发布技能（仅作者）：draft → pending。"""
    svc = SkillService()
    return await svc.publish_skill(user_id, name)


@router.post("/{name}/add")
async def add_skill(name: str, user_id: str = Depends(get_current_user)):
    """添加广场技能到当前用户。"""
    svc = SkillService()
    return await svc.add_skill(user_id, name)


@router.delete("/{name}/add")
async def remove_added_skill(name: str, user_id: str = Depends(get_current_user)):
    """取消添加。"""
    svc = SkillService()
    return await svc.remove_added_skill(user_id, name)


@router.post("/{name}/review")
async def review_skill(
    name: str,
    body: SkillReviewRequest,
    user_id: str = Depends(get_current_user),
):
    """管理员审核：pending → approved / rejected。"""
    svc = SkillService()
    return await svc.review_skill(user_id, name, body.action, body.reason)

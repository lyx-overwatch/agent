"""Skill service — upload, publish, review, add, and the marketplace.

上传流程（云端 agent 定位）：``.zip`` 归档、``.md`` 单文件、或 ``.skill``
（按内容嗅探）→ frontmatter 校验 + LLM 安全扫描 → 逐文件上传到 OBS →
写 ``skills`` 表（``draft``）。技能文件本体永不落容器本地磁盘。
"""

from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_sdk.skills import load_skills
from agent_sdk.skills.installer import (
    MultiSkillArchiveError,
    SkillSecurityScanError,
    StagedSkill,
    astage_skill_archive,
    astage_skill_markdown,
)
from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select as sa_select

from app.core.agent import get_skills_dir
from app.core.storage import get_storage
from app.models.database import SessionLocal, Skill, User
from app.repositories.skill_repo import SkillRepo
from app.services.skill_security_scanner import get_scanner
from app.utils.skill_i18n import localize_skill_description

#: OBS 对象 key 前缀，自定义技能文件单副本存于此。
_CUSTOM_SKILL_PREFIX = "skills/custom"

#: 明确按 zip 归档解析的扩展名。
_ZIP_SUFFIXES = (".zip",)

#: 明确按「单文件 Markdown」解析的扩展名。
_MARKDOWN_SUFFIXES = (".md",)

#: 需内容嗅探的扩展名：.skill 非标准格式，可能是 zip 也可能是 Markdown。
_SNIFF_SUFFIXES = (".skill",)


def _prepare_markdown(content: bytes) -> str:
    """校验 .md 正文必须包含 YAML frontmatter（name + description），并返回文本。"""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="上传的 .md 文件必须是 UTF-8 编码文本") from exc

    if not text.lstrip().startswith("---"):
        raise HTTPException(
            status_code=400,
            detail="上传的 .md 文件必须包含 YAML frontmatter（以 --- 开头），并提供 name 与 description 字段",
        )
    return text


def _is_zip(content: bytes) -> bool:
    """按内容判断是否为 zip 归档（不依赖扩展名，供 .skill 嗅探用）。"""
    return zipfile.is_zipfile(io.BytesIO(content))


class SkillService:
    """Manage user-created skills, the marketplace, and per-user availability."""

    def __init__(self) -> None:
        self._skill_repo = SkillRepo()

    # ── 上传 ──────────────────────────────────────────────────────────

    async def upload(
        self,
        user_id: str,
        filename: str,
        content: bytes,
        display_name: str | None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """上传并安装一个技能到 OBS，落库为 ``draft``。

        支持 ``.zip``（归档）、``.md``（单文件 Markdown，必须自带 frontmatter），
        以及 ``.skill``（非标准格式，按内容嗅探：是 zip 则走归档解析，
        否则按 Markdown 处理）。``display_name`` / ``description`` 可选覆盖，
        缺省时分别取 frontmatter 的 name / description。
        """
        resolved_display = (display_name or "").strip()
        if len(resolved_display) > 200:
            raise HTTPException(status_code=400, detail="display_name 过长（最多 200 字符）")

        resolved_description = (description or "").strip()
        if len(resolved_description) > 1024:
            raise HTTPException(status_code=400, detail="description 过长（最多 1024 字符）")
        if "<" in resolved_description or ">" in resolved_description:
            raise HTTPException(status_code=400, detail="description 不能包含尖括号（< 或 >）")

        lower = filename.lower()
        staged: StagedSkill | None = None
        try:
            if lower.endswith(_ZIP_SUFFIXES):
                staged = await self._stage_archive(content)
            elif lower.endswith(_MARKDOWN_SUFFIXES):
                staged = await self._stage_markdown(content)
            elif lower.endswith(_SNIFF_SUFFIXES):
                # .skill 非标准格式：按内容嗅探，zip 走归档，否则按 Markdown
                if _is_zip(content):
                    staged = await self._stage_archive(content)
                else:
                    staged = await self._stage_markdown(content)
            else:
                raise HTTPException(status_code=400, detail="只支持上传 .zip / .skill / .md 文件")

            async with SessionLocal() as db:
                existing = await self._skill_repo.get_by_name(db, staged.name)
            if existing is not None:
                raise HTTPException(status_code=409, detail=f"技能 '{staged.name}' 已存在")

            storage = get_storage()
            try:
                for rel, abs_path in staged.files:
                    key = f"{_CUSTOM_SKILL_PREFIX}/{staged.name}/{rel}"
                    await storage.upload(local_path=abs_path, key=key)
            except Exception as exc:  # noqa: BLE001 — 回滚后转 500
                try:
                    await storage.delete_prefix(f"{_CUSTOM_SKILL_PREFIX}/{staged.name}")
                except Exception:
                    logger.exception("回滚技能 {} 的 OBS 对象失败", staged.name)
                logger.exception("技能 {} 上传 OBS 失败", staged.name)
                raise HTTPException(status_code=500, detail=f"上传存储失败: {exc}") from exc

            final_display = resolved_display or staged.name
            final_description = resolved_description or staged.description
            async with SessionLocal() as db:
                author_name = await self._resolve_author_name(db, user_id)
                await self._skill_repo.create(
                    db,
                    name=staged.name,
                    display_name=final_display,
                    description=final_description,
                    author_id=user_id,
                    author_name=author_name,
                    review_status="draft",
                    version=staged.version,
                    storage_key=f"{_CUSTOM_SKILL_PREFIX}/{staged.name}",
                )
                await db.commit()

            logger.info("用户 {} 上传技能 {} (draft)", user_id, staged.name)
            return {
                "skill_name": staged.name,
                "display_name": final_display,
                "review_status": "draft",
            }
        finally:
            if staged is not None:
                shutil.rmtree(staged.root, ignore_errors=True)

    async def _stage_archive(self, content: bytes) -> StagedSkill:
        """解包 zip 归档 → 校验 + 安全扫描，返回 StagedSkill。"""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf.write(content)
            tmp_zip = tf.name
        try:
            try:
                return await astage_skill_archive(tmp_zip, scan_content=get_scanner().scan_content)
            except SkillSecurityScanError as exc:
                raise HTTPException(status_code=422, detail=f"安全扫描未通过: {exc}") from exc
            except MultiSkillArchiveError as exc:
                names = "、".join(exc.skill_names)
                raise HTTPException(
                    status_code=400,
                    detail=f"检测到多个技能被打包在同一个归档里（{names}）。一个归档只能包含一个技能，请将每个技能单独打包后分别上传。",
                ) from exc
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            try:
                Path(tmp_zip).unlink(missing_ok=True)
            except OSError:
                pass

    async def _stage_markdown(self, content: bytes) -> StagedSkill:
        """把单个 Markdown 文件当作 SKILL.md → 校验 + 安全扫描，返回 StagedSkill。"""
        text = _prepare_markdown(content)
        try:
            return await astage_skill_markdown(text, scan_content=get_scanner().scan_content)
        except SkillSecurityScanError as exc:
            raise HTTPException(status_code=422, detail=f"安全扫描未通过: {exc}") from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ── 我的技能 ──────────────────────────────────────────────────────

    async def list_mine(self, user_id: str) -> dict[str, Any]:
        """列出当前用户创建的全部技能（各状态）。"""
        async with SessionLocal() as db:
            skills = await self._skill_repo.list_by_author(db, user_id)
        return {"skills": [self._to_item(s) for s in skills]}

    async def update_skill(
        self,
        user_id: str,
        name: str,
        display_name: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        """更新技能展示名/描述（仅作者）。"""
        async with SessionLocal() as db:
            await self._get_owned(db, user_id, name)
            await self._skill_repo.update(db, name, display_name=display_name, description=description)
            await db.commit()
            updated = await self._skill_repo.get_by_name(db, name)
        return {
            "skill_name": name,
            "display_name": updated.display_name if updated else None,
            "description": updated.description if updated else None,
        }

    async def delete_skill(self, user_id: str, name: str) -> dict[str, Any]:
        """删除技能（仅作者）：删 OBS 对象 + 删记录 + 清引用。"""
        async with SessionLocal() as db:
            skill = await self._get_owned(db, user_id, name)
            storage_key = skill.storage_key or f"{_CUSTOM_SKILL_PREFIX}/{name}"
            await self._skill_repo.delete_user_skills_by_skill(db, name)
            await self._skill_repo.delete(db, name)
            await db.commit()

        try:
            await get_storage().delete_prefix(storage_key)
        except Exception:
            logger.exception("删除技能 {} 的 OBS 对象失败: {}", name)

        logger.info("用户 {} 删除技能 {}", user_id, name)
        return {"skill_name": name, "deleted": True}

    async def publish_skill(self, user_id: str, name: str) -> dict[str, Any]:
        """发布/重新提交技能（仅作者）：``draft`` 或 ``rejected → pending``。"""
        async with SessionLocal() as db:
            skill = await self._get_owned(db, user_id, name)
            if skill.review_status not in ("draft", "rejected"):
                raise HTTPException(
                    status_code=409,
                    detail=f"只有 draft 或 rejected 状态的技能可以发布（当前: {skill.review_status}）",
                )
            # 重新提交时清空旧的驳回原因
            await self._skill_repo.set_review_status(db, name, "pending")
            await db.commit()
        return {"skill_name": name, "review_status": "pending"}

    # ── 广场 / 添加 ───────────────────────────────────────────────────

    async def list_builtin(self) -> dict[str, Any]:
        """官方内置技能（只读列表，来自容器文件系统 ``skills/``）。"""
        skills = load_skills(get_skills_dir())
        return {"skills": [{"name": s.name, "description": localize_skill_description(s.name, s.description)} for s in skills]}

    async def list_marketplace(self, user_id: str) -> dict[str, Any]:
        """技能广场：所有 ``approved`` 的自定义技能，附带「是否已添加」。"""
        async with SessionLocal() as db:
            skills = await self._skill_repo.list_approved(db)
            added_names = await self._skill_repo.get_added_names(db, user_id)
        return {"skills": [self._to_item(s, added=s.name in added_names) for s in skills]}

    async def add_skill(self, user_id: str, name: str) -> dict[str, Any]:
        """添加广场技能到当前用户（仅 ``approved`` 有效）。"""
        async with SessionLocal() as db:
            skill = await self._skill_repo.get_by_name(db, name)
            if skill is None:
                raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
            if skill.review_status != "approved":
                raise HTTPException(
                    status_code=409,
                    detail=f"只有已审核通过的技能可以添加（当前: {skill.review_status}）",
                )
            await self._skill_repo.add_to_user(db, user_id, name)
            await db.commit()
        return {"skill_name": name, "added": True}

    async def remove_added_skill(self, user_id: str, name: str) -> dict[str, Any]:
        """取消添加。"""
        async with SessionLocal() as db:
            await self._skill_repo.remove_from_user(db, user_id, name)
            await db.commit()
        return {"skill_name": name, "added": False}

    async def list_available(self, user_id: str) -> dict[str, Any]:
        """当前用户可用技能全量（内置 + 我的 + 已添加），带 ``origin`` 来源标记。"""
        builtin = await self.list_builtin()
        async with SessionLocal() as db:
            mine = await self._skill_repo.list_by_author(db, user_id)
            added = await self._skill_repo.list_added_by_user(db, user_id)

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for s in builtin["skills"]:
            items.append(
                {
                    "name": s["name"],
                    "display_name": s["name"],
                    "description": s["description"],
                    "origin": "builtin",
                    "review_status": None,
                    "version": None,
                }
            )
            seen.add(s["name"])
        for s in mine:
            items.append(
                {
                    "name": s.name,
                    "display_name": s.display_name,
                    "description": s.description,
                    "origin": "mine",
                    "review_status": s.review_status,
                    "review_note": s.review_note,
                    "version": s.version,
                }
            )
            seen.add(s.name)
        for s in added:
            if s.name in seen:
                continue  # 已按 builtin / mine 计入，避免重复
            items.append(
                {
                    "name": s.name,
                    "display_name": s.display_name,
                    "description": s.description,
                    "origin": "added",
                    "review_status": s.review_status,
                    "version": s.version,
                }
            )
        return {"skills": items}

    # ── 审核（管理员） ────────────────────────────────────────────────

    async def list_pending(self, user_id: str) -> dict[str, Any]:
        """待审核技能队列（仅管理员）。"""
        await self._require_admin(user_id)
        async with SessionLocal() as db:
            skills = await self._skill_repo.list_pending(db)
        return {"skills": [self._to_item(s) for s in skills]}

    async def review_skill(self, user_id: str, name: str, action: str, reason: str | None = None) -> dict[str, Any]:
        """管理员审核：``pending → approved / rejected``，reject 时记录驳回原因。"""
        await self._require_admin(user_id)
        new_status = "approved" if action == "approve" else "rejected"
        note = (reason or "").strip() if action == "reject" else None
        if action == "reject" and not note:
            raise HTTPException(status_code=422, detail="驳回时必须填写原因")
        async with SessionLocal() as db:
            skill = await self._skill_repo.get_by_name(db, name)
            if skill is None:
                raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
            if skill.review_status != "pending":
                raise HTTPException(
                    status_code=409,
                    detail=f"只有 pending 状态的技能可以审核（当前: {skill.review_status}）",
                )
            await self._skill_repo.set_review_status(db, name, new_status, review_note=note, reviewed_by=user_id, reviewed_at=datetime.now(UTC))
            await db.commit()
        return {"skill_name": name, "review_status": new_status, "review_note": note}

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _resolve_author_name(db, user_id: str) -> str:
        """取用户显示名（username），缺失时回退 user_id。"""
        result = await db.execute(sa_select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is not None and user.username:
            return user.username
        return user_id

    @staticmethod
    def _to_item(skill: Skill, *, added: bool = False) -> dict[str, Any]:
        return {
            "name": skill.name,
            "display_name": skill.display_name,
            "description": skill.description,
            "author_id": skill.author_id,
            "author_name": skill.author_name,
            "review_status": skill.review_status,
            "review_note": skill.review_note,
            "reviewed_by": skill.reviewed_by,
            "reviewed_at": skill.reviewed_at.isoformat() if skill.reviewed_at else None,
            "version": skill.version,
            "created_at": skill.created_at.isoformat() if skill.created_at else None,
            "added": added,
        }

    async def _get_owned(self, db, user_id: str, name: str) -> Skill:
        """取技能并校验存在性 + 作者身份，失败抛 404/403。"""
        skill = await self._skill_repo.get_by_name(db, name)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
        if skill.author_id != user_id:
            raise HTTPException(status_code=403, detail="只有作者可以操作此技能")
        return skill

    @staticmethod
    async def _require_admin(user_id: str) -> None:
        async with SessionLocal() as db:
            result = await db.execute(sa_select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
        if user is None or user.role != "admin":
            raise HTTPException(status_code=403, detail="仅管理员可执行此操作")

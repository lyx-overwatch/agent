"""Agent 层技能可用性桥接 —— 把 SDK 工具与 DB/OBS 数据源对接起来。

PR3 接线：``agent_sdk.skills.tools.make_skill_tools`` 接受三个异步回调，
本模块提供它们的 app 层实现，供 :func:`app.core.agent._build_agent` 注入：

* :func:`is_available` —— 判断某自定义技能是否对当前用户可用
* :func:`fetch_skill_files` —— 从 OBS 拉取某自定义技能的全部文件
* :func:`list_personal_skills` —— 列出当前用户的个人技能（我的 + 已添加）

用户身份来自 SDK 的 ``agent_sdk.runtime.user_context``（由
``app.core.dependencies.get_current_user`` 在每个请求里写入 ContextVar），
因此这些回调在 agent 工具执行时无需额外传参即可拿到当前 userId。

⚠️ 依赖方向：本模块**不能**导入 ``app.core.agent``（会造成循环导入），
也不导入 ``app.services.skill_service``（它间接依赖 ``app.core.agent``）。
这里直接用 ``config_loader``/``storage``/``skill_repo`` 等底层模块。
"""

from __future__ import annotations

from agent_sdk.runtime.user_context import DEFAULT_USER_ID, get_effective_user_id
from loguru import logger

from app.core.storage import get_storage
from app.models.database import SessionLocal
from app.repositories.skill_repo import SkillRepo

#: OBS 对象 key 前缀（与 ``skill_service._CUSTOM_SKILL_PREFIX`` 保持一致，
#: 但此处不复用该常量以免引入对 ``app.core.agent`` 的间接依赖）。
_CUSTOM_SKILL_PREFIX = "skills/custom"


async def is_available(name: str) -> bool:
    """判断名为 *name* 的自定义技能是否对当前用户可用。

    SDK 的 ``read_skill`` 会**先**从文件系统解析内置技能，只有内置技能里
    找不到的名字才会走到这里——因此本函数只处理 OBS 里的自定义技能。

    可用规则：
    * 作者本人 → 任意状态（draft/pending/approved/rejected）均可用；
    * 非作者 → 仅当技能已 ``approved`` 且当前用户已「添加」它时可用。

    未认证上下文（``user_id == "default"``）→ 一律不可用（避免越权读取）。
    """
    user_id = get_effective_user_id()
    if user_id == DEFAULT_USER_ID:
        return False

    try:
        async with SessionLocal() as db:
            skill = await SkillRepo.get_by_name(db, name)
            if skill is None:
                return False
            if skill.author_id == user_id:
                return True
            if skill.review_status != "approved":
                return False
            added_names = await SkillRepo.get_added_names(db, user_id)
            return name in added_names
    except Exception:
        logger.exception("is_available({!r}) 查询失败，按不可用处理", name)
        return False


async def fetch_skill_files(name: str) -> list[tuple[str, bytes]]:
    """从 OBS 拉取名为 *name* 的自定义技能的**全部**文件。

    返回 ``(rel_path, bytes)`` 列表，``rel_path`` 相对技能根（如
    ``SKILL.md``、``scripts/run.py``）。目录占位对象（``key`` 以 ``/``
    结尾）被跳过。
    """
    storage = get_storage()
    prefix = f"{_CUSTOM_SKILL_PREFIX}/{name}/"
    files: list[tuple[str, bytes]] = []
    for obj in await storage.list_objects(prefix):
        key: str = obj["key"]
        if key.endswith("/"):
            continue
        rel = key[len(prefix) :]
        if not rel:
            continue
        data = await storage.download_bytes(key)
        files.append((rel, data))
    return files


async def list_personal_skills() -> list[tuple[str, str]]:
    """列出当前用户的个人技能（自己创建的 + 已添加且已审核通过的）。

    返回 ``(name, description)`` 列表，按名称去重；内置技能**不**在此列
    （它们已由 ``SkillsMiddleware`` 注入系统提示的 ``<available_skills>``）。
    """
    user_id = get_effective_user_id()
    if user_id == DEFAULT_USER_ID:
        return []

    try:
        async with SessionLocal() as db:
            mine = await SkillRepo.list_by_author(db, user_id)
            added = await SkillRepo.list_added_by_user(db, user_id)
    except Exception:
        logger.exception("list_personal_skills() 查询失败")
        return []

    # 去重：自己的技能优先；已添加的若与「我的」同名则忽略。
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for skill in [*mine, *added]:
        if skill.name in seen:
            continue
        seen.add(skill.name)
        result.append((skill.name, skill.description or ""))
    return result

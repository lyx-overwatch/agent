"""Agent runtime singleton — powered by agent-sdk + config.yaml.

通过 :func:`load_agent_config` 从 config.yaml 读取全部配置，
再经由 agent_sdk 的 :func:`create_agent` 组装运行时而非硬编码。

提供 :func:`get_agent` / :func:`get_skills_dir` / :func:`init_agent`
/ :func:`shutdown_agent` 供路由和 FastAPI lifespan 使用。
"""

from __future__ import annotations

from pathlib import Path

from agent_sdk import create_agent
from agent_sdk.community.jina_ai.tools import web_fetch_tool
from agent_sdk.community.skillhub import SubagentRunner
from agent_sdk.community.vision.tools import make_view_image_tool
from agent_sdk.community.web_search.tools import web_search
from agent_sdk.mcp import get_mcp_tools
from agent_sdk.sandbox import SandboxPathResolver, make_sandbox_tools
from agent_sdk.skills.tools import make_skill_tools
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer
from loguru import logger

from app.core.config_loader import get_agent_config

# ── Available sub-agents block builder ─────────────────────────────────────


def _build_available_subagents_block(registry) -> str:
    """Build the ``<available_subagents>`` system-prompt block dynamically.

    Reads the registered subagent types and their descriptions from
    *registry* so the parent agent always sees an up-to-date list
    without hardcoded role names in the system prompt.
    """
    names = registry.list_names()
    if not names:
        return ""

    lines = ["<available_subagents>"]
    for name in names:
        definition = registry.get(name)
        if definition is None:
            continue
        # Take the first line of the description as a one-line summary.
        desc = definition.description.strip().split("\n")[0]
        lines.append(f"- **{name}**: {desc}")
    lines.append("</available_subagents>")
    return "\n".join(lines)


# ── Module-level agent pool ────────────────────────────────────────────────
# Lazy-cached: default model agents are created at startup; others are built
# on first use.  Keyed by (model_name, thinking_enabled).
_agents: dict[tuple[str, bool], CompiledStateGraph] = {}
_default_model_name: str = ""
_supports_thinking: bool = False
_mcp_tools: list[BaseTool] = []
_checkpointer: Checkpointer | None = None


def _build_agent(
    checkpointer: Checkpointer | None = None,
    thinking_enabled: bool = False,
    model_name: str = "",
    mcp_tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """从 config.yaml 组装 agent 运行时（sandbox + skills + checkpointer + MCP）。

    Args:
        checkpointer: LangGraph checkpointer 实例。
        thinking_enabled: 是否启用深度思考模式。
        model_name: 模型名称（来自 config.yaml models[].name）。
        mcp_tools: 预加载的 MCP 工具列表。
    """
    cfg = get_agent_config()

    # ── 模型 ──────────────────────────────────────────────────────────
    model = cfg.create_model(name=model_name, thinking_enabled=thinking_enabled)

    # ── Sandbox 工具 ──────────────────────────────────────────────────
    resolver = SandboxPathResolver(cfg.sandbox_config)
    sandbox_bundle = make_sandbox_tools(
        sandbox_provider=cfg.sandbox_provider,
        resolver=resolver,
        host_bash_policy=cfg.host_bash_policy,
    )
    sandbox_tools = [
        sandbox_bundle.bash,
        sandbox_bundle.ls,
        sandbox_bundle.glob,
        sandbox_bundle.grep,
        sandbox_bundle.read_file,
        sandbox_bundle.write_file,
        sandbox_bundle.str_replace,
    ]

    # ── Skill 工具 ────────────────────────────────────────────────────
    # 始终注入 app 层回调：内置技能走文件系统，个人/已添加技能走 OBS。
    # SDK 的回调参数为 None 时回退到「仅内置技能」的旧行为（单测/独立运行）。
    # 延迟导入以打破 app.core.agent ↔ app.services 的循环依赖：chat_service
    # 反向依赖 agent，因此不能在模块顶层 import services。
    from app.services.skill_availability import fetch_skill_files, is_available, list_personal_skills

    skill_tools = make_skill_tools(
        skills_path=cfg.skills_path,
        sandbox_provider=cfg.sandbox_provider,
        is_available=is_available,
        fetch_skill_files=fetch_skill_files,
        list_personal_skills=list_personal_skills,
    )

    # ── 外部工具 ──────────────────────────────────────────────────────
    external_tools = [
        web_search,
        web_fetch_tool,
    ]

    # ── 图像理解工具 ──────────────────────────────────────────────────
    # 用独立的多模态模型理解图片内容，返回文字描述给主模型；
    # 主模型保持纯文本，不注入 base64。
    vision_model = cfg.create_vision_model()
    if vision_model is not None:
        external_tools.append(make_view_image_tool(resolver, vision_model, sandbox_provider=cfg.sandbox_provider))

    # ── 系统提示 ──────────────────────────────────────────────────────
    # ⚠️  DeepSeek Disk Cache: 修改此 system prompt 会导致硬盘上下文缓存
    #     全部失效，所有用户的首次请求将重新走冷启动（~5K tokens 全价）。
    #     每次修改后建议重启服务并等待缓存预热完成。

    # ── 动态子代理列表 ──────────────────────────────────────────────
    available_subagents_block = _build_available_subagents_block(cfg.subagent_registry)

    system_prompt = (
        "You are Heyu Agent, an AI assistant with access to a sandbox environment.\n\n"
        "<rules>\n"
        "- Stop on failure: if a tool fails due to missing deps (API keys, env vars, "
        "unavailable services), STOP after 2 attempts and tell the user what is missing. "
        "Do not try endless workarounds.\n"
        "- Clarify first: if the request misses critical info (file paths, params, "
        "credentials), ask BEFORE acting.\n"
        "- Always provide a visible text response after thinking.\n"
        "- Keep using the same language as the user.\n"
        "- All user-facing files go to /mnt/user-data/outputs/, NOT workspace.\n"
        "  workspace is for intermediate scratch files only.\n"
        "- Images: to understand an uploaded image, call view_image(image_path=...). "
        "It uses a multimodal model and returns a description. Never install OCR "
        "libraries (tesseract / pytesseract) or write image-to-text scripts to read "
        "an image.\n"
        "</rules>\n\n"
        "<execution_strategy>\n"
        "- Delegate, don't inline: for tasks expected to require more than 5 tool-call "
        "steps, delegate to a subagent via the task tool. The parent agent's context "
        "is limited — keep it clean for planning and synthesis.\n"
        "- See <available_subagents> below for which subagent types to use. "
        "Match the task to the right subagent type based on its description.\n"
        "- After creating files or delegating a subagent, present results to the user "
        "BEFORE doing additional work. Do NOT chain creation → testing → debugging "
        "in one go unless the user explicitly asked for it.\n"
        "- Do NOT run end-to-end tests, generate sample data, or verify outputs unless "
        "the user explicitly asked you to.\n"
        "- Skill files: `read_skill` is the ONLY tool that can access skill content. "
        "Never use `ls`, `glob`, `grep`, or `read_file` to explore or read skill files "
        "— those tools cannot see the skills directory.  When a SKILL.md references "
        "supporting files, use `read_skill('<name>', file='path/to/file')` to read "
        "them, or `read_skill('<name>', file='subdir/')` to list a subdirectory.\n"
        "- Personal skills: built-in skills are listed in <available_skills> above. "
        "To discover the user's personal skills (ones they created, or marketplace "
        "skills they added), call `list_skills`.  Load any of them with "
        "`read_skill('<name>')` exactly like a built-in skill.\n"
        "- Skill resource injection: when a skill contains binary files (.docx, .pptx, "
        "images, etc.) and you read a supporting file via `read_skill('<name>', "
        "file='...')`, ALL files from that skill are automatically injected into the "
        "sandbox at `.skills/<name>/`.  After injection, you can execute scripts "
        "(`bash .skills/<name>/scripts/...`) and reference templates directly "
        "from that path.  The `read_skill` return value confirms injection.\n"
        "- Environment issues: if a dependency is missing (pip, pandas, etc.), try "
        "at most 2 approaches, then report the problem to the user.\n"
        "</execution_strategy>\n\n" + available_subagents_block + "\n"
        "<workspace>\n"
        "Work dir (rw): /mnt/user-data/workspace/ — for intermediate files, scripts, and scratch work.\n"
        "Outputs (rw): /mnt/user-data/outputs/ — REQUIRED for all user-facing deliverables.\n"
        "  After writing any file the user should receive (documents, reports, spreadsheets,\n"
        "  code files, images, etc.), place it HERE — not in workspace.\n"
        "  用户可在文件树面板中预览 outputs 和 workspace 中的所有文件。\n"
        "Skills (host): use `read_skill('<name>')` to load SKILL.md; "
        "`read_skill('<name>', file='path/...')` for supporting files; "
        "`read_skill('<name>', file='dir/')` to list a subdirectory.\n"
        "</workspace>\n\n"
        "You can run shell/Python commands (bash), read/write/edit files, "
        "navigate the filesystem (ls/glob/grep), and delegate subtasks to subagents (task). "
        "Use the available tools directly — do not claim you cannot perform an action "
        "without first trying the appropriate tool."
    )

    # ── MCP 工具提示 ─────────────────────────────────────────────────
    mcp_hint = ""
    if mcp_tools:
        mcp_prefixes = sorted({t.name.split("_")[0] for t in mcp_tools})
        mcp_hint = (
            "\n\n<mcp_tools>\n"
            "The following MCP tool groups are available: " + ", ".join(mcp_prefixes) + ". "
            "Use these tools directly for their specific domains "
            "(e.g. playwright_* for browser automation, screenshots, web scraping). "
            "Do NOT try to install browsers or automation libraries in the sandbox — "
            "use the MCP tools instead.\n"
            "</mcp_tools>"
        )

    _all_tools = sandbox_tools + skill_tools + external_tools + (mcp_tools or [])

    # ── 子代理 ──────────────────────────────────────────────────────
    # Inject the registry and a real runner into middleware_deps so the
    # ``task`` tool is functional (vs the no-op fallback).
    cfg.middleware_deps.subagent_registry = cfg.subagent_registry
    cfg.middleware_deps.run_subagent = SubagentRunner(
        model,
        _all_tools,
        sandbox_provider=cfg.sandbox_provider,
        timeout_seconds=900,
    )

    # ── 组装 ──────────────────────────────────────────────────────────
    agent = create_agent(
        model=model,
        tools=_all_tools,
        system_prompt=system_prompt + mcp_hint,
        features=cfg.features,
        middleware_deps=cfg.middleware_deps,
        checkpointer=checkpointer,
        name="skillhub",
    )
    return agent


async def init_agent(checkpointer: Checkpointer | None = None) -> CompiledStateGraph:
    """初始化 agent 池（FastAPI lifespan 调用）。

    只预建**默认模型**的 agent 实例（thinking + non-thinking）；
    其余模型的 agent 在首次请求时懒加载。

    MCP 工具在启动时一次性加载，所有 agent 实例共享。

    Args:
        checkpointer: LangGraph checkpointer 实例。

    Returns:
        默认模型的 non-thinking agent 实例，供 cache warm-up 使用。
    """
    global _agents, _default_model_name, _supports_thinking, _mcp_tools, _checkpointer
    cfg = get_agent_config()

    if not cfg.model_configs:
        raise ValueError("config.yaml 中没有定义 models")

    _default_model_name = cfg.model_configs[0].name
    _supports_thinking = any(m.supports_thinking for m in cfg.model_configs)
    _checkpointer = checkpointer

    # ── 加载 MCP 工具（一次性，所有实例共享）───────────────────────
    _mcp_tools = await get_mcp_tools(cfg.mcp_servers_config)
    if _mcp_tools:
        logger.info("Loaded {} MCP tool(s): {}", len(_mcp_tools), [t.name for t in _mcp_tools])

    # ── 仅预建默认模型的 agent 实例 ──────────────────────────────
    model_config = cfg.model_configs[0]
    model_name = model_config.name
    for thinking_enabled in (False, True):
        if thinking_enabled and not model_config.supports_thinking:
            continue
        key = (model_name, thinking_enabled)
        logger.info("Creating agent: model={}, thinking={} (default, pre-built)", model_name, thinking_enabled)
        _agents[key] = _build_agent(
            checkpointer=checkpointer,
            thinking_enabled=thinking_enabled,
            model_name=model_name,
            mcp_tools=_mcp_tools,
        )

    return _agents[(_default_model_name, False)]


def shutdown_agent() -> None:
    """关闭 agent 运行时，释放资源。"""
    global _agents, _default_model_name, _supports_thinking, _mcp_tools, _checkpointer
    _agents.clear()
    _default_model_name = ""
    _supports_thinking = False
    _mcp_tools.clear()
    _checkpointer = None


def get_agent(*, thinking_enabled: bool = True, model_name: str | None = None) -> CompiledStateGraph:
    """返回编译好的 agent 实例。需先调用 :func:`init_agent`。

    默认模型（config.yaml 第一个）在启动时预建；其他模型首次请求时
    懒构建并缓存。

    Args:
        thinking_enabled: 是否启用深度思考。仅当模型支持时生效。
        model_name: 模型名称（config.yaml models[].name）。``None`` 时
                    使用默认模型。

    Raises:
        RuntimeError: 尚未调用 ``init_agent()`` 或请求的模型不支持 thinking。
    """
    if not _agents:
        raise RuntimeError("Agent not initialized. Call init_agent() first.")

    # ── 模型名验证 / 回退 ──────────────────────────────────────────
    cfg = get_agent_config()
    resolved_name = model_name or _default_model_name
    if not any(m.name == resolved_name for m in cfg.model_configs):
        logger.warning(
            "Model {!r} not found in config; falling back to default model {!r}.",
            resolved_name,
            _default_model_name,
        )
        resolved_name = _default_model_name

    model_config = next(m for m in cfg.model_configs if m.name == resolved_name)

    # ── 思考锁 ─────────────────────────────────────────────────────
    # Kimi K2.7 等模型不支持关闭深度思考（API 会拒绝 thinking.type=disabled）。
    # 无论请求传 thinking_enabled=False 都强制开启，避免命中 400。
    if model_config.thinking_locked and not thinking_enabled:
        logger.info(
            "Model {} thinking is locked on; forcing thinking_enabled=True",
            resolved_name,
        )
        thinking_enabled = True

    # ── 池查找 + 懒构建 ──────────────────────────────────────────
    key = (resolved_name, thinking_enabled)
    agent = _agents.get(key)
    if agent is not None:
        return agent

    # Lazy build — this model wasn't pre-built at startup (not the default)
    if thinking_enabled and not model_config.supports_thinking:
        # This model doesn't support thinking; fall back to non-thinking
        key_no_thinking = (resolved_name, False)
        agent = _agents.get(key_no_thinking)
        if agent is not None:
            return agent
        # Build non-thinking variant
        logger.info(
            "Lazy-creating agent: model={}, thinking=False (thinking not supported)",
            resolved_name,
        )
        _agents[key_no_thinking] = _build_agent(
            checkpointer=_checkpointer,
            thinking_enabled=False,
            model_name=resolved_name,
            mcp_tools=_mcp_tools,
        )
        return _agents[key_no_thinking]

    logger.info("Lazy-creating agent: model={}, thinking={}", resolved_name, thinking_enabled)
    _agents[key] = _build_agent(
        checkpointer=_checkpointer,
        thinking_enabled=thinking_enabled,
        model_name=resolved_name,
        mcp_tools=_mcp_tools,
    )
    return _agents[key]


def get_skills_dir() -> Path:
    """返回 skills 目录路径。"""
    cfg = get_agent_config()
    if cfg.skills_path:
        return cfg.skills_path
    # 回退到 config.py 的 settings.skills_dir
    from app.core.config import settings

    return settings.skills_dir.resolve()

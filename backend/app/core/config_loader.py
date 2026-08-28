"""Heyu Agent 配置加载器 — config.yaml → agent_sdk 对象的桥接层。

将 YAML 声明式配置翻译为 agent_sdk 的编程式对象:
- ``models`` → :class:`ModelConfig` + :func:`create_chat_model`
- ``sandbox`` → :class:`SandboxProvider` + :class:`SandboxToolsConfig`
- ``skills`` → :class:`MiddlewareChainConfig.skills_path`
- ``checkpointer`` → :class:`CheckpointerConfig`
- ``memory`` / ``summarization`` / ``title`` / ``subagents`` →
  :class:`RuntimeFeatures` + :class:`MiddlewareChainConfig`

使用方式::

    from app.core.config_loader import load_agent_config

    cfg = load_agent_config()
    model = cfg.create_model()
    agent = create_agent(model=model, features=cfg.features, middleware_deps=cfg.middleware_deps, ...)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from agent_sdk.mcp.config import McpServersConfig, config_from_extensions_dict
from agent_sdk.models.factory import ModelConfig, create_chat_model
from agent_sdk.runtime.checkpointer.config import CheckpointerConfig
from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import MiddlewareChainConfig
from agent_sdk.sandbox import (
    DefaultAuditRules,
    SandboxToolsConfig,
)
from agent_sdk.subagents.default import DefaultSubagentRegistry
from dotenv import load_dotenv
from loguru import logger

# ---------------------------------------------------------------------------
# 与 agent_sdk ModelConfig 的 known fields 对照
# ---------------------------------------------------------------------------
# 这些字段属于 agent_sdk.ModelConfig 的元数据，不传给模型构造函数。
# 其余所有字段都会被放入 model_settings。
_MODEL_META_FIELDS: set[str] = {
    "name",
    "use",
    "display_name",
    "description",
    "supports_thinking",
    "thinking_locked",
    "supports_reasoning_effort",
    "supports_vision",
    "when_thinking_enabled",
    "when_thinking_disabled",
    "thinking",
}


# ---------------------------------------------------------------------------
# 配置加载结果
# ---------------------------------------------------------------------------


@dataclass
class AgentConfig:
    """config.yaml → agent_sdk 的完整翻译结果。

    包含组装一个 agent 所需的全部对象:
    - model_configs: 所有模型声明
    - features: 功能开关
    - middleware_deps: 功能中间件运行时依赖
    - checkpointer_cfg: 持久化后端配置
    - sandbox_config: sandbox 工具参数
    - sandbox_provider: sandbox 后端实例
    - path_provider: 路径提供者
    - skills_path: 技能定义根目录
    - system_prompt: 自定义系统提示词
    - mcp_servers_config: MCP 服务器配置
    - subagent_registry: 子代理注册表
    """

    model_configs: list[ModelConfig] = field(default_factory=list)
    vision_model_config: ModelConfig | None = None
    features: RuntimeFeatures = field(default_factory=RuntimeFeatures)
    middleware_deps: MiddlewareChainConfig = field(default_factory=MiddlewareChainConfig)
    checkpointer_cfg: CheckpointerConfig = field(default_factory=CheckpointerConfig)
    sandbox_config: SandboxToolsConfig = field(default_factory=SandboxToolsConfig)
    sandbox_provider: Any = None
    host_bash_policy: Any = None
    path_provider: Any = None
    skills_path: Path | None = None
    system_prompt: str | None = None
    mcp_servers_config: McpServersConfig = field(default_factory=McpServersConfig)
    subagent_registry: DefaultSubagentRegistry = field(default_factory=DefaultSubagentRegistry)

    def create_model(self, name: str | None = None, thinking_enabled: bool = False):
        """从配置创建模型实例。

        Args:
            name: 模型名，None 则使用第一个模型。
            thinking_enabled: 是否启用 thinking 模式。

        Returns:
            BaseChatModel 实例。
        """
        if not self.model_configs:
            raise ValueError("config.yaml 中没有定义 models")
        target = name or self.model_configs[0].name
        config = next((m for m in self.model_configs if m.name == target), None)
        if config is None:
            raise ValueError(f"模型 {target!r} 未在 config.yaml 中定义")
        return create_chat_model(config, thinking_enabled=thinking_enabled)

    def create_vision_model(self):
        """创建用于图像理解的多模态模型实例（thinking 关闭）。

        Returns:
            BaseChatModel 实例；若未配置 vision 模型则返回 None。
        """
        if self.vision_model_config is None:
            return None
        return create_chat_model(self.vision_model_config, thinking_enabled=False)

    def create_title_model(self):
        """创建用于后台标题生成的模型实例。

        TitleMiddleware 已移除，标题改为后台异步生成（见
        ``app/services/chat/title_service.py``）。此工厂仍由
        ``config.yaml`` 的 ``title.enabled`` 驱动 —— 关闭该开关时
        返回 None，标题生成即被跳过。

        Returns:
            BaseChatModel 实例；若未启用标题则返回 None。
        """
        if self.middleware_deps.title_model_factory is None:
            return None
        return self.middleware_deps.title_model_factory()


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def load_agent_config(config_path: str | None = None) -> AgentConfig:
    """加载 config.yaml 并返回 :class:`AgentConfig`。

    路径优先级:
    1. 参数 ``config_path``
    2. 环境变量 ``SKILLHUB_CONFIG_PATH``
    3. 默认 ``{backend}/config.yaml``

    Raises:
        FileNotFoundError: 找不到 config.yaml。
    """
    resolved = _resolve_config_path(config_path)
    logger.info("加载配置: {}", resolved)

    # 先加载 .env 到 os.environ，确保 $VAR 引用能解析
    load_dotenv()

    with open(resolved, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 解析环境变量引用 ($VAR)
    raw = _resolve_env_vars(raw)

    result = AgentConfig()

    # ── 1. 模型 ──────────────────────────────────────────────────────
    result.model_configs = _load_models(raw.get("models", []))
    result.vision_model_config = _resolve_vision_model(raw.get("vision", {}), result.model_configs)

    # ── 2. Skills ────────────────────────────────────────────────────
    result.skills_path = _resolve_skills_path(raw.get("skills", {}))

    # ── 3. Sandbox ───────────────────────────────────────────────────
    result.sandbox_provider = _build_sandbox_provider(raw.get("sandbox", {}))
    result.sandbox_config = _load_sandbox_config(raw.get("sandbox", {}))
    result.host_bash_policy = _build_host_bash_policy(raw.get("sandbox", {}))
    result.path_provider = _build_path_provider(raw.get("sandbox", {}))

    # ── 3.5 MCP Servers ─────────────────────────────────────────────
    result.mcp_servers_config = config_from_extensions_dict(raw)

    # ── 4. Features ──────────────────────────────────────────────────
    result.features = _load_features(raw)

    # ── 4.5. Subagent registry ───────────────────────────────────────
    # Build the role registry from Heyu Agent built-ins + optional custom
    # roles defined in config.yaml → subagents.roles.  Custom roles that
    # match a built-in name are registered as overrides (replace the
    # built-in definition).
    result.subagent_registry = _build_subagent_registry(raw.get("subagents", {}))

    # ── 5. MiddlewareChainConfig ─────────────────────────────────────
    result.middleware_deps = _load_middleware_deps(
        raw=raw,
        path_provider=result.path_provider,
        sandbox_provider=result.sandbox_provider,
        skills_path=result.skills_path,
        model_configs=result.model_configs,
    )

    # ── 6. Checkpointer ──────────────────────────────────────────────
    result.checkpointer_cfg = _load_checkpointer_config(raw.get("checkpointer", {}))

    return result


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------


def _resolve_config_path(config_path: str | None) -> Path:
    """解析 config.yaml 文件路径。"""
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        return path

    if env_path := os.getenv("SKILLHUB_CONFIG_PATH"):
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(f"SKILLHUB_CONFIG_PATH 指定的配置文件不存在: {path}")
        return path

    default = Path(__file__).resolve().parents[2] / "config.yaml"
    if default.exists():
        return default

    raise FileNotFoundError("找不到 config.yaml。请将 config.yaml 放在 backend/ 目录下，或通过 SKILLHUB_CONFIG_PATH 环境变量指定路径。")


def _resolve_env_vars(config: Any) -> Any:
    """递归解析配置中的 $VAR 环境变量引用。

    Supports both standalone (``"$VAR"``) and inline
    (``"Bearer $TOKEN"``) references.  Unset variables are
    preserved as-is with a logged warning.
    """
    import re

    if isinstance(config, str):
        # Standalone reference: "$VAR" → env value
        if config.startswith("$") and re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", config):
            var_name = config[1:]
            value = os.getenv(var_name)
            if value is None:
                logger.warning("环境变量 {} 未设置，config 中引用了 {}，保留原值", var_name, config)
                return config
            return value

        # Inline references: "Bearer $TOKEN" → "Bearer <value>"
        def _replace(m: re.Match) -> str:
            var_name = m.group(1)
            value = os.getenv(var_name)
            if value is None:
                logger.warning("环境变量 {} 未设置，config 中引用了 ${}，保留原值", var_name, var_name)
                return m.group(0)
            return value

        return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", _replace, config)
    if isinstance(config, dict):
        return {k: _resolve_env_vars(v) for k, v in config.items()}
    if isinstance(config, list):
        return [_resolve_env_vars(item) for item in config]
    return config


# ── 模型加载 ────────────────────────────────────────────────────────────────


def _load_models(raw_models: list[dict]) -> list[ModelConfig]:
    """将 YAML 模型列表转换为 agent_sdk ModelConfig 列表。

    自动分离元数据字段和模型构造函数参数:
    - name / use / display_name / supports_thinking 等 → ModelConfig 字段
    - model / api_base / api_key / timeout 等 → model_settings
    """
    result: list[ModelConfig] = []
    for entry in raw_models:
        meta: dict[str, Any] = {}
        settings: dict[str, Any] = {}

        for key, value in entry.items():
            if key in _MODEL_META_FIELDS:
                meta[key] = value
            else:
                settings[key] = value

        # 确保 model 字段被正确传递
        # agent_sdk ModelConfig 的 extra="allow" 也会保留 model，但 model_settings
        # 是 agent_sdk 传给模型构造函数的唯一途径
        cfg = ModelConfig(
            name=meta.get("name", ""),
            use=meta.get("use", ""),
            display_name=meta.get("display_name"),
            description=meta.get("description"),
            supports_thinking=meta.get("supports_thinking", False),
            thinking_locked=meta.get("thinking_locked", False),
            supports_reasoning_effort=meta.get("supports_reasoning_effort", False),
            supports_vision=meta.get("supports_vision", False),
            when_thinking_enabled=meta.get("when_thinking_enabled"),
            when_thinking_disabled=meta.get("when_thinking_disabled"),
            thinking=meta.get("thinking"),
            model_settings=settings,
        )
        result.append(cfg)
    return result


#: 图像理解默认使用的多模态模型名（引用 models[].name）。
_DEFAULT_VISION_MODEL = "glm-5.2"


def _resolve_vision_model(vision_cfg: dict, model_configs: list[ModelConfig]) -> ModelConfig | None:
    """解析图像理解用的多模态模型配置。

    优先取 ``vision.model`` 指定的模型名，未配置时回退到
    :data:`_DEFAULT_VISION_MODEL`；两者都未命中则退到第一个声明
    ``supports_vision`` 的模型。找不到任何可用模型返回 None（此时
    ``view_image`` 工具不会被装配）。
    """
    if not model_configs:
        return None

    name = vision_cfg.get("model") or _DEFAULT_VISION_MODEL
    for model in model_configs:
        if model.name == name:
            return model

    for model in model_configs:
        if model.supports_vision:
            logger.warning("vision.model {!r} 未在 models 中定义，回退到 {}", name, model.name)
            return model

    logger.warning("未找到支持 vision 的模型，view_image 工具不可用")
    return None


# ── Sandbox ──────────────────────────────────────────────────────────────────


def _build_sandbox_provider(sandbox: dict) -> Any:
    """根据 sandbox.provider 构建 SandboxProvider 实例。

    provider 取值:
    - "local"  → LocalSandboxProvider
    - "docker" → AioSandboxProvider（失败则抛异常）
    - "auto"   → 优先 Docker，不可用时回退 local

    sandbox.image 可指定自定义镜像（仅 docker / auto 生效），
    不配置则使用 SDK 内置默认镜像。
    """
    import subprocess

    from agent_sdk.community.aio_sandbox import AioSandboxProvider
    from agent_sdk.sandbox.local import LocalSandboxProvider

    workspace = Path(sandbox.get("workspace", "../agent-test"))
    sandbox_image = sandbox.get("image")  # None → 使用 SDK 默认镜像

    mode = sandbox.get("provider", "auto").lower()

    if mode == "local":
        logger.info("Sandbox provider: local (explicit)")
        return LocalSandboxProvider(workspace=workspace)

    if mode == "docker":
        aio_kwargs: dict[str, Any] = _aio_sandbox_kwargs(workspace, sandbox)
        if sandbox_image:
            aio_kwargs["image"] = sandbox_image
            logger.info("Sandbox provider: docker (explicit, image={})", sandbox_image)
        else:
            logger.info("Sandbox provider: docker (explicit)")
        return AioSandboxProvider(**aio_kwargs)

    # auto: 尝试 Docker
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
        aio_kwargs = _aio_sandbox_kwargs(workspace, sandbox)
        if sandbox_image:
            aio_kwargs["image"] = sandbox_image
            logger.info("Sandbox provider: docker (auto-detected, image={})", sandbox_image)
        else:
            logger.info("Sandbox provider: docker (auto-detected)")
        return AioSandboxProvider(**aio_kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        logger.info("Sandbox provider: local (fallback — Docker not available)")
        return LocalSandboxProvider(workspace=workspace)


def _aio_sandbox_kwargs(workspace: Path | str, sandbox: dict) -> dict[str, Any]:
    """Build the kwargs dict for :class:`AioSandboxProvider`.

    Pulls ``SKILLHUB_HOST_BASE_DIR`` from the environment to translate
    the container-side ``thread_base_dir`` into a host-side path that
    Docker can bind-mount (DooD deployment).

    Reads ``provisioner_url`` from the sandbox config section to switch
    between local Docker backend and remote K8s provisioner backend.

    Injects the remote storage backend so the provider can restore
    workspace files when a fresh sandbox Pod is created (K8s mode).
    """
    kwargs: dict[str, Any] = {"thread_base_dir": workspace}
    host_base = os.environ.get("SKILLHUB_HOST_BASE_DIR")
    if host_base:
        kwargs["host_base_dir"] = host_base

    # ── Sandbox readiness timeout ────────────────────────────────────
    # K8s Pod creation (scheduling + image pull + startup + readiness
    # probe) can take 2+ minutes in production.  Let operators tune
    # this via config.yaml → sandbox.readiness_timeout (in seconds).
    readiness_timeout = sandbox.get("readiness_timeout")
    if readiness_timeout is not None:
        kwargs["readiness_timeout"] = int(readiness_timeout)

    # ── K8s provisioner ──────────────────────────────────────────────
    provisioner_url = sandbox.get("provisioner_url", "")
    if not provisioner_url:
        provisioner_url = os.environ.get("PROVISIONER_URL", "")
    if provisioner_url:
        kwargs["provisioner_url"] = provisioner_url
        logger.info("AioSandboxProvider: using remote provisioner at {}", provisioner_url)

        # ── Resident pool (常驻 Pod 池) ──────────────────────────────
        # >0 时启用池化复用：backend 复用固定的常驻沙箱 Pod，消除每次冷启动
        # 拉镜像的 1–2 分钟等待。仅 K8s provisioner 模式生效。
        pool_cfg = sandbox.get("pool") or {}
        pool_size = int(pool_cfg.get("size", 0))
        if pool_size > 0:
            kwargs["pool_size"] = pool_size
            kwargs["pool_lease_timeout"] = int(pool_cfg.get("lease_timeout", 60))
            logger.info("AioSandboxProvider: resident pool enabled (size={}, lease_timeout={}s)", pool_size, kwargs["pool_lease_timeout"])

        # ── Inject storage backend for workspace restore ─────────────
        # Only relevant in K8s mode — local Docker uses bind-mounts.
        from app.core.storage import LocalStorageBackend, get_storage

        storage = get_storage()
        if not isinstance(storage, LocalStorageBackend):
            kwargs["storage"] = storage
            logger.info("AioSandboxProvider: storage backend injected for workspace restore")

    return kwargs


def _load_sandbox_config(sandbox: dict) -> SandboxToolsConfig:
    """从 YAML sandbox 段构建 SandboxToolsConfig。"""
    return SandboxToolsConfig(
        virtual_path_prefix="/mnt/user-data",
        bash_output_max_chars=sandbox.get("bash_output_max_chars", 50000),
        read_file_output_max_chars=sandbox.get("read_file_output_max_chars", 50000),
    )


def _build_host_bash_policy(sandbox: dict):
    """从 YAML sandbox.allow_host_bash 构建 HostBashPolicy。

    默认 false（安全），开发环境建议设为 true。
    仅对 LocalSandboxProvider 生效。
    """
    from agent_sdk.sandbox.security import LOCAL_HOST_BASH_DISABLED_MESSAGE, ConfigurableHostBashPolicy

    allow = sandbox.get("allow_host_bash", False)
    logger.info("Host bash policy: {}", "allowed" if allow else "denied")
    return ConfigurableHostBashPolicy(
        allow_fn=lambda: allow,
        disabled_message=LOCAL_HOST_BASH_DISABLED_MESSAGE,
    )


def _build_path_provider(sandbox: dict) -> Any:
    """构建 PathProvider，默认使用 agent_sdk 的 DefaultPathProvider。"""
    from agent_sdk.paths import DefaultPathProvider

    workspace = sandbox.get("workspace", "../agent-test")
    return DefaultPathProvider(base_dir=Path(workspace))


# ── Skills ───────────────────────────────────────────────────────────────────


def _resolve_skills_path(skills: dict) -> Path | None:
    """解析 skills 目录路径。"""
    raw_path = skills.get("path", "../skills")
    path = Path(raw_path)
    if not path.is_absolute():
        # 相对于 backend/ 目录
        path = (Path(__file__).resolve().parents[2] / path).resolve()
    return path if path.exists() else None


# ── Features ─────────────────────────────────────────────────────────────────


def _load_features(raw: dict) -> RuntimeFeatures:
    """从 YAML 各段的 enabled 字段构建 RuntimeFeatures。"""
    return RuntimeFeatures(
        sandbox=True,
        skills=_get_bool(raw, "skills", "path") is not None,
        memory=_get_bool(raw, "memory", "enabled", False),
        summarization=_get_bool(raw, "summarization", "enabled", False),
        # TitleMiddleware 已移除：标题改为后台异步生成（title_service.py），
        # 不再在 agent 回合内同步调用标题模型。auto_title 强制关闭，
        # 以免 middleware_chain 又把 TitleMiddleware 挂回执行链。
        auto_title=False,
        subagent=_get_bool(raw, "subagents", "enabled", False),
    )


def _build_subagent_registry(subagents_cfg: dict) -> DefaultSubagentRegistry:
    """构建 Heyu Agent 子代理注册表（内建角色 + 可选的 YAML 自定义角色）。

    config.yaml 中的 ``subagents.roles`` 映射是可选的。
    内建角色始终可用（由 ``build_skillhub_registry`` 定义）；
    YAML 中的自定义角色会追加到注册表中，与内建角色同名的
    自定义角色会覆盖内建定义。
    """
    from agent_sdk.community.skillhub import build_skillhub_registry

    roles_cfg = subagents_cfg.get("roles")
    if isinstance(roles_cfg, dict) and roles_cfg:
        registry = build_skillhub_registry(custom_roles=roles_cfg)
        names = registry.list_names()
        logger.info(
            "加载 {} 个自定义子代理角色，当前注册表共 {} 个角色: {}",
            len(roles_cfg),
            len(names),
            ", ".join(names),
        )
        return registry

    registry = build_skillhub_registry()
    names = registry.list_names()
    logger.info("使用 Heyu Agent 内建子代理角色 ({})", ", ".join(names))
    return registry


def _get_bool(raw: dict, section: str, key: str, default: bool = False) -> bool:
    """安全地从嵌套字典中读取 bool 值。"""
    sec = raw.get(section)
    if isinstance(sec, dict):
        return bool(sec.get(key, default))
    if sec is not None:
        return True
    return default


# ── MiddlewareChainConfig ────────────────────────────────────────────────────


def _load_middleware_deps(
    raw: dict,
    path_provider: Any,
    sandbox_provider: Any,
    skills_path: Path | None,
    model_configs: list[ModelConfig],
) -> MiddlewareChainConfig:
    """构建 MiddlewareChainConfig，注入所有功能中间件运行时依赖。"""
    memory_cfg = raw.get("memory", {})

    # ── summarization_model ──────────────────────────────────────────
    summarization_model = None
    summarization_max_tokens = None
    summarization_keep_messages = None
    if _get_bool(raw, "summarization", "enabled", False) and model_configs:
        summarization_model = create_chat_model(model_configs[0])
        # 打标签以区分摘要模型和主模型的事件，流式端点据此过滤
        summarization_model = summarization_model.with_config(tags=["middleware:summarize"])
        summarization_cfg = raw.get("summarization", {})
        summarization_max_tokens = summarization_cfg.get("trigger_tokens")
        summarization_keep_messages = summarization_cfg.get("keep_messages")

    # ── memory_storage ───────────────────────────────────────────────
    memory_storage = None
    memory_schema_cls = None
    if _get_bool(raw, "memory", "enabled", False):
        from agent_sdk.memory import DefaultMemorySchema, FileMemoryStorage

        storage_path = memory_cfg.get("storage_path", "memory.json")
        memory_schema_cls = DefaultMemorySchema
        memory_storage = FileMemoryStorage(Path(storage_path), memory_schema_cls)

    # ── title（后台异步生成） ─────────────────────────────────────────
    title_model_factory = None
    title_prompts = None
    if _get_bool(raw, "title", "enabled", False) and model_configs:
        from agent_sdk.middlewares.title import TitlePrompts

        title_cfg = raw.get("title", {})
        _title_model = create_chat_model(model_configs[0])

        def _title_model_factory():
            return _title_model

        title_model_factory = _title_model_factory
        title_prompts = TitlePrompts(
            max_words=title_cfg.get("max_words", 8),
            max_chars=title_cfg.get("max_chars", 80),
            fallback_max_chars=title_cfg.get("fallback_max_chars", 50),
        )

    return MiddlewareChainConfig(
        path_provider=path_provider,
        sandbox_provider=sandbox_provider,
        audit_rules=DefaultAuditRules(),
        skills_path=str(skills_path) if skills_path else None,
        summarization_model=summarization_model,
        summarization_max_tokens=summarization_max_tokens,
        summarization_keep_messages=summarization_keep_messages,
        memory_storage=memory_storage,
        memory_schema_cls=memory_schema_cls,
        title_model_factory=title_model_factory,
        title_prompts=title_prompts,
    )


# ── Checkpointer ─────────────────────────────────────────────────────────────


def _load_checkpointer_config(raw_cfg: dict) -> CheckpointerConfig:
    """从 YAML checkpointer 段构建 CheckpointerConfig。"""
    return CheckpointerConfig(
        type=raw_cfg.get("type", "memory"),
        connection_string=raw_cfg.get("connection_string"),
    )


# ---------------------------------------------------------------------------
# 向后兼容：保留旧 .env 驱动的 Settings 可用
# ---------------------------------------------------------------------------
# 如果 config.yaml 中没有指定模型，则回退到 .env 中的 MODEL_ID 等配置。
# 这确保现有的 .env 配置方式仍然可用。

_AGENT_CONFIG: AgentConfig | None = None


def get_agent_config() -> AgentConfig:
    """获取缓存的 AgentConfig 单例。"""
    global _AGENT_CONFIG
    if _AGENT_CONFIG is None:
        _AGENT_CONFIG = load_agent_config()
    return _AGENT_CONFIG


def reload_agent_config(config_path: str | None = None) -> AgentConfig:
    """强制重新加载配置（用于热更新场景）。"""
    global _AGENT_CONFIG
    _AGENT_CONFIG = load_agent_config(config_path)
    return _AGENT_CONFIG

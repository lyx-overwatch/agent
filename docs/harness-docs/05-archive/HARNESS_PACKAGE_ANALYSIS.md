# DeerFlow Harness 包结构化分析报告

> **分析对象**：`backend/packages/harness/deerflow/`（`deerflow-harness`）
> **分析目标**：为未来抽离核心逻辑到独立 SDK 提供结构化决策依据
> **总规模**：16 个子包 + 2 个顶层文件（`__init__.py`、`client.py`），约 70+ 个 Python 文件，~30000+ 行代码

---

## 一、总体概览

| 项目 | 数值 |
|------|------|
| 子包数 | 16 个子目录 + `__init__.py` + `client.py`（1202 行单文件） |
| 代码量 | ~70+ Python 文件，~30000+ 行 |
| 核心分层 | 核心 SDK / 应用层 / 边界依赖 / 辅助工具 |

整个包是一个典型的"**双层框架**"：

- **上半部分**：「可复用的 agent 运行时核心」——可作为通用 SDK 抽离
- **下半部分**：「DeerFlow 特有业务」——中文 prompt、IM 集成、本地沙箱、自定义 subagent

---

## 二、顶层文件

### 2.1 `__init__.py`（空）

包标识文件，无导出。

**分类**：辅助。

### 2.2 `client.py`（1202 行，单文件）

**核心导出**：`DeerFlowClient` 类、`StreamEvent` 数据类、`StreamEventType` Literal

**职责**：

1. 提供不依赖 LangGraph Server / Gateway API 的嵌入式 Python 客户端入口
2. 懒加载 + 配置驱动的 `create_agent` 工厂
3. 同步/异步的 `stream()` / `chat()` 消息流
4. 同步访问 thread、checkpointer、memory、uploads、artifacts
5. 桥接 `get_available_tools` / `_build_middlewares` / `apply_prompt_template`

**关键设计点**：

- `stream()` 和 Gateway 的 `run_agent` 是**两条并行路径**——`stream()` 是同步生成器，绕开 asyncio queue 抽象
- 直接依赖 `lead_agent/agent.py::_build_middlewares`（**私有函数**），存在跨层耦合
- 集成 tools.py、memory、uploads、extensions_config、MCP、skills

**分类**：**应用层 (App Layer)** —— 是给最终用户使用的便利门面，**不应抽离**到核心 SDK。

**依赖**：heavy（15+ 子包）—— `agents.lead_agent`、`config.*`、`models`、`runtime.user_context`、`skills.installer`、`uploads.manager`、`extensions_config`。

---

## 三、16 个子目录详细分析

### 3.1 `agents/` — Agent 编排（最核心）

**目录树**：

```
agents/
├── __init__.py                # 工厂 + 中间件 + 状态导出
├── factory.py                 # create_deerflow_agent 纯参数工厂 (15 KB)
├── features.py                # RuntimeFeatures dataclass + @Next/@Prev 装饰器
├── thread_state.py            # ThreadState / SandboxState TypedDict
├── lead_agent/
│   ├── __init__.py            # 导出 make_lead_agent
│   ├── agent.py               # 配置文件驱动的 make_lead_agent (411 行)
│   └── prompt.py              # System prompt 模板 + 技能缓存 (33 KB)
├── memory/
│   ├── __init__.py            # 全面导出
│   ├── message_processing.py  # filter/detect_correction/detect_reinforcement
│   ├── prompt.py              # MEMORY_UPDATE_PROMPT / FACT_EXTRACTION_PROMPT
│   ├── queue.py               # MemoryUpdateQueue + debounce 机制
│   ├── storage.py             # MemoryStorage ABC + FileMemoryStorage
│   ├── summarization_hook.py  # Summarization 前置 hook
│   └── updater.py             # LLM 驱动的事实提取 + 存储
└── middlewares/               # 17 个中间件，60+ KB
    ├── __init__.py (空)
    ├── clarification_middleware.py
    ├── dangling_tool_call_middleware.py
    ├── deferred_tool_filter_middleware.py
    ├── llm_error_handling_middleware.py   (14 KB, 含 circuit breaker)
    ├── loop_detection_middleware.py       (16 KB, 哈希滑动窗口)
    ├── memory_middleware.py
    ├── sandbox_audit_middleware.py        (14 KB, 危险命令审计)
    ├── subagent_limit_middleware.py
    ├── summarization_middleware.py        (13 KB, DeerFlowSummarizationMiddleware)
    ├── thread_data_middleware.py
    ├── title_middleware.py
    ├── todo_middleware.py
    ├── token_usage_middleware.py
    ├── tool_error_handling_middleware.py  (含 build_lead_runtime_middlewares 工厂)
    ├── uploads_middleware.py              (12 KB, 文档大纲注入)
    └── view_image_middleware.py
```

**核心职责**：

- `factory.py` 是**纯参数 SDK 入口**——`create_deerflow_agent(model, tools, system_prompt, middleware, features, ...)` 不读 YAML，是抽离候选
- `features.py` 的 `RuntimeFeatures` + `@Next` / `@Prev` 装饰器提供了**声明式中间件编排**（declarative feature flags）
- `thread_state.py` 的 `ThreadState` TypedDict 是**所有中间件状态 schema 的根基**
- `lead_agent/agent.py` 是**配置驱动工厂**——`make_lead_agent(config: RunnableConfig)` 解析 config.yaml
- `lead_agent/prompt.py`（33 KB）是 DeerFlow 业务灵魂——所有 system prompt 模板
- 17 个 middleware 组成有序链路（声明在 CLAUDE.md）：`ThreadData → Uploads → Sandbox → DanglingTool → LLMErrorHandling → Guardrail → SandboxAudit → ToolError → Summarization → TodoList → TokenUsage → Title → Memory → ViewImage → DeferredToolFilter → SubagentLimit → LoopDetection → Clarification`
- `memory/` 子包实现"**对话后异步抽取事实**"——`MemoryUpdateQueue` 用 `threading.Timer` + debounce，`MemoryUpdater` 调 LLM 总结

**关键类/函数/接口**：

| 名称 | 类型 | 行数 | 抽离价值 |
|------|------|------|----------|
| `create_deerflow_agent` | 公共 SDK 入口 | 147 | ⭐⭐⭐ 核心 |
| `RuntimeFeatures` | 数据类 | 35 | ⭐⭐⭐ 核心 |
| `@Next` / `@Prev` | 装饰器 | 21 | ⭐⭐⭐ 核心 |
| `ThreadState` | TypedDict | 55 | ⭐⭐⭐ 核心 |
| `make_lead_agent` | 工厂 | 411 | 应用层（依赖配置） |
| `_build_middlewares` | 内部 | 70 | 应用层 |
| `apply_prompt_template` | 提示组装 | - | 业务灵魂 |
| 17 个 `*Middleware` | 中间件 | 60+ KB | ⭐⭐⭐ 核心（部分） |
| `MemoryMiddleware` / `MemoryUpdater` / `MemoryStorage` | 内存 | 30+ KB | ⭐⭐ 核心 |
| `MemoryUpdateQueue` | 队列 | 200+ | 边界（线程/异步） |

**依赖**：

- **依赖**（imports）：`langchain.agents`、`langchain_core`、`deerflow.config`、`deerflow.sandbox`、`deerflow.skills`、`deerflow.models`、`deerflow.subagents`
- **被依赖**（imported by）：`client.py`、`langgraph.json`（`make_lead_agent`）、`app/gateway/*`

**分类**：

- **核心 SDK 候选**：`factory.py`、`features.py`、`thread_state.py`、大部分 `middlewares/`（但 LLM 错误处理、Sandbox 审计、Title、Memory 与 DeerFlow 业务强绑定）
- **应用层**：`lead_agent/agent.py`（YAML 依赖）、`lead_agent/prompt.py`（业务提示）、`memory/updater.py`（业务事实抽取）
- **边界依赖**：`runtime.user_context` 跨进程

---

### 3.2 `community/` — 社区贡献（8 个可选集成）

**目录树**：

```
community/
├── aio_sandbox/         # Docker/容器沙箱后端 (62 KB)
│   ├── aio_sandbox.py           # AioSandbox (HTTP API 客户端)
│   ├── aio_sandbox_provider.py  # AioSandboxProvider (32 KB, 完整生命周期)
│   ├── backend.py               # SandboxBackend 抽象 + wait_for_sandbox_ready
│   ├── local_backend.py         # LocalContainerBackend (Docker, 22 KB)
│   ├── remote_backend.py        # RemoteSandboxBackend (HTTP to provisioner)
│   └── sandbox_info.py          # SandboxInfo dataclass
├── ddg_search/          # DuckDuckGo 搜索 (no API key)
├── exa/                 # Exa 搜索 + 抓取
├── firecrawl/           # Firecrawl 搜索 + 抓取
├── image_search/        # DDG 图片搜索
├── infoquest/           # InfoQuest (19 KB, 完整客户端 + 工具)
├── jina_ai/             # Jina Reader API (web_fetch)
└── tavily/              # Tavily 搜索 + 抓取
```

**核心职责**：

- 8 个**可选**集成（搜索、抓取、沙箱后端），每个都是自包含的包
- `aio_sandbox` 是 DeerFlow 的**默认沙箱后端**——完整的容器编排、端口分配、空闲超时
- 6 个 web tool 全部通过 `deerflow.config.get_app_config().get_tool_config("web_search")` 读 API key

**关键类/函数**：

- `AioSandbox` / `AioSandboxProvider` / `LocalContainerBackend` / `RemoteSandboxBackend` / `SandboxBackend` —— 沙箱抽象
- `web_search_tool` / `web_fetch_tool` —— 6 个 web 工具各提供一对

**依赖**：

- **依赖**：`deerflow.config`、`deerflow.utils.readability`、`deerflow.sandbox`、`deerflow.utils.network`（for `get_free_port`）、大量第三方（ddgs、exa_py、firecrawl、tavily、jina、agent_sandbox）
- **被依赖**：`deerflow.sandbox.tools`、`deerflow.tools.tools`（动态加载）

**分类**：

- **可独立成包**：全部 `community/*` 都是**插件**——`aio_sandbox` 拆成 `deerflow-sandbox-aio`，web 工具拆成 `deerflow-tools-web`
- **不抽离**：留在 `deerflow-harness` 但作为可选 extras（`pip install deerflow-harness[web-tools,aio-sandbox]`）

---

### 3.3 `config/` — 配置管理（23 个子文件）

**目录树**：

```
config/
├── __init__.py             # 顶层 re-export
├── acp_config.py           # ACP (Agent Client Protocol) agents 配置
├── agents_api_config.py    # 是否暴露 agents API 路由
├── agents_config.py        # 自定义 agent 加载 (config.yaml)
├── app_config.py           # AppConfig Pydantic (18 KB) + 全局单例
├── checkpointer_config.py  # LangGraph checkpointer 配置
├── database_config.py      # 统一 database backend (memory/sqlite/postgres)
├── extensions_config.py    # extensions_config.json (MCP + skills)
├── guardrails_config.py    # Guardrail provider 配置
├── memory_config.py        # memory 子系统配置
├── model_config.py         # ModelConfig 数据类
├── paths.py                # Paths 类 + 虚拟路径解析 (14 KB)
├── run_events_config.py    # Run events 后端配置
├── sandbox_config.py       # Sandbox provider 配置
├── skill_evolution_config.py
├── skills_config.py
├── stream_bridge_config.py
├── subagents_config.py     # Subagent 自定义配置
├── summarization_config.py
├── title_config.py
├── token_usage_config.py
├── tool_config.py          # ToolConfig + ToolGroupConfig
├── tool_search_config.py
└── tracing_config.py
```

**核心职责**：

- **单例配置体系**——`AppConfig` + `set_app_config` / `get_app_config` / `push_current_app_config` / `pop_current_app_config`（ContextVar 栈）
- `app_config.py` 是**唯一的配置总入口**——所有 YAML 字段都汇总到这里
- `paths.py` 的 `Paths` 类实现**虚拟路径系统**——`/mnt/user-data/{workspace,uploads,outputs}` 映射到物理目录
- `extensions_config.py` 单独管理 `extensions_config.json`（与 `config.yaml` 分开）
- 23 个子配置都遵循**相同模式**：Pydantic BaseModel + 全局单例 + `load_*_from_dict`

**关键类/函数**：

- `AppConfig`（核心）—— 423 行，所有子配置的聚合
- `Paths` / `get_paths` / `resolve_virtual_path` —— 14 KB 路径解析器，含安全校验
- `get_app_config` / `reload_app_config` / `set_app_config` —— 单例 + ContextVar
- `ExtensionsConfig` / `McpServerConfig` / `McpOAuthConfig` / `SkillStateConfig` —— 扩展配置
- `McpOAuthConfig` 含 `token_field`、`token_type_field`、`expires_in_field` 等

**依赖**：

- **依赖**：Pydantic、PyYAML、dotenv、`deerflow.config.*`（内部循环引用）
- **被依赖**：几乎所有子包都 import `get_app_config`

**分类**：

- **核心**：`app_config.py`、`paths.py`、`extensions_config.py`、`model_config.py`、`tool_config.py`、`database_config.py`
- **应用层**：`agents_config.py`（自定义 agent 业务）、`agents_api_config.py`（HTTP 路由开关）、`acp_config.py`（IM 集成）

**抽离建议**：

- 配置可独立成 `deerflow-config` 子包
- `Paths` 是高度 Deeflow 特化（`/mnt/user-data` 硬编码），**需要抽象**出 `PathProvider` 接口

---

### 3.4 `guardrails/` — 守卫（OAP 协议）

**目录树**：

```
guardrails/
├── __init__.py      # 导出
├── builtin.py       # AllowlistProvider (1.2 KB)
├── middleware.py    # GuardrailMiddleware (4.4 KB)
└── provider.py      # GuardrailRequest/Decision/Reason/Provider Protocol
```

**核心职责**：

- 实现 **OAP (Open Agent Protocol) 兼容的预授权层**——tool call 前拦截
- `GuardrailProvider` 是**结构性 Protocol**（`@runtime_checkable`），不要求基类
- `AllowlistProvider` 是最简实现（白/黑名单）
- `GuardrailMiddleware` 包装 `wrap_tool_call` / `awrap_tool_call`，拦截并返回错误 `ToolMessage`

**关键类/函数**：

- `GuardrailRequest` / `GuardrailDecision` / `GuardrailReason` —— OAP 协议数据
- `GuardrailProvider` —— 协议
- `GuardrailMiddleware` —— LangChain 中间件
- `AllowlistProvider` —— 默认实现

**依赖**：

- **依赖**：`langchain.agents.middleware`、`langgraph.prebuilt.tool_node`、`deerflow.guardrails.provider`（内部）
- **被依赖**：`config/guardrails_config.py`、`agents/middlewares/tool_error_handling_middleware.py`

**分类**：**核心 SDK 候选**（独立、可替换、可插拔），可成 `deerflow-guardrails`。

---

### 3.5 `mcp/` — MCP 集成

**目录树**：

```
mcp/
├── __init__.py     # 导出 cache / client / tools
├── cache.py        # MCP 工具缓存（mtime 失效）
├── client.py       # build_server_params / build_servers_config
├── oauth.py        # OAuthTokenManager + 拦截器 (5.9 KB)
└── tools.py        # get_mcp_tools + 同步包装 (5.8 KB)
```

**核心职责**：

- 通过 `langchain-mcp-adapters` 桥接 Model Context Protocol
- 3 种传输：stdio / sse / http
- `OAuthTokenManager` 处理 MCP HTTP/SSE 的 OAuth 2.0 客户端凭证和 refresh token
- `MultiServerMCPClient(tool_interceptors=...)` 注入 OAuth 拦截器

**关键类/函数**：

- `OAuthTokenManager` —— 缓存 + 自动 refresh
- `build_oauth_tool_interceptor` —— 返回 `async def(request, handler) -> response` 拦截器
- `initialize_mcp_tools` / `get_cached_mcp_tools` —— 单例 + mtime 失效
- `_make_sync_tool_wrapper` —— async→sync 转换

**依赖**：

- **依赖**：`langchain_mcp_adapters`（可选）、`httpx`、`deerflow.config.extensions_config`、`deerflow.reflection`
- **被依赖**：`deerflow.tools.tools`

**分类**：**核心**（MCP 是 DeerFlow 重要扩展点），可拆成 `deerflow-mcp` 子包。

---

### 3.6 `models/` — 模型管理

**目录树**：

```
models/
├── __init__.py                  # create_chat_model
├── factory.py                   # 7.8 KB，反射 + 工厂
├── credential_loader.py         # Claude/Codex CLI 凭证自动加载 (7.2 KB)
├── claude_provider.py           # ClaudeChatModel (OAuth, 14.7 KB)
├── openai_codex_provider.py     # CodexChatModel (17 KB)
├── mindie_provider.py           # MindIE 推理引擎 (10.8 KB)
├── vllm_provider.py             # vLLM 服务 (10.8 KB)
├── patched_openai.py            # Gemini thought_signature 修复
├── patched_minimax.py           # 8.2 KB
└── patched_deepseek.py          # 3.2 KB
```

**核心职责**：

- **统一 ChatModel 工厂**——`create_chat_model(name, thinking_enabled, ...)` 通过 `deerflow.reflection.resolve_class` 反射加载
- **3 个原生 Provider**：Claude（含 Claude Code OAuth）、OpenAI Codex、MindIE
- **3 个 patched ChatOpenAI**：Gemini（thought_signature）、MiniMax（reasoning_split）、DeepSeek（reasoning_content）
- **1 个 vLLM provider**：用于本地 vLLM 服务
- 处理 `when_thinking_enabled` / `when_thinking_disabled` / `thinking` 三种 thinking 配置
- 默认开启 `stream_usage=True`（OpenAI 兼容网关需要）

**关键类/函数**：

- `create_chat_model(name, thinking_enabled, app_config, **kwargs)` —— 主入口
- `ClaudeChatModel`、`CodexChatModel`、`MindIEChatModel` —— 三个原生 provider
- `PatchedChatOpenAI` 系列（Gemini、MiniMax、DeepSeek）
- `ClaudeCodeCredential`、`CodexCliCredential` —— 凭证数据类
- `is_oauth_token(token)` —— 检测 Claude Code OAuth token

**依赖**：

- **依赖**：`langchain_anthropic`、`langchain_openai`、`langchain_deepseek`、`anthropic`、`deerflow.config`、`deerflow.reflection`、`deerflow.tracing`
- **被依赖**：`agents.lead_agent`、`agents.subagent.executor`、`skills.security_scanner`、`mcp.*`、`subagents.executor`

**分类**：

- **核心**：`factory.py`（反射工厂）
- **可独立成包**：所有 `*_provider.py` 和 `patched_*` 应拆成 `deerflow-models-providers`（可选 extras）
- **应用层**：`credential_loader.py`（Claude Code CLI 凭证是开发者体验，不是核心运行时）

---

### 3.7 `persistence/` — 持久化

**目录树**：

```
persistence/
├── __init__.py           # engine re-export
├── base.py               # DeclarativeBase + to_dict() 自动序列化
├── engine.py             # Async SQLAlchemy 引擎 + 跨进程 CREATE DATABASE (7.2 KB)
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/         # (空)
├── models/
│   ├── __init__.py       # 注册所有 ORM 模型
│   └── run_event.py      # RunEventRow
├── feedback/
│   ├── model.py          # FeedbackRow
│   └── sql.py            # FeedbackRepository
├── run/
│   ├── model.py          # RunRow
│   └── sql.py            # RunRepository
├── thread_meta/
│   ├── base.py           # ThreadMetaStore ABC
│   ├── memory.py         # MemoryThreadMetaStore (LangGraph BaseStore)
│   ├── model.py          # ThreadMetaRow
│   └── sql.py            # ThreadMetaRepository
└── user/
    ├── __init__.py
    └── model.py          # UserRow (凭证/auth 由 app 层做)
```

**核心职责**：

- **DeerFlow 自有的 ORM 层**（与 LangGraph checkpointer 分离）
- 5 张表：`runs`、`threads_meta`、`run_events`、`feedback`、`users`
- 3 种后端：`memory` / `sqlite` / `postgres`
- **3 态 user_id 解析**：`_AutoSentinel`（自动从 contextvar）、`str`（显式）、`None`（绕过）
- Alembic 迁移（但 `versions/` 为空——自动 `create_all` 在用）
- `ThreadMetaStore` 抽象支持 SQL 与 LangGraph BaseStore 两种实现

**关键类/函数**：

- `init_engine` / `close_engine` / `get_session_factory` —— 引擎生命周期
- `Base` —— 自动 `to_dict()` 序列化基类
- `RunRepository` / `ThreadMetaRepository` / `FeedbackRepository` —— 3 个 SQL repo
- `MemoryThreadMetaStore` —— 内存版（基于 LangGraph BaseStore）
- `RunStore` / `ThreadMetaStore` / `RunEventStore` —— 抽象接口
- `resolve_user_id` —— 3 态 user_id 解析

**依赖**：

- **依赖**：`sqlalchemy`、`asyncpg`/`aiosqlite`、`alembic`、`deerflow.runtime.user_context`、`deerflow.runtime.runs.store.base`
- **被依赖**：`app/gateway/*` 路由、`runtime/events/store/db.py`、`runtime/worker.py`

**分类**：

- **应用层 / 边界**：SQL ORM 与 LangGraph checkpointer 耦合、依赖 SQLAlchemy/asyncpg
- **抽离建议**：拆成 `deerflow-persistence`（独立子包），但应提供 `NoOp` / `In-Memory` 默认实现让核心 SDK 不强制要求数据库

---

### 3.8 `reflection/` — 反射（最独立）

**目录树**：

```
reflection/
├── __init__.py     # 导出 resolve_class / resolve_variable
└── resolvers.py    # 4 KB
```

**核心职责**：

- **统一的"字符串路径 → Python 对象"解析器**
- `resolve_variable("langchain_openai:ChatOpenAI")` → 类对象
- `resolve_class("pkg.module:Class", base_class=BaseChatModel)` → 类（带类型检查）
- **缺失依赖提示**：智能识别未安装的包并给出 `uv add xxx` 建议

**关键函数**：

- `resolve_variable(path, expected_type)` —— 通用解析
- `resolve_class(path, base_class)` —— 带基类校验

**依赖**：

- **依赖**：仅 `importlib`
- **被依赖**：`models.factory`、`mcp.tools`、`sandbox.sandbox_provider`、`tools.tools`

**分类**：**核心 / 工具**（极简、自包含），可独立成 `deerflow-reflection`。

---

### 3.9 `runtime/` — 运行时

**目录树**：

```
runtime/
├── __init__.py                # 全量 re-export
├── converters.py              # LangChain → OpenAI 格式转换 (4.8 KB)
├── journal.py                 # RunJournal (15 KB) — LangChain callback → RunEvent
├── serialization.py           # 序列化 LC 对象 (2.6 KB)
├── user_context.py            # 跨进程 user_id 上下文 (ContextVar)
├── checkpointer/              # LangGraph checkpointer 工厂
│   ├── provider.py            # sync (7.3 KB)
│   └── async_provider.py      # async (7.3 KB)
├── events/                    # RunEventStore 抽象 + 实现
│   ├── __init__.py
│   └── store/                 # base, memory, db, jsonl
├── runs/                      # RunManager + worker
│   ├── __init__.py
│   ├── manager.py             # RunManager + RunRecord (10 KB)
│   ├── schemas.py             # RunStatus / DisconnectMode
│   ├── worker.py              # run_agent 异步执行 (21 KB)
│   └── store/                 # base, memory
├── store/                     # LangGraph BaseStore 工厂
│   ├── provider.py            # sync (6.9 KB)
│   └── async_provider.py      # async (4.3 KB)
└── stream_bridge/             # 生产者-消费者解耦层
    ├── base.py                # StreamBridge ABC + StreamEvent
    ├── memory.py              # MemoryStreamBridge (in-process asyncio.Queue)
    └── async_provider.py      # make_stream_bridge
```

**核心职责**：

- `run_agent` 是**Gateway 唯一调用的 agent 执行入口**——async 函数，通过 `StreamBridge` 发布事件
- `RunJournal` 是 LangChain `BaseCallbackHandler`——捕获 LLM/token/lifecycle，写入 `RunEventStore`
- `StreamBridge` 是**生产者-消费者解耦**（模仿 LangGraph Platform Queue + StreamManager）
- `RunManager` + `RunRecord` 是 LangGraph Platform API 兼容的 run 生命周期管理
- `user_context` 通过 ContextVar 跨异步任务传 user_id
- 4 个 store/checkpointer 工厂：memory / sqlite / postgres

**关键类/函数**：

- `run_agent(bridge, run_manager, record, ctx, agent_factory, graph_input, config, ...)` —— 195 行核心循环
- `RunJournal` —— 跨多种 LangChain 事件类型的事件捕获
- `RunManager` / `RunRecord` —— run 状态机
- `StreamBridge` (ABC) / `MemoryStreamBridge` (impl)
- `RunEventStore` (ABC) / `MemoryRunEventStore` / `DBRunEventStore` / `JSONLRunEventStore`
- `RunStore` (ABC) / `MemoryRunStore`
- `make_checkpointer` / `make_store` / `make_stream_bridge` —— async 工厂
- `checkpointer_context` / `store_context` —— sync 工厂
- `serialize` / `serialize_messages_tuple` / `serialize_channel_values` —— JSON 序列化

**依赖**：

- **依赖**：`langgraph.checkpoint.{sqlite,postgres,memory}`、`langgraph.store.{sqlite,postgres,memory}`、`langchain_core.callbacks`、`deerflow.config.app_config`
- **被依赖**：`app/gateway/*` 大量使用；`client.py`

**分类**：

- **核心 SDK 候选**：`StreamBridge`、`RunManager`、`user_context`、`serialization`（抽象层）
- **应用层**：`run_agent` 的 LangGraph Platform 兼容性、HTTP 集成
- **边界依赖**：`checkpointer/`、`store/`（依赖 SQL/SQLite/Postgres）

**抽离建议**：

- `runtime/` 整个可独立成 `deerflow-runtime` 子包
- `StreamBridge` 接口设计良好，可单独抽离

---

### 3.10 `sandbox/` — 沙箱

**目录树**：

```
sandbox/
├── __init__.py                       # 导出 Sandbox, SandboxProvider
├── sandbox.py                        # Sandbox ABC (6 接口)
├── sandbox_provider.py               # SandboxProvider ABC + 单例 (3 KB)
├── middleware.py                     # SandboxMiddleware (3.3 KB)
├── exceptions.py                     # 6 个领域异常
├── security.py                       # is_host_bash_allowed (2 KB)
├── file_operation_lock.py            # per-(sandbox,path) 线程锁
├── search.py                         # glob/grep 工具函数 (6 KB)
├── tools.py                          # **1582 行 LangChain tools 集合**
└── local/
    ├── __init__.py
    ├── local_sandbox.py              # LocalSandbox 实现 (436 行)
    ├── local_sandbox_provider.py     # LocalSandboxProvider (121 行)
    └── list_dir.py
```

**核心职责**：

- **抽象沙箱接口**——`Sandbox` (6 方法) + `SandboxProvider` (3 方法)
- `tools.py` 是**最大的单文件**（1582 行）——含 `bash_tool`、`read_file`、`write_file`、`str_replace`、`ls`、`grep`、`glob`、`view` 等所有沙箱内工具
- `local/` 子包实现**进程内沙箱**（直接执行 host 命令，单例）
- `search.py` 提供 **glob/grep 实现**（与语言无关）
- `security.py` 判断 host bash 是否允许（`LocalSandboxProvider` 默认禁用）

**关键类/函数**：

- `Sandbox` ABC：`execute_command`、`read_file`、`write_file`、`list_dir`、`glob`、`grep`、`update_file`
- `SandboxProvider` ABC：`acquire`、`get`、`release`
- `LocalSandbox` / `LocalSandboxProvider` —— 进程内实现
- `SandboxMiddleware` —— 注入到 agent 中间件链
- `get_sandbox_provider()` —— 单例工厂（用 `resolve_class`）
- `is_host_bash_allowed()` —— 安全门控

**依赖**：

- **依赖**：`deerflow.config`、`deerflow.sandbox.search`（被社区包 `community/aio_sandbox` 实现）
- **被依赖**：`agents.middlewares`（SandboxMiddleware）、`tools`（沙箱工具）

**分类**：

- **核心**：`sandbox.py`、`sandbox_provider.py`（抽象层）
- **应用层 / 业务**：`tools.py` 1582 行是**LangChain tool 函数**的集合，**强依赖 DeerFlow 业务**（如 `mask_local_paths_in_output`、`validate_local_tool_path`）
- **核心**：`search.py`（glob/grep 实现）
- **应用层**：`local/`（生产环境禁用）

**抽离建议**：

- `sandbox.py` / `sandbox_provider.py` 抽到 `deerflow-sandbox-core`（仅抽象接口）
- `tools.py` 留在 harness 里（业务化）

---

### 3.11 `skills/` — Skills

**目录树**：

```
skills/
├── __init__.py             # 导出 load_skills, Skill, install_skill_from_archive
├── types.py                # Skill dataclass
├── parser.py               # parse_skill_file (YAML frontmatter)
├── loader.py               # load_skills + get_skills_root_path
├── validation.py           # frontmatter 校验
├── manager.py              # 自定义 skill CRUD (管理 API 用)
├── security_scanner.py     # LLM 驱动的内容安全扫描
└── installer.py            # .skill ZIP 安装 + 安全解压 (10.5 KB)
```

**核心职责**：

- **Skills 是 DeerFlow 的"能力单元"**——`SKILL.md` (YAML frontmatter + Markdown)
- 3 类：`public`（内置）、`custom`（用户/agent 创建）
- `load_skills()` 从 `skills/{public,custom}/` 扫描所有 `SKILL.md`
- `installer.py` 是 `.skill` ZIP 安装器，**含 zip bomb 防护、symlink 拒绝、traversal 检查、文件大小限制（512 MB）**
- `security_scanner.py` 用 LLM 评估 skill 内容（prompt injection / unsafe code 检测）
- `manager.py` 提供 create/edit/patch/delete/write_file/remove_file 操作

**关键类/函数**：

- `Skill` dataclass —— 8 字段
- `parse_skill_file(path, category)` —— 解析 frontmatter
- `load_skills(skills_path, use_config, enabled_only)` —— 扫描器
- `install_skill_from_archive(zip_path)` / `ainstall_skill_from_archive` —— 异步安装
- `safe_extract_skill_archive(zip_ref, dest, max_total_size=512MB)` —— 安全解压
- `scan_skill_content(content, executable)` —— LLM 安全扫描
- `validate_skill_frontmatter(skill_dir)` —— 校验

**依赖**：

- **依赖**：`pyyaml`、`zipfile`、`asyncio`、`deerflow.config`、`deerflow.models`（用于 security_scanner）
- **被依赖**：`agents.lead_agent.prompt`、`tools.skill_manage_tool`、`client.py`

**分类**：

- **核心**：`types.py`、`parser.py`、`loader.py`、`validation.py`、`installer.py`（**纯业务逻辑，可独立**）
- **应用层**：`security_scanner.py`（依赖 LLM）、`manager.py`（管理 API 用）

**抽离建议**：`skills` 可独立成 `deerflow-skills` 子包（含 SKILL.md 协议）。

---

### 3.12 `subagents/` — 子 agent

**目录树**：

```
subagents/
├── __init__.py                # 导出 SubagentConfig, SubagentExecutor, registry 函数
├── config.py                  # SubagentConfig dataclass (32 行)
├── registry.py                # get_subagent_config, get_subagent_names (162 行)
├── executor.py                # SubagentExecutor + 线程池管理 (676 行)
└── builtins/
    ├── __init__.py            # BUILTIN_SUBAGENTS = {"general-purpose": ..., "bash": ...}
    ├── general_purpose.py     # general-purpose agent 配置
    └── bash_agent.py          # bash agent 配置
```

**核心职责**：

- **"Subagent 即上下文隔离"**——每个 subagent 在自己的 thread / context 中执行
- 2 个内置 subagent：`general-purpose`（继承所有工具）、`bash`（沙箱 bash）
- `SubagentExecutor` 在**独立 ThreadPoolExecutor** 中执行（`max_workers=3`）
- `MAX_CONCURRENT_SUBAGENTS = 3`，`timeout_seconds = 900s`（15 分钟）
- **三层配置解析**：built-in → custom（from YAML）→ per-agent override
- 支持 `task_started` / `task_running` / `task_completed` / `task_failed` / `task_cancelled` / `task_timed_out` 流式事件
- 与主 agent 的 `trace_id` 关联（distributed tracing）

**关键类/函数**：

- `SubagentConfig` dataclass —— 8 字段
- `SubagentExecutor` —— 背景执行器
- `SubagentStatus` enum —— `PENDING` / `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED` / `TIMED_OUT`
- `SubagentResult` dataclass —— 含 `cancel_event`
- `get_subagent_config(name)` —— 配置解析
- `_filter_tools(all, allowed, disallowed)` —— 工具过滤
- `task_tool`（在 `tools/builtins/task_tool.py`）—— 主 agent 调用的入口

**依赖**：

- **依赖**：`deerflow.agents.thread_state`、`deerflow.config.subagents_config`、`deerflow.models`、`deerflow.sandbox.security`
- **被依赖**：`tools.builtins.task_tool`、`agents.lead_agent.prompt`（注入到 prompt）

**分类**：

- **核心**：`config.py`、`registry.py`（抽象层）
- **应用层**：`executor.py`（强业务，含 background polling、5s tick）、`builtins/`（业务 subagent 定义）

---

### 3.13 `tools/` — 工具

**目录树**：

```
tools/
├── __init__.py                # get_available_tools + skill_manage_tool (lazy)
├── tools.py                   # get_available_tools (7.4 KB) —— 工具装配器
├── skill_manage_tool.py       # skill_manage_tool (10.9 KB)
└── builtins/
    ├── __init__.py            # setup_agent, present_file_tool, ask_clarification_tool, view_image_tool, task_tool
    ├── clarification_tool.py
    ├── invoke_acp_agent_tool.py   # ACP 集成 (11.6 KB)
    ├── present_file_tool.py
    ├── setup_agent_tool.py
    ├── task_tool.py           # 12.7 KB，包含 polling 逻辑
    ├── tool_search.py         # DeferredToolRegistry (7.3 KB)
    └── view_image_tool.py
```

**核心职责**：

- `get_available_tools()` 是**工具装配总入口**——拼装 builtin + config tools + MCP tools + ACP tools
- 6 个 builtin tool：`present_files`、`ask_clarification`、`view_image`、`task`、`setup_agent`、`invoke_acp_agent`
- `tool_search.py` 实现**Claude Code 风格的延迟工具发现**——`DeferredToolRegistry` + `tool_search` tool
- `task_tool` 是 12.7 KB 单文件，**含完整的子 agent 轮询循环**
- `skill_manage_tool` 让 agent 自管理 skills（create/edit/patch/delete）

**关键类/函数**：

- `get_available_tools(groups, include_mcp, model_name, subagent_enabled, app_config)` —— 装配
- `DeferredToolRegistry` / `tool_search` —— 延迟工具发现
- 6 个 builtin tools（LangChain `@tool` 装饰）

**依赖**：

- **依赖**：`deerflow.config`、`deerflow.reflection`、`deerflow.mcp`、`deerflow.skills`、`deerflow.subagents`、`deerflow.sandbox.security`
- **被依赖**：`agents.lead_agent.agent`、`client.py`

**分类**：

- **核心**：`tools.py` 装配逻辑（如果去掉内置 tools）；`tool_search.py`（通用机制）
- **应用层**：所有 `builtins/`（强 DeerFlow 业务绑定）

---

### 3.14 `tracing/` — 追踪

**目录树**：

```
tracing/
├── __init__.py     # build_tracing_callbacks
└── factory.py      # LangSmith + Langfuse (1.9 KB)
```

**核心职责**：

- 为 `BaseChatModel` 注入 LangChain callback（LangSmith / Langfuse）
- 通过 `tracing_config` 配置项启用

**关键函数**：

- `build_tracing_callbacks()` —— 根据 config 构造 callback 列表
- `_create_langsmith_tracer(config)` / `_create_langfuse_handler(config)`

**依赖**：

- **依赖**：`langchain_core.tracers.langchain`、`langfuse`（可选）
- **被依赖**：`models.factory`

**分类**：**辅助 / 工具**（独立、可选），可成 `deerflow-tracing` 子包。

---

### 3.15 `uploads/` — 上传

**目录树**：

```
uploads/
├── __init__.py     # 全导出
└── manager.py      # 路径校验 + 文件 CRUD (6.7 KB)
```

**核心职责**：

- **用户上传文件的纯业务逻辑**——不含 FastAPI/HTTP 依赖（文档明确说明）
- `get_uploads_dir(thread_id)` / `ensure_uploads_dir(thread_id)` —— 目录管理
- `claim_unique_filename(name, seen)` —— 唯一命名
- `validate_path_traversal(path, base)` —— 路径穿越校验
- `delete_file_safe(base_dir, filename, convertible_extensions)` —— 安全删除（含 companion `.md` 清理）
- `upload_artifact_url` / `upload_virtual_path` —— URL 构造

**关键类/函数**：

- `PathTraversalError` exception
- `validate_thread_id` —— `thread_id` 字符白名单
- `get_uploads_dir` / `ensure_uploads_dir` / `list_files_in_dir` / `delete_file_safe` / `enrich_file_listing`
- `upload_artifact_url(thread_id, filename)` —— URL 构造

**依赖**：

- **依赖**：`deerflow.config.paths`、`deerflow.runtime.user_context`
- **被依赖**：`client.py`、`agents.middlewares.uploads_middleware`

**分类**：

- **核心 / 业务**：纯文件管理，可成 `deerflow-uploads` 子包
- 但当前实现是文件系统的，未来若要支持对象存储需抽象

---

### 3.16 `utils/` — 工具函数

**目录树**：

```
utils/
├── file_conversion.py   # PDF/PPT/Excel/Word → Markdown (12 KB)
├── network.py           # 线程安全端口分配器 (4.4 KB)
└── readability.py       # HTML → Article 提取
```

**核心职责**：

- `file_conversion.py` 实现 `convert_file_to_markdown`（pymupdf4llm 主，MarkItDown fallback）
- `network.py` 的 `PortAllocator` 是**线程安全的端口分配器**（aiob sandbox 用）
- `readability.py` 用 `readabilipy` + `markdownify` 把 HTML 转成 Markdown
- `extract_outline(md_path)` —— 从 markdown 抽取章节大纲（uploads 中间件用）

**关键类/函数**：

- `convert_file_to_markdown(path)` —— 转换入口
- `PortAllocator` / `get_free_port` / `release_port` —— 端口分配
- `ReadabilityExtractor` / `Article` —— HTML 解析
- `extract_outline` / `CONVERTIBLE_EXTENSIONS` —— 上传辅助

**依赖**：

- **依赖**：pymupdf4llm、markitdown、readabilipy、markdownify（外部）、socket、threading
- **被依赖**：`agents.middlewares.uploads_middleware`、`community.aio_sandbox.local_backend`、`community.jina_ai.tools`

**分类**：**辅助 / 工具**（独立），可成 `deerflow-utils` 子包。

---

## 四、依赖关系图

### 4.1 模块级依赖（关键路径）

```
                ┌────────────────────────┐
                │  langgraph.json entry  │
                │  deerflow.agents       │
                │  (make_lead_agent)     │
                └───────────┬────────────┘
                            │
        ┌───────────────────┼───────────────────────┐
        ▼                   ▼                       ▼
  ┌──────────┐       ┌──────────────┐         ┌──────────────┐
  │ agents/  │◀─────▶│   config/    │◀───────▶│   models/    │
  │ factory  │       │   app_config │         │  factory     │
  │ lead_    │       │   paths      │         │  providers   │
  │ agent    │       │   extensions │         │  patches     │
  └────┬─────┘       └──────┬───────┘         └──────┬───────┘
       │                    │                       │
       │           ┌────────┴────────┐              │
       ▼           ▼                 ▼              ▼
  ┌──────────┐  ┌────────┐    ┌──────────┐    ┌──────────┐
  │ sandbox/ │  │ skills │    │  mcp/    │    │  tracing │
  │ tools    │  │ loader │    │  tools   │    │  factory │
  │ providers│  │ install│    │  cache   │    └──────────┘
  └────┬─────┘  └────┬───┘    └────┬─────┘
       │             │              │
       ▼             ▼              ▼
  ┌──────────┐  ┌──────────┐   ┌──────────┐
  │  comm-   │  │  tools/  │   │  upload  │
  │  unity/  │  │  builtins│   │  manager │
  │ aio_sand │  │  task    │   │          │
  └──────────┘  └────┬─────┘   └──────────┘
                     │
                     ▼
              ┌─────────────┐
              │ subagents/  │
              │  executor   │
              │  registry   │
              └─────────────┘

  ┌──────────────────────────────────────────────┐
  │  runtime/  (run_agent + StreamBridge + ...)  │ ◀── app/gateway, client.py
  └──────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────┐
  │  persistence/  (ORM + SQL + ThreadMetaStore) │ ◀── app/gateway, runtime
  └──────────────────────────────────────────────┘
```

### 4.2 关键横向依赖（容易破坏边界）

| 依赖方 | 被依赖方 | 类型 | 抽离风险 |
|--------|----------|------|----------|
| `agents/lead_agent/agent.py` | `config.app_config` | YAML 读取 | ⭐⭐⭐ 高 |
| `agents/memory/updater.py` | `models.create_chat_model` | LLM 调用 | ⭐⭐ 中 |
| `skills/security_scanner.py` | `models.create_chat_model` | LLM 调用 | ⭐⭐ 中 |
| `sandbox/tools.py` | `agents.thread_state`、`deerflow.sandbox.search` | 业务耦合 | ⭐⭐ 中 |
| `persistence/*` | `runtime.user_context` | ContextVar 依赖 | ⭐⭐⭐ 高 |
| `tools/builtins/task_tool.py` | `subagents.executor`、`runtime.user_context` | 业务耦合 | ⭐⭐ 中 |
| `mcp/tools.py` | `reflection.resolve_variable` | 反射 | ⭐ 低 |
| `client.py` | `agents.lead_agent._build_middlewares`（私有） | 跨层 | ⭐⭐⭐ 高 |

### 4.3 反向依赖（被外部大量使用）

| 模块 | 被谁使用（harness 内） | 抽离建议 |
|------|------------------------|----------|
| `config.get_app_config` | **几乎全部** | 必有 |
| `config.paths.get_paths` | 15+ 文件 | 必有 |
| `models.create_chat_model` | 10+ 文件 | 必有 |
| `sandbox.get_sandbox_provider` | 中间件 | 必有 |
| `skills.load_skills` | `agents.prompt`、`client` | 必有 |
| `persistence.init_engine` | `app/gateway` | 应用层 |
| `runtime.run_agent` | `app/gateway`、`client` | 应用层 |
| `tools.get_available_tools` | `agents`、`client` | 必有 |
| `agents.thread_state.ThreadState` | 所有中间件 | 核心 |

---

## 五、分类总结

### 5.1 核心 SDK 候选（必须抽离的）

| 模块 | 抽离候选度 | 关键类型 |
|------|------------|----------|
| `agents/factory.py` | ⭐⭐⭐⭐⭐ | `create_deerflow_agent`、`RuntimeFeatures`、`@Next`/`@Prev` |
| `agents/thread_state.py` | ⭐⭐⭐⭐⭐ | `ThreadState`、`SandboxState`、reducers |
| `agents/features.py` | ⭐⭐⭐⭐⭐ | `RuntimeFeatures`、decorators |
| `agents/middlewares/*.py`（除业务强绑定外） | ⭐⭐⭐⭐ | 17 个 middleware，但 ToolError/LoopDetection/DanglingTool/SandboxAudit 是通用模式 |
| `config/app_config.py` | ⭐⭐⭐⭐ | `AppConfig` 单例模式 |
| `config/paths.py` | ⭐⭐⭐ | `Paths` 类（需抽象路径前缀） |
| `config/extensions_config.py` | ⭐⭐⭐ | `ExtensionsConfig`、MCP 配置 |
| `guardrails/` | ⭐⭐⭐⭐ | `GuardrailProvider` Protocol + Middleware |
| `mcp/` | ⭐⭐⭐ | MCP 客户端 + OAuth |
| `models/factory.py` | ⭐⭐⭐⭐ | `create_chat_model` 反射工厂 |
| `reflection/` | ⭐⭐⭐⭐⭐ | `resolve_class` / `resolve_variable`（独立可抽） |
| `sandbox/sandbox.py` | ⭐⭐⭐⭐ | `Sandbox` ABC |
| `sandbox/sandbox_provider.py` | ⭐⭐⭐⭐ | `SandboxProvider` ABC |
| `sandbox/search.py` | ⭐⭐⭐⭐ | glob/grep |
| `skills/types.py`、`parser.py`、`loader.py`、`validation.py`、`installer.py` | ⭐⭐⭐⭐ | SKILL.md 协议 |
| `subagents/config.py`、`registry.py` | ⭐⭐⭐ | SubagentConfig + 解析 |
| `tools/tools.py`（装配器） | ⭐⭐⭐ | `get_available_tools` 装配逻辑 |
| `tools/builtins/tool_search.py` | ⭐⭐⭐ | `DeferredToolRegistry` |
| `tracing/` | ⭐⭐⭐⭐ | 独立可抽 |
| `utils/file_conversion.py`、`network.py`、`readability.py` | ⭐⭐⭐⭐ | 独立可抽 |
| `runtime/user_context.py` | ⭐⭐⭐ | ContextVar 模式 |
| `runtime/serialization.py` | ⭐⭐⭐ | LC 对象序列化 |
| `runtime/stream_bridge/` | ⭐⭐⭐ | StreamBridge 抽象 |
| `runtime/runs/manager.py` | ⭐⭐ | RunManager（API 兼容层） |
| `runtime/store/`、`runtime/checkpointer/` | ⭐⭐ | LangGraph 集成（可选后端） |

### 5.2 应用层（应保留在 app 层）

| 模块 | 原因 |
|------|------|
| `agents/lead_agent/agent.py` | YAML 驱动的 `make_lead_agent`，与配置强绑定 |
| `agents/lead_agent/prompt.py` | 33 KB 业务 prompt 模板，DeerFlow 特有 |
| `agents/memory/*`（updater、storage、prompt、queue） | "LLM 抽取事实"是 DeerFlow 特定业务 |
| `agents/middlewares/title_middleware.py` | DeerFlow 业务："生成对话标题" |
| `agents/middlewares/memory_middleware.py` | 与 memory 子系统绑定 |
| `agents/middlewares/uploads_middleware.py` | 与 uploads/ 业务绑定 |
| `agents/middlewares/view_image_middleware.py` | DeerFlow 业务：图片处理 |
| `sandbox/tools.py`（1582 行） | 强 DeerFlow 业务，工具名 / 描述全是中文 + 业务化 |
| `sandbox/local/` | 仅在 trusted 模式使用 |
| `subagents/builtins/*` | 业务 subagent 定义 |
| `subagents/executor.py` | 强 DeerFlow 业务（background polling、5s tick） |
| `tools/builtins/*`（除 `tool_search.py`） | 业务工具 |
| `uploads/manager.py` | "用户上传"业务（与 IM / 文档处理相关） |
| `community/*` | 全部是第三方集成的插件 |
| `persistence/*` | SQLAlchemy ORM + 用户/线程元数据（应用层数据） |
| `models/credential_loader.py` | Claude Code / Codex CLI 凭证 |
| `models/claude_provider.py` 等 | Provider 是 Deeflow 业务，但应可独立 |
| `client.py` | 嵌入式 Python 客户端门面 |
| `agents/middlewares/llm_error_handling_middleware.py` | 包含 circuit breaker（DeerFlow 业务概念） |
| `agents/middlewares/sandbox_audit_middleware.py` | DeerFlow 特有的 bash 审计规则 |

### 5.3 边界依赖（需要解耦的）

| 模块 | 边界 | 解耦方案 |
|------|------|----------|
| `config/paths.py` | 文件系统（绝对路径、Docker volume mount） | 抽象 `PathProvider` 接口 |
| `sandbox/local/local_sandbox.py` | subprocess 进程内执行 | 抽象 `Sandbox` 已有 |
| `sandbox/local/local_sandbox_provider.py` | 全局单例 | 通过 DI 注入 |
| `persistence/engine.py` | SQLAlchemy async engine | 抽象 `StorageBackend`（已有 `MemoryThreadMetaStore`） |
| `runtime/checkpointer/` | LangGraph checkpointer backend | 已经是工厂模式 |
| `runtime/store/` | LangGraph BaseStore | 已经是工厂模式 |
| `runtime/stream_bridge/memory.py` | in-process asyncio queue | 已有抽象 `StreamBridge` |
| `mcp/cache.py` | 全局单例 + mtime 失效 | 抽象 `MCPCache` |
| `runtime/user_context.py` | ContextVar | 抽象 `UserContext` 接口 |
| `runtime/runs/worker.py` | LangGraph Platform API 兼容 | 抽象 `RunExecutor` |

### 5.4 工具/辅助（可以独立成包的）

| 模块 | 建议包名 | 依赖 |
|------|----------|------|
| `reflection/` | `deerflow-reflection` | 无 |
| `tracing/` | `deerflow-tracing` | `langchain_core` |
| `utils/` | `deerflow-utils` | pymupdf、markitdown、readabilipy |
| `mcp/` | `deerflow-mcp` | `langchain-mcp-adapters`、httpx |
| `skills/` | `deerflow-skills` | pyyaml、zipfile |
| `guardrails/` | `deerflow-guardrails` | `langchain.agents.middleware` |
| `runtime/checkpointer/` | `deerflow-checkpointer` | `langgraph.checkpoint` |
| `runtime/store/` | `deerflow-store` | `langgraph.store` |
| `runtime/stream_bridge/` | `deerflow-stream-bridge` | 无（仅 asyncio） |
| `models/` | `deerflow-models` + `deerflow-models-{claude,codex,vllm,...}` | langchain_* |
| `community/aio_sandbox/` | `deerflow-sandbox-aio` | agent_sandbox、docker |
| `community/{exa,firecrawl,jina,tavily,ddg,image_search}/` | `deerflow-tools-web` | exa_py、firecrawl、... |

---

## 六、抽离建议

### 6.1 抽离顺序（推荐 4 个阶段）

**阶段 1：零依赖辅助包（1-2 周）**

- 抽离 `reflection/`、`tracing/`、`utils/`、`runtime/stream_bridge/`
- 理由：依赖极少，可立即拆分；提供基础工具
- 风险：低

**阶段 2：配置 + 反射（2-3 周）**

- 抽离 `config/app_config.py`、`config/paths.py`、`config/extensions_config.py`、`config/agent_config.py`、`config/database_config.py`
- 抽离 `models/factory.py`（反射 + 工厂模式）
- 抽象 `PathProvider` 接口，让 paths 可注入
- 理由：几乎所有其他模块都依赖 config，先抽离
- 风险：中（需要修改 50+ 个 import）

**阶段 3：核心 Agent 框架（4-6 周）**

- 抽离 `agents/factory.py`、`agents/features.py`、`agents/thread_state.py`、通用 middleware（DanglingToolCall、LoopDetection、ToolErrorHandling、Clarification、DeferredToolFilter）
- 抽离 `guardrails/`、`mcp/`、`sandbox/{sandbox,sandbox_provider,search,exceptions,security,file_operation_lock}.py`
- 抽离 `subagents/config.py` + `registry.py`（不含 executor）
- 抽离 `tools/tools.py` 装配器
- 抽离 `skills/{types,parser,loader,validation,installer}.py`
- 抽离 `runtime/{serialization,user_context}.py`、`runtime/runs/{manager,schemas}.py`
- 理由：核心 SDK 的主体
- 风险：中-高（要保持向后兼容）

**阶段 4：应用层 + 业务层（持续）**

- 保留在 `deerflow`（或拆出 `deerflow-app`）：
  - `agents/lead_agent/`、`agents/memory/`
  - `agents/middlewares/{llm_error, sandbox_audit, memory, title, view_image, uploads, subagent_limit, summarization}.py`
  - `sandbox/tools.py`（1582 行）
  - `sandbox/local/`
  - `subagents/executor.py`、`subagents/builtins/`
  - `tools/builtins/*`（除 tool_search）
  - `uploads/manager.py`
  - `skills/{manager,security_scanner}.py`
  - `community/*`
  - `persistence/*`
  - `models/{credential_loader, *_provider, patched_*}.py`
  - `client.py`

### 6.2 抽离方案

#### 方案 A：渐进式拆分（推荐）

```
deerflow-harness (核心, PyPI: deerflow-harness)
  ├─ 子目录（re-export 旧路径以保持兼容）
  └─ extras_require:
       [web-tools]   → community/{exa,firecrawl,jina,tavily,ddg,image_search}
       [aio-sandbox] → community/aio_sandbox
       [persistence] → persistence/ + SQLAlchemy
       [providers]   → models/*_provider.py, patched_*
       [mcp]         → mcp/
       [all]
```

新增 `deerflow-*` 子包：

- `deerflow-reflection` —— 反射工具
- `deerflow-utils` —— 文件/网络工具
- `deerflow-tracing` —— 追踪
- `deerflow-skills` —— SKILL.md 协议
- `deerflow-guardrails` —— OAP 守卫
- `deerflow-mcp` —— MCP 集成
- `deerflow-sandbox-core` —— 沙箱抽象（不含 tools.py）
- `deerflow-models` + `deerflow-models-*` —— 模型
- `deerflow-checkpointer` / `deerflow-store` / `deerflow-stream-bridge` —— runtime
- `deerflow-uploads` —— 文件上传

#### 方案 B：单包多子模块（折中）

保留 `deerflow-harness` 单包，但用 lazy loading + 严格的 import 边界：

- 用 `tests/test_harness_boundary.py`（现有）验证不依赖 `app.*`
- 新增 `tests/test_core_sdk_boundary.py` 验证"核心"模块不依赖"应用"模块
- 内部 `deerflow.core`、`deerflow.app` 分层

#### 方案 C：完全拆分（最激进）

完全拆成多个独立 PyPI 包。优点：依赖最小化，可组合。缺点：维护成本高、版本管理复杂。

### 6.3 潜在风险

1. **循环依赖**
   - `agents/lead_agent/agent.py` → `config.*` → `agents/...` 可能形成循环
   - 当前用 lazy import 解决；抽离时需保持

2. **私有函数跨层**
   - `client.py` 调用 `deerflow.agents.lead_agent.agent._build_middlewares`（下划线开头）
   - 抽离前应公开此函数或用其他方式

3. **ContextVar 隐式依赖**
   - `runtime.user_context` 大量使用 `ContextVar`
   - 子进程 / 多线程下需重新评估
   - `MemoryUpdateQueue` 用 `threading.Timer` 跨线程——`ContextVar` 不会自动传播

4. **LangGraph 版本耦合**
   - 大量代码依赖 LangGraph 0.6+ 的 `Runtime`、`Command`、`ToolCallRequest` API
   - 升级 LangGraph 时需谨慎回归测试

5. **单例 + 全局状态**
   - `_app_config`、`_paths`、`_mcp_tools_cache`、`_mcp_tool_registry` 等都是模块级单例
   - 抽离后需统一为 `ContextVar` 或 DI 容器

6. **`extensions_config.json` vs `config.yaml` 双文件**
   - 现有 hot-reload 机制假设两个文件都被监听
   - 抽离后接口需保留

7. **大量隐式配置**
   - `sandbox.tools.py` 通过 `get_app_config().sandbox` 读配置
   - 抽离后需通过 `SandboxProvider` 构造参数注入

8. **业务与通用未分离**
   - 17 个 middleware 中，DanglingToolCall / LoopDetection / ToolErrorHandling / Clarification 是通用模式
   - MemoryMiddleware / ViewImageMiddleware / UploadsMiddleware / TitleMiddleware 是 DeerFlow 特有
   - LLMErrorHandlingMiddleware 含 circuit breaker 是 DeerFlow 特有
   - SandboxAuditMiddleware 含 DeerFlow 特有的 bash 审计规则
   - 抽离时**必须明确标注**哪些是通用、哪些是业务

9. **prompt 模板硬编码**
   - `agents/lead_agent/prompt.py` 33 KB 全部是硬编码字符串
   - 抽离后应支持外部 prompt 文件注入

10. **测试依赖**
    - `client.py` 是单测集成点
    - 抽离后应保证 `client.py` 可独立测试

---

## 七、最终建议

### 7.1 核心抽离目标包（按优先级）

| 顺序 | 包名 | 估时 | 风险 | 价值 |
|------|------|------|------|------|
| 1 | `deerflow-reflection` | 1d | 极低 | 高（任何项目通用） |
| 2 | `deerflow-tracing` | 2d | 低 | 中 |
| 3 | `deerflow-utils` | 3d | 低 | 中 |
| 4 | `deerflow-guardrails` | 1w | 中 | 高（OAP 协议） |
| 5 | `deerflow-mcp` | 1w | 中 | 高 |
| 6 | `deerflow-skills`（核心协议） | 1w | 中 | 高 |
| 7 | `deerflow-sandbox-core`（仅抽象） | 1w | 中-高 | 高 |
| 8 | `deerflow-models`（工厂） | 1w | 中 | 高 |
| 9 | `deerflow-runtime`（bridge + serialization） | 2w | 高 | 高 |
| 10 | `deerflow-agent-core`（factory + features + thread_state + 通用 middleware） | 3w | 高 | 极高 |

### 7.2 建议立即开始的小型抽离

1. `reflection/` 抽成 `deerflow-reflection`（半天工作量）
2. `tracing/` 抽成 `deerflow-tracing`（半天）
3. `guardrails/` 抽成 `deerflow-guardrails`（2 天）
4. `utils/` 抽成 `deerflow-utils`（2 天）

这 4 个是**最容易、最快、风险最低**的抽离，可以立即做。

### 7.3 重点重构目标

- `agents/factory.py` + `agents/features.py` + `agents/thread_state.py` —— 这 3 个文件共同定义了 SDK 公共 API
- `config/paths.py` —— 需要抽象 `PathProvider` 接口
- `client.py` —— 重新组织为 SDK 公开 API（`DeerFlowClient` 应成为 SDK 的标志）

### 7.4 不建议抽离的部分

- `agents/lead_agent/`、`agents/memory/` —— 业务灵魂，留在应用层
- `sandbox/tools.py`（1582 行）—— 强业务化，独立成包得不偿失
- `client.py` —— 是 Deeflow 特有门面，不应成为通用 SDK
- `community/*` —— 已经按"可选集成"组织好了

---

## 八、关键文件路径索引

> 全部为绝对路径，按分析顺序排列

### 顶层

- `D:\registry\source\deer-flow\backend\packages\harness\deerflow\__init__.py`
- `D:\registry\source\deer-flow\backend\packages\harness\deerflow\client.py`

### agents

- `backend/packages/harness/deerflow/agents/__init__.py`
- `backend/packages/harness/deerflow/agents/factory.py`（核心）
- `backend/packages/harness/deerflow/agents/features.py`（核心）
- `backend/packages/harness/deerflow/agents/thread_state.py`（核心）
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py`（应用层）
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`（应用层）
- `backend/packages/harness/deerflow/agents/memory/*`（应用层）
- `backend/packages/harness/deerflow/agents/middlewares/*`（混合）

### config

- `backend/packages/harness/deerflow/config/app_config.py`（核心）
- `backend/packages/harness/deerflow/config/paths.py`（核心，需抽象）
- `backend/packages/harness/deerflow/config/extensions_config.py`（核心）

### reflection（建议立即抽离）

- `backend/packages/harness/deerflow/reflection/__init__.py`
- `backend/packages/harness/deerflow/reflection/resolvers.py`

### tracing（建议立即抽离）

- `backend/packages/harness/deerflow/tracing/__init__.py`
- `backend/packages/harness/deerflow/tracing/factory.py`

### guardrails

- `backend/packages/harness/deerflow/guardrails/__init__.py`
- `backend/packages/harness/deerflow/guardrails/provider.py`
- `backend/packages/harness/deerflow/guardrails/middleware.py`
- `backend/packages/harness/deerflow/guardrails/builtin.py`

### sandbox

- `backend/packages/harness/deerflow/sandbox/sandbox.py`（核心 ABC）
- `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`（核心 ABC）
- `backend/packages/harness/deerflow/sandbox/search.py`（核心）
- `backend/packages/harness/deerflow/sandbox/tools.py`（1582 行，应用层）
- `backend/packages/harness/deerflow/sandbox/local/*`（应用层）

### skills

- `backend/packages/harness/deerflow/skills/__init__.py`
- `backend/packages/harness/deerflow/skills/types.py`
- `backend/packages/harness/deerflow/skills/parser.py`
- `backend/packages/harness/deerflow/skills/loader.py`
- `backend/packages/harness/deerflow/skills/installer.py`
- `backend/packages/harness/deerflow/skills/validation.py`
- `backend/packages/harness/deerflow/skills/manager.py`（应用层）
- `backend/packages/harness/deerflow/skills/security_scanner.py`（应用层）

### subagents

- `backend/packages/harness/deerflow/subagents/__init__.py`
- `backend/packages/harness/deerflow/subagents/config.py`（核心）
- `backend/packages/harness/deerflow/subagents/registry.py`（核心）
- `backend/packages/harness/deerflow/subagents/executor.py`（应用层，676 行）
- `backend/packages/harness/deerflow/subagents/builtins/*`（应用层）

### tools

- `backend/packages/harness/deerflow/tools/__init__.py`
- `backend/packages/harness/deerflow/tools/tools.py`（核心装配）
- `backend/packages/harness/deerflow/tools/skill_manage_tool.py`（应用层）
- `backend/packages/harness/deerflow/tools/builtins/*`（应用层）

### mcp

- `backend/packages/harness/deerflow/mcp/__init__.py`
- `backend/packages/harness/deerflow/mcp/cache.py`
- `backend/packages/harness/deerflow/mcp/client.py`
- `backend/packages/harness/deerflow/mcp/oauth.py`
- `backend/packages/harness/deerflow/mcp/tools.py`

### models

- `backend/packages/harness/deerflow/models/__init__.py`
- `backend/packages/harness/deerflow/models/factory.py`（核心）
- `backend/packages/harness/deerflow/models/credential_loader.py`（应用层）
- `backend/packages/harness/deerflow/models/*_provider.py`（应用层）
- `backend/packages/harness/deerflow/models/patched_*.py`（应用层）

### runtime

- `backend/packages/harness/deerflow/runtime/__init__.py`
- `backend/packages/harness/deerflow/runtime/user_context.py`（核心）
- `backend/packages/harness/deerflow/runtime/serialization.py`（核心）
- `backend/packages/harness/deerflow/runtime/journal.py`（应用层）
- `backend/packages/harness/deerflow/runtime/checkpointer/*`（应用层）
- `backend/packages/harness/deerflow/runtime/store/*`（应用层）
- `backend/packages/harness/deerflow/runtime/stream_bridge/*`（核心抽象）
- `backend/packages/harness/deerflow/runtime/runs/*`（应用层）
- `backend/packages/harness/deerflow/runtime/events/*`（应用层）
- `backend/packages/harness/deerflow/runtime/converters.py`（辅助）

### persistence

- `backend/packages/harness/deerflow/persistence/__init__.py`
- `backend/packages/harness/deerflow/persistence/base.py`（核心）
- `backend/packages/harness/deerflow/persistence/engine.py`（应用层）
- `backend/packages/harness/deerflow/persistence/models/*`（核心 ORM 定义）
- `backend/packages/harness/deerflow/persistence/run/*`（应用层）
- `backend/packages/harness/deerflow/persistence/thread_meta/*`（应用层）
- `backend/packages/harness/deerflow/persistence/feedback/*`（应用层）
- `backend/packages/harness/deerflow/persistence/user/model.py`（应用层）
- `backend/packages/harness/deerflow/persistence/migrations/*`（应用层）

### utils

- `backend/packages/harness/deerflow/utils/file_conversion.py`
- `backend/packages/harness/deerflow/utils/network.py`
- `backend/packages/harness/deerflow/utils/readability.py`

### uploads

- `backend/packages/harness/deerflow/uploads/__init__.py`
- `backend/packages/harness/deerflow/uploads/manager.py`

### community

- `backend/packages/harness/deerflow/community/aio_sandbox/*`（应用层插件）
- `backend/packages/harness/deerflow/community/{exa,firecrawl,jina,tavily,ddg_search,image_search,infoquest}/*`（应用层插件）

---

## 九、总结

**DeerFlow Harness 是一个典型的"双层"框架**：

### 1. 核心 SDK 层（可抽离、应抽离）

- `agents/factory.py` + `features.py` + `thread_state.py` —— 纯参数 Agent 工厂
- 通用 middleware（DanglingToolCall、LoopDetection、ToolErrorHandling、Clarification、DeferredToolFilter）
- `config/app_config.py` + `paths.py` + `extensions_config.py` —— 配置
- `models/factory.py` —— 模型反射工厂
- `sandbox/{sandbox,sandbox_provider,search}.py` —— 抽象层
- `skills/{types,parser,loader,validation,installer}.py` —— SKILL.md 协议
- `mcp/`、`guardrails/`、`tracing/`、`reflection/`、`utils/` —— 各自独立
- `runtime/stream_bridge`、`runtime/user_context`、`runtime/serialization` —— 抽象层
- `subagents/{config,registry}.py` —— 抽象层

### 2. 应用层 / 业务层（应保留在 `deerflow` 或拆到 `deerflow-app`）

- `agents/lead_agent/*`、`agents/memory/*`
- 业务 middleware（MemoryMiddleware、TitleMiddleware、UploadsMiddleware、ViewImageMiddleware、LLMErrorHandlingMiddleware、SandboxAuditMiddleware）
- `sandbox/tools.py`（1582 行）、`sandbox/local/*`
- `subagents/executor.py`、`subagents/builtins/*`
- `tools/builtins/*`（除 tool_search）
- `uploads/manager.py`、`persistence/*`、`client.py`
- `community/*`、`models/*_provider.py`、`models/patched_*.py`

**抽离路线图**：建议从最独立的 `reflection/`、`tracing/`、`guardrails/`、`utils/` 入手，逐步推进到 `config/` + `models/factory.py` + `agents/factory.py` 主体。整个过程预计 2-3 个月工作量。

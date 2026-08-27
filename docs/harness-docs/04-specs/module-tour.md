# SDK 模块手册（Module Tour）

> **目的**：这份文档解决两个问题——
> 1. `agent_sdk/` 下面 15 个文件夹每个是什么作用，互相怎么配合；
> 2. 如果你想测某个模块，应该看哪些测试文件、跑什么命令、怎么手验。
>
> **适用读者**：第一次接触 SDK 源码、想定位"某个功能在哪"或"某个测试怎么跑"的人。
>
> **不重复**：本文不展开每个 Protocol 的逐字签名——打开对应文件 5 行内有 module docstring；本文重点在**地图 + 测试**。

---

## 0. 30 秒俯瞰

SDK 的核心抽象可以浓缩成 7 个钩子（按依赖关系自下而上）：

```
                ┌──────────────────────────────────────┐
                │  create_agent(model, features, ...)  │  ← 唯一公开入口
                └──────────────────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
     RuntimeFeatures        MiddlewareChainConfig      @Next / @Prev
     (声明开哪些能力)         (注入 path/sandbox/...)    (extra mw 定位)
            │                      │
            ▼                      ▼
       19 middlewares      PathProvider / SandboxProvider
       (按 backend 顺序)     / MemoryStorage / Skills / GuardrailProvider / ...
            │
            ▼
       7 个 builtin tools (ask_clarification / view_image / task / ...)
       + MCP 工具（动态）
       + Skills（动态）
```

**文件组织原则**：
- `agent_sdk/runtime/`：**装配层**——入口、链装配、上下文、LangGraph 胶水
- `agent_sdk/middlewares/`：**业务规则**——每个 middleware 一个文件
- `agent_sdk/{paths,memory,subagents,sandbox,guardrails,skills,mcp,tracing,models,tools}/`：**业务子系统**——每个子系统一个文件夹
- `agent_sdk/presets/deerflow/`：**DeerFlow 业务实现**——其他子系统的"有业务味道"版本

---

## 1. 文件夹逐个拆解

### 1.1 `agent_sdk/runtime/` — 装配层（10 个文件）

**作用**：这是 SDK 入口 + 链装配 + LangGraph 集成。**所有"如何把 middlewares 拼起来"的逻辑都在这里**。

| 文件 | 作用 | 关键导出 |
|------|------|----------|
| `entry.py` | `create_agent()` 工厂函数 | `create_agent(model, features, middleware, extra_middleware, l2_config, plan_mode, state_schema)` |
| `features.py` | `RuntimeFeatures` 特性标志 | `RuntimeFeatures` dataclass（sandbox/memory/summarization/subagent/vision/auto_title/guardrail） |
| `middleware_chain.py` | 把 features 装成有序 middleware 链 | `MiddlewareChainConfig` + `assemble_chain(features, config, ...)`（**5.5** 新增 `summarization_partitioner` / `guardrail_provider` / `skills_path` / `skills_container_base_path` 字段） |
| `decorators.py` | `@Next` / `@Prev` 装饰器 | `Next(anchor)` / `Prev(anchor)` |
| `user_context.py` | 请求级用户上下文（`CurrentUser` Protocol + ContextVar） | `CurrentUser` / `resolve_user_id()` / `get_effective_user_id()` |
| `stream_bridge.py` | Worker ↔ SSE 抽象桥 | `StreamBridge` ABC + `StreamEvent` + `HEARTBEAT_SENTINEL` |
| `thread_state.py` | 默认 AgentState TypedDict（含 `artifacts` / `viewed_images` 槽 + reducer） | `ThreadState` |
| `langgraph_integration.py` | LangGraph 胶水（thread_id 校验 / run_id 生成 / config 合并） | `make_thread_config()` / `merge_configs()` / `make_run_id()` / `is_valid_thread_id()` |
| `checkpointer/` | 3 后端 checkpointer 工厂（memory / sqlite / postgres） | `CheckpointerConfig` + `make_checkpointer()` (async) + sync singleton |
| `store/` | 异步 store 工厂（与 checkpointer 独立配置） | `make_store()` (async CM) |

**怎么测**：

| 测试文件 | 覆盖范围 |
|----------|----------|
| `tests/runtime/test_entry.py` | `create_agent` 工厂 + 17 中间件排序 + 错误路径（mix 参数 / 缺依赖） |
| `tests/runtime/test_features.py` | `RuntimeFeatures` 默认值 + 3-state 语义（True/False/instance） |
| `tests/runtime/test_middleware_chain.py` | `assemble_chain` 全功能：链顺序 / 特性开关（**5.5** 新增 skills / guardrail / summarization_partitioner 集成） / `@Next`/`@Prev` 插入 / Clarification 始终在末位 |
| `tests/runtime/test_decorators.py` | `@Next` / `@Prev` 装饰器契约 |
| `tests/runtime/test_user_context.py` | `CurrentUser` Protocol + ContextVar 行为 + `resolve_user_id` 三态 |
| `tests/runtime/test_stream_bridge.py` | `StreamBridge` ABC + sentinels |
| `tests/runtime/test_thread_state.py` | `ThreadState` TypedDict + `merge_artifacts` / `merge_viewed_images` reducer |
| `tests/runtime/test_langgraph_integration.py` | `is_valid_thread_id` / `make_run_id` / `make_thread_config` |
| `tests/runtime/test_checkpointer.py` | 3 后端 checkpointer（sqlite/postgres 需要 extras） |
| `tests/runtime/test_store.py` | 3 后端 store（同上） |

**单测一条命令**：

```bash
# 跑某个文件
cd sdk-extraction/harness
uv run pytest tests/runtime/test_middleware_chain.py -v

# 跑某个测试
uv run pytest tests/runtime/test_middleware_chain.py::TestDefaultChain::test_clarification_is_last_by_default -v
```

**手验最短路径**（看 `create_agent` 真能跑）：

```python
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from agent_sdk import create_agent, RuntimeFeatures

model = FakeListChatModel(responses=["hi"])
agent = create_agent(model=model, features=RuntimeFeatures(sandbox=False))
# agent 现在是 langgraph 的 CompiledStateGraph，可 invoke
```

---

### 1.2 `agent_sdk/middlewares/` — 业务规则（14 个文件 + 1 子包）

**作用**：LangGraph `AgentMiddleware` 的具体实现。每个 middleware 一行职责。**注意：这里没有 sandbox 相关**（sandbox 在 `agent_sdk/sandbox/middleware.py`）。

| 文件 | 作用 | L 层 |
|------|------|------|
| `thread_data.py` | 创建/暴露 thread 的 workspace/uploads/outputs 三个目录 | L2 |
| `uploads.py` | 把用户上传的文件元数据注入到 LLM 上下文（`<uploaded_files>` 块） | L2 |
| `subagent_limit.py` | 单回合内 `task` 工具调用上限（默认 3，clamp [2,4]） | L2 |
| `view_image.py` | 拦截 `view_image` 完成，把图片 base64 注入到 LLM 上下文 | L2 |
| `title.py` | 第一轮后自动生成 thread 标题（需外部 model factory） | L2 |
| `clarification.py` | 拦截 `ask_clarification` 工具调用 → `Command(goto=END)` 中断 | L2 |
| `llm_error.py` | LLM 异常分类 + 重试 + 熔断器（`RetryConfig` + `CircuitBreakerConfig`） | L2 |
| `summarization.py` | token 超阈值时压缩旧消息（**async-only**）；提供 `skill_rescue_partitioner(skill_tool_names, max_preserved_skills=5)` 工厂构造可注入的 partitioner | L2 |
| `dangling_tool_call.py` | 修补无对应 `ToolMessage` 的 `AIMessage.tool_calls` | L3 |
| `deferred_tool_filter.py` | 隐藏 deferred 工具 schema（推 `tool_search` 让 LLM 自助激活） | L3 |
| `loop_detection.py` | 检测重复工具调用 → 软中断 | L3 |
| `token_usage.py` | 日志 `usage_metadata`（input/output/total tokens） | L3 |
| `tool_error_handling.py` | 工具异常 → 错误 `ToolMessage`（不中断 agent 循环） | L3 |
| `todo/` 子包 | `TodoMiddleware` + `TodoPrompts`（plan_mode 启用） | L2 |

**怎么测**：每个 middleware 一个测试文件（`tests/middlewares/test_*.py` + `tests/middlewares/todo/test_*.py`）。

| 测试文件 | 测什么 |
|----------|--------|
| `test_clarification.py` | 拦截路径 / `Command(goto=END)` / ToolMessage 名字 / `tool_name=` 自定义 |
| `test_subagent_limit.py` | clamp [2,4] / 截断超量 task 调用 / 保留 ID 一致 |
| `test_thread_data.py` | `path_provider` 注入 / lazy_init / 三个目录路径 |
| `test_uploads.py` | 注入 `<uploaded_files>` 块 / 保留 multimodal / 空文件回退 |
| `test_summarization.py` | async 路径 / hook 触发 / 自定义 partitioner / sync 路径 no-op / `skill_rescue_partitioner` 工厂 |
| `test_title.py` | 第一轮触发 / `model_factory` 注入 / prompts 覆盖 |
| `test_view_image.py` | 拦截 view_image 完成 / 注入图片详情 / 幂等 |
| `test_dangling_tool_call.py` | 修补孤立 tool_call / JSON 解析失败回退 |
| `test_deferred_tool_filter.py` | 隐藏 deferred schema / 错误消息文案 / `missing_id` sentinel |
| `test_loop_detection.py` | 同 call 重复检测 / 软中断 |
| `test_token_usage.py` | 解析 `usage_metadata` / 日志 |
| `test_tool_error_handling.py` | 异常 → `ToolMessage(status="error")` / 不中断循环 |
| `todo/test_middleware.py` + `todo/test_prompts.py` | TodoPrompts dataclass + TodoMiddleware 行为 |

**单测一条命令**：

```bash
uv run pytest tests/middlewares/ -v            # 跑全部 14 个
uv run pytest tests/middlewares/test_clarification.py -v
```

---

### 1.3 `agent_sdk/sandbox/` — 沙箱子系统（9 个文件 + 1 子包）

**作用**：沙箱 ABC + 沙箱 middleware + 命令审计 + 路径解析 + 7 个 sandbox 工具 + 文件操作锁 + host bash 安全策略。

**5.7 完成**：`tools.py`（`make_sandbox_tools` 工厂 + 7 个 `@tool`）、`path_resolver.py`、`security.py`、`search.py`、`exceptions.py`、`file_operation_lock.py` 全部落地。

| 文件 | 作用 |
|------|------|
| `base.py` | `Sandbox` ABC（`execute_command` / `read_file` / `write_file` / `list_dir` / `glob` / `grep` / `update_file`）+ `SandboxProvider` ABC（`acquire` / `get` / `release` / `shutdown`）+ `GrepMatch` dataclass |
| `middleware.py` | `SandboxMiddleware`（per-thread sandbox 生命周期：`acquire` on `before_agent` / `release` on `after_agent`；支持 `lazy_init`） |
| `exceptions.py` | 7 类 `SandboxError` 层级（`SandboxError` → `NotFoundError` / `RuntimeError` / `CommandError` / `FileError` → `PermissionError` / `FileNotFoundError`） |
| `file_operation_lock.py` | 进程级 per-`(sandbox_id, path)` 写锁（`WeakValueDictionary` + `threading.Lock`），防并发写冲突 |
| `search.py` | 纯 Python glob / grep walker（`find_glob_matches` / `find_grep_matches` / `is_binary_file` / VCS ignore patterns） |
| `security.py` | `HostBashPolicy` Protocol + `DefaultHostBashPolicy`（永远 deny）+ `ConfigurableHostBashPolicy`（回调注入）；brand-neutral 默认错误消息 |
| `path_resolver.py` | `SandboxPathResolver` + `SandboxToolsConfig` + `CustomMount` — 4 个 path family（user-data / skills / acp-workspace / custom-mount）+ 校验 / 解析 / masking / command-rewrite / cwd-prefix |
| `tools.py` | `make_sandbox_tools(sandbox_provider, resolver, host_bash_policy, name_prefix)` 工厂 → `SandboxToolsBundle`（`bash` / `ls` / `glob` / `grep` / `read_file` / `write_file` / `str_replace` 7 个 `@tool`） |
| `audit/__init__.py` | 审计子包导出 |
| `audit/default.py` | `DefaultAuditRules`（**无业务** — 全部 PASS） |
| `audit/middleware.py` | `SandboxAuditMiddleware`（`wrap_tool_call` / `awrap_tool_call` 拦截 bash 命令）+ 命令分类助手（`_split_compound_command` / `_classify_command`） |
| `audit/rules.py` | `AuditPattern` / `AuditRules` Protocol（`runtime_checkable`）/ `AuditVerdict` enum（BLOCK / WARN / PASS） |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/sandbox/test_base.py` | ABC 契约（不能实例化 / 抽象方法列表 / Protocol 形状） |
| `tests/sandbox/test_middleware.py` | `SandboxMiddleware` 生命周期 / lazy_init |
| `tests/sandbox/test_exceptions.py` | 7 类异常层级 + `__str__` 格式 + 继承关系 |
| `tests/sandbox/test_file_operation_lock.py` | 锁 key 构造 / 同 key 复用 / 互斥 / 不同 key 不互斥 |
| `tests/sandbox/test_search.py` | glob/grep walker / ignore patterns / 二进制跳过 / 符号链接跳过 / 大文件跳过 |
| `tests/sandbox/test_security.py` | `HostBashPolicy` Protocol / 默认 deny / `ConfigurableHostBashPolicy` 回调 / brand-neutral 消息 |
| `tests/sandbox/test_path_resolver.py` | 路径校验/解析/掩码 / bash 命令验证 / cd 安全 / bare root 拒绝 / 自定义挂载 |
| `tests/sandbox/test_tools.py` | 7 个 `@tool` 端到端 / 懒获取 / 本地沙箱路径策略 / 输出掩码 / truncation / `max_results` 上限 |
| `tests/sandbox/audit/test_rules.py` | `AuditPattern` 校验 / `AuditRules` Protocol |
| `tests/sandbox/audit/test_middleware.py` | `wrap_tool_call` 拦截 / 各种输入 |
| `tests/sandbox/audit/test_classification.py` | `_split_compound_command` / `_classify_command` 命令解析 |

**单测一条命令**：

```bash
uv run pytest tests/sandbox/ -v
```

---

### 1.4 `agent_sdk/paths/` — 路径子系统（3 个文件）

**作用**：**品牌无关**的路径解析层。PathProvider 是所有"路径相关业务"（workspace/uploads/outputs/skills/...）的注入点。

| 文件 | 作用 |
|------|------|
| `provider.py` | `PathProvider` Protocol（10 个方法）+ `VIRTUAL_PATH_PREFIX` 常量 |
| `default.py` | `DefaultPathProvider`（**无业务** — base 在 `./.agent-sdk`，无 `/mnt/user-data` 假设） |
| `resolver.py` | `VirtualPathResolver`（虚拟路径 ↔ 物理路径，含 path-traversal 防护） |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/paths/test_provider.py` | `PathProvider` Protocol 契约（用最小实现验证形状） |
| `tests/paths/test_default.py` | `DefaultPathProvider` 路径推导（**品牌无关验证**） |
| `tests/paths/test_resolver.py` | `VirtualPathResolver` 路径转换 + path-traversal 防护 |

---

### 1.5 `agent_sdk/memory/` — 记忆子系统（5 个文件）

**作用**：长期记忆数据 + 持久化 + middleware 注入。

| 文件 | 作用 |
|------|------|
| `schema.py` | `MemorySchema` Protocol（`get_user_profile` / `get_conversation_history` / `to_dict` / `from_dict` / `touch` / `empty`） |
| `default.py` | `DefaultMemorySchema`（**品牌无关** — 自由 KV bag） |
| `storage.py` | `MemoryStorage` ABC（`load` / `reload` / `save`）+ `FileMemoryStorage`（**用户隔离外置到 PathProvider**） |
| `updater.py` | `MemoryUpdater`（`update_section` 改写 + `clear` 清空） |
| `middleware.py` | `MemoryMiddleware`（**当前只读** — `before_agent` 注入 `get_user_profile()`；`after_agent` 排队写入是 5.x 后续工作） |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/memory/test_default.py` | `DefaultMemorySchema` 自由 KV 行为 |
| `tests/memory/test_deerflow.py` | `DeerFlowMemorySchema` 与 backend `create_empty_memory()` **字节级一致** |
| `tests/memory/test_storage.py` | `FileMemoryStorage` 持久化 + mtime 缓存 + 线程安全 |

---

### 1.6 `agent_sdk/subagents/` — 子代理子系统（4 个文件）

**作用**：多 agent 委派（一个 LLM 把任务派给"专才" agent）。

| 文件 | 作用 |
|------|------|
| `definition.py` | `SubagentDefinition` 数据类（`name` / `description` / `system_prompt` / `tools` / `model` / `max_turns` / `timeout_seconds`） |
| `registry.py` | `SubagentRegistry` Protocol |
| `default.py` | `DefaultSubagentRegistry`（**空**，无内置角色） |
| `executor.py` | `SubagentExecutor`（执行 + 后台任务管理）+ `SubagentResult` + `SubagentStatus`（COMPLETED/FAILED/CANCELLED/TIMED_OUT） |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/subagents/test_default.py` | `DefaultSubagentRegistry` 行为 |
| `tests/subagents/test_deerflow.py` | `DeerFlowSubagentRegistry` 重新录入 `general-purpose` / `bash` |
| `tests/subagents/test_executor.py` | `SubagentExecutor` 生命周期（同步测试覆盖部分逻辑） |

### 1.7.5 `agent_sdk/skills/` — Skills 子系统（5 个文件，5.5 新增）

**作用**：扫描 `SKILL.md` 文件 + 解析 YAML front-matter + 注入到 system prompt。**核心是 5.5 新增**。

| 文件 | 作用 |
|------|------|
| `types.py` | `Skill` dataclass（`name` / `description` / `category` / `skill_dir` / `enabled` / 容器路径助手） |
| `parser.py` | `parse_skill_file()` — 从 `SKILL.md` 读 YAML front-matter，构造 `Skill` |
| `loader.py` | `load_skills(skills_path, ...)` — 扫描 `public/` + `custom/` 目录；支持 `is_enabled` 回调 / `enabled_names` 集合 / `enabled_only` 过滤 |
| `manager.py` | 路径助手（`get_custom_skill_dir` / `public_skill_exists` / `validate_skill_name` / `ensure_safe_support_path`） |
| `middleware.py` | `SkillsMiddleware` — `before_model` 注入 `<available_skills>` 块到 system message；缓存 + `invalidate_cache()` |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/skills/test_types.py` | `Skill` 容器路径 + `__repr__` |
| `tests/skills/test_parser.py` | `parse_skill_file` 各种边界（缺字段 / 错 YAML / 错文件名） |
| `tests/skills/test_loader.py` | `load_skills` 扫描 / 排序 / 隐藏目录 / 启用过滤 |
| `tests/skills/test_manager.py` | 路径助手 + `validate_skill_name` + `ensure_safe_support_path` |
| `tests/skills/test_middleware.py` | `SkillsMiddleware` 注入 / 幂等 / 白名单 / 缓存失效 |

**单测一条命令**：

```bash
uv run pytest tests/skills/ -v
```

**手验最短路径**：

```python
from pathlib import Path
from agent_sdk.skills import load_skills, SkillsMiddleware

# 扫描一个 skills 根目录
skills = load_skills(Path("./skills"), enabled_only=True)
print([s.name for s in skills])

# 或直接挂到 chain
from agent_sdk.runtime import MiddlewareChainConfig, RuntimeFeatures
from agent_sdk import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel

agent = create_agent(
    model=FakeListChatModel(responses=["ok"]),
    features=RuntimeFeatures(skills=True, sandbox=False),
    l2_config=MiddlewareChainConfig(skills_path=Path("./skills")),
)
```

### 1.7.6 `agent_sdk/mcp/` — MCP 子系统（3 个文件，5.5 新增）

**作用**：MCP（Model Context Protocol）配置 + 工具加载。**`langchain-mcp-adapters` 是可选依赖**——没装时 `get_mcp_tools` 返回 `[]` 并 warn。

| 文件 | 作用 |
|------|------|
| `config.py` | `McpServerConfig` / `McpServersConfig`（Pydantic，**`type` Literal 校验**）+ `config_from_extensions_dict()` |
| `client.py` | `build_server_params()` / `build_servers_config()`（**纯函数** — 翻译 SDK 配置到 langchain-mcp-adapters 格式） |
| `tools.py` | `get_mcp_tools(servers)` async（懒加载 `langchain-mcp-adapters`）+ `list_mcp_tool_names()` |

**未在 SDK 版本（5.x follow-up）**：OAuth 头注入、`mcpInterceptors` 自定义拦截器、跨进程的 sync 包装线程池。计划见 `phase-5-l3-foundation.md`。

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/mcp/test_config.py` | Pydantic 模型 + 启用过滤 + `config_from_extensions_dict` |
| `tests/mcp/test_client.py` | `build_server_params` 各 transport 类型 + 错误路径 |
| `tests/mcp/test_tools.py` | `list_mcp_tool_names` + 无服务器时早返回 |

**单测一条命令**：

```bash
uv run pytest tests/mcp/ -v
```

**手验最短路径**：

```python
from agent_sdk.mcp import McpServersConfig, McpServerConfig, get_mcp_tools
import asyncio

servers = McpServersConfig(
    servers={
        "filesystem": McpServerConfig(type="stdio", command="mcp-server-filesystem"),
    }
)
tools = asyncio.run(get_mcp_tools(servers))
print([t.name for t in tools])
```

---

### 1.7 `agent_sdk/guardrails/` — 工具调用授权（3 个文件）

**作用**：工具调用前的 allow/deny 决定。

| 文件 | 作用 |
|------|------|
| `provider.py` | `GuardrailRequest` / `GuardrailDecision` / `GuardrailReason` dataclass + `GuardrailProvider` Protocol（`runtime_checkable`） |
| `builtin.py` | `AllowlistProvider`（**参考实现** — 简单的 allowlist 拒绝机制） |
| `middleware.py` | `GuardrailMiddleware`（**5.5 新增**）— 包装一个 `GuardrailProvider`，在 `wrap_tool_call` / `awrap_tool_call` 钩子里同步/异步调用，决定 allow/deny；`fail_closed` flag 控制 provider 抛错时的行为；`GraphBubbleUp` 透传以保留 langgraph 控制流 |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/guardrails/test_provider.py` | 数据类 + Protocol 形状 + `AllowlistProvider` 行为 |
| `tests/guardrails/test_middleware.py` | `GuardrailMiddleware` 同步/异步路径 + allow/deny + fail_closed/open + `GraphBubbleUp` 透传 |

---

### 1.8 `agent_sdk/tools/` — 工具子系统（9 个文件）

**作用**：built-in tool 的工厂函数（每个工具一个 `make_*_tool(tool_name=...)` 构造器）+ 工具加载器。

| 文件 | 作用 | 状态 |
|------|------|------|
| `factory.py` | 工具注册/重命名抽象 | ✅ |
| `loader.py` | `load_tools()` — 从 `ToolConfig`（class path）按组过滤+去重加载工具 | ✅ |
| `ask_clarification.py` | `make_ask_clarification_tool` — 5 个 `clarification_type` Literal + `context` + `options` + `return_direct=True` | ✅ |
| `view_image.py` | `make_view_image_tool` — **当前是 stub**（返回 `'ok'`；后续接入 sandbox 后实现 MIME 检测 / base64） | ⚠️ stub |
| `task.py` | `make_task_tool` — **当前是 stub**（返回 `''`；后续接入 `SubagentExecutor` 后实现） | ⚠️ stub |
| `present_files.py` | `make_present_files_tool` | ✅ |
| `setup_agent.py` | `make_setup_agent_tool` | ✅ |
| `invoke_acp_agent.py` | `make_invoke_acp_agent_tool` | ✅ |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/tools/test_factory.py` | 所有 `make_*_tool` 工厂 + `tool_name=` 注入 |
| `tests/test_tools_loader.py` | `load_tools` + `ToolConfig` + `LoadResult` + 去重 + group 过滤 |

---

### 1.9 `agent_sdk/presets/deerflow/` — DeerFlow 业务预设（5 个文件 + 1 子包）

**作用**：**DeerFlow 风味** 的实现。`agent_sdk/*` 是品牌无关的，**这个文件夹才有 DeerFlow 业务假设**（`/mnt/user-data` 路径、DeerFlow 记忆结构、DeerFlow 审计规则、DeerFlow todo prompt 文案）。

| 文件 | 作用 |
|------|------|
| `paths.py` | `DeerFlowPathProvider`（实现 `/mnt/user-data/{workspace,uploads,outputs}` 风格 + 路径校验 + host bash 允许） |
| `memory.py` | `DeerFlowMemorySchema`（`workContext` / `personalContext` / `topOfMind` 三段） |
| `audit.py` | `DeerFlowAuditRules`（一套完整的命令分类规则 — 与 backend `sandbox_audit_middleware` 字节级一致） |
| `subagents.py` | `DeerFlowSubagentRegistry`（重新录入 `general-purpose` / `bash`） |
| `prompts/todo.py` | `DEERFLOW_TODO_SYSTEM_PROMPT` / `DEERFLOW_TODO_TOOL_DESCRIPTION` / `DEERFLOW_TODO_PROMPTS`（与 backend 文案字节级一致） |

**怎么测**：

| 测试文件 | 测什么 |
|----------|--------|
| `tests/presets/deerflow/test_audit.py` | `DeerFlowAuditRules` 重新录入的 fixture 集 |
| `tests/presets/deerflow/test_todo_prompts.py` | 文案字节级一致 |

注意：`tests/paths/test_deerflow.py` 测的是 `DeerFlowPathProvider`（虽然放在 `tests/paths/`，逻辑上是 preset 的一部分）。

---

### 1.10 `agent_sdk/models/` — 模型工厂（1 个文件）

**作用**：从 `ModelConfig` 构造 langchain chat model。

| 文件 | 作用 |
|------|------|
| `factory.py` | `ModelConfig` + `create_chat_model()`（class path 加载 + thinking 切换 + `stream_usage` 默认 + tracing callback 注入） |

**怎么测**：`tests/test_models.py`

---

### 1.11 `agent_sdk/tracing/` — 追踪回调（1 个文件）

**作用**：构造 LangSmith / Langfuse callback handlers（**可选依赖** — 缺包时 WARN 不 raise）。

| 文件 | 作用 |
|------|------|
| `factory.py` | `TracingConfig` / `LangSmithConfig` / `LangfuseConfig` / `build_tracing_callbacks()` |

**怎么测**：`tests/test_tracing.py`

---

### 1.12 `agent_sdk/reflection/` — 反射工具（1 个文件）

**作用**：从字符串 `"module.path:attribute"` 加载对象（class path 配置用）。

| 文件 | 作用 |
|------|------|
| `resolvers.py` | `resolve_class[T]` / `resolve_variable[T]`（含 11 个 module-to-package 提示 — 缺包时给清晰的 `uv add xxx` 提示） |

**怎么测**：`tests/test_reflection.py`

---

### 1.13 `agent_sdk/utils/` — 通用工具（3 个文件）

**作用**：跨子系统的依赖无关小工具。

| 文件 | 作用 |
|------|------|
| `network.py` | `PortAllocator`（线程安全）+ `get_free_port()` / `release_port()`（用于本地 dev server / 子进程端口分配） |
| `thread.py` | `extract_thread_id()` / `resolve_thread_id()` — 从 thread_data / runtime 提取 thread id 的共享 helper（消除 tools / path_resolver / sandbox middleware / summarization 之间的重复代码） |

**怎么测**：`tests/utils/test_network.py`（thread 工具通过各自调用方的测试间接覆盖）

---

## 1.14 模块计数速查（5.7 完成时）

| 类别 | 源文件数 | 测试文件数 |
|------|----------|------------|
| `agent_sdk/runtime/`（含 checkpointer + store 子包） | 15 | 10 |
| `agent_sdk/middlewares/`（含 todo 子包） | 17 | 15 |
| `agent_sdk/sandbox/`（含 audit 子包） | 13 | 11 |
| `agent_sdk/memory/` | 5 | 3 |
| `agent_sdk/subagents/` | 4 | 3 |
| `agent_sdk/guardrails/` | 3 | 2 |
| `agent_sdk/skills/` | 5 | 5 |
| `agent_sdk/mcp/` | 3 | 3 |
| `agent_sdk/paths/` | 3 | 4 |
| `agent_sdk/presets/deerflow/`（含 prompts 子包） | 6 | 2 |
| `agent_sdk/tools/` | 9 | 2 |
| `agent_sdk/tracing/` | 1 | 1 |
| `agent_sdk/models/` | 1 | 1 |
| `agent_sdk/reflection/` | 1 | 1 |
| `agent_sdk/utils/` | 3 | 1 |
| `agent_sdk/__init__.py` | 1 | 0 |
| `tests/integration/` | — | 1 |
| **合计** | **90** | **65** |

---

## 2. 跨文件夹关系图

```
                ┌────────────────────────────────────────────┐
                │  create_agent (runtime/entry.py)           │
                │  唯一公开入口                                │
                └────────────────────────────────────────────┘
                          │                │
                          ▼                ▼
                ┌────────────────────┐  ┌──────────────────────┐
                │ features.py        │  │ middleware_chain.py  │
                │ RuntimeFeatures    │  │ assemble_chain()     │
                │ (声明)              │  │ (装配)                │
                └────────────────────┘  └──────────────────────┘
                          │                │
                          │                │  L2 依赖注入
                          │                ▼
                          │       ┌──────────────────────────────────┐
                          │       │  MiddlewareChainConfig           │
                          │       │  (path_provider / sandbox_...    │
                          │       │   memory_storage / model / ...)  │
                          │       └──────────────────────────────────┘
                          │                │
                          ▼                ▼
                ┌──────────────────────────────────────────────────┐
                │  middlewares/    +  sandbox/audit/ + memory/     │
                │  (17 文件)         (4 文件)        (5 文件)       │
                │  19 个 AgentMiddleware 实现                       │
                └──────────────────────────────────────────────────┘
                          │                │                │
                          ▼                ▼                ▼
                ┌──────────────────┐  ┌────────────────────────────┐
                │  sandbox/base.py │  │  tools/  (7 文件)           │
                │  Sandbox ABC     │  │  ask_clarification / view  │
                │  SandboxProvider │  │  task / present_files / .. │
                │  ABC             │  │                            │
                └──────────────────┘  └────────────────────────────┘
                          │
                          ▼
                ┌──────────────────────────────────────────────────┐
                │  presets/deerflow/  (6 文件)                      │
                │  DeerFlow 业务实现（paths/memory/audit/...）     │
                │  → 注入上面的 Protocol                            │
                └──────────────────────────────────────────────────┘
```

**关键设计**：`agent_sdk/{paths,memory,subagents,sandbox,audit,guardrails}/*` 是 **Protocol + 默认空实现**；`agent_sdk/presets/deerflow/*` 是 **DeerFlow 业务实现**。其他项目可以仿照 `presets/deerflow/` 写自己的 preset。

---

## 3. 怎么测（5 条常用命令）

### 3.1 跑全部测试

```bash
cd sdk-extraction/harness
uv run pytest                       # 1080 个测试，~8s
uv run pytest -v                    # 加 -v 看每个 case 名
uv run pytest -x                    # 遇错即停
uv run pytest --tb=short            # 失败时只显示一行 traceback
```

### 3.2 跑某个子系统

```bash
uv run pytest tests/middlewares/ -v          # 全部 15 个 middleware 测试
uv run pytest tests/runtime/ -v              # 装配层全部
uv run pytest tests/sandbox/ -v              # 沙箱
uv run pytest tests/memory/ -v               # 记忆
uv run pytest tests/subagents/ -v            # 子代理
uv run pytest tests/guardrails/ -v           # 守卫（含 middleware）
uv run pytest tests/skills/ -v               # 5.5 新增：skills 子系统
uv run pytest tests/mcp/ -v                  # 5.5 新增：MCP 子系统
uv run pytest tests/paths/ -v                # 路径
uv run pytest tests/presets/ -v              # DeerFlow 预设
```

### 3.3 跑单个文件 / 单个 case

```bash
# 单个文件
uv run pytest tests/middlewares/test_clarification.py -v

# 单个 class
uv run pytest tests/middlewares/test_clarification.py::TestClarificationIntercepts -v

# 单个 case
uv run pytest tests/middlewares/test_clarification.py::TestClarificationIntercepts::test_ask_clarification_returns_command_end -v
```

### 3.4 跑特定子集（按关键字）

```bash
uv run pytest -k "sandbox" -v         # 名字含 sandbox
uv run pytest -k "memory" -v          # 名字含 memory
uv run pytest -k "chain" -v           # 名字含 chain
```

### 3.5 看覆盖率（如果装了 coverage）

```bash
uv run pytest --cov=agent_sdk --cov-report=term-missing
```

---

## 4. 怎么手验（无 pytest 的情况下跑一遍）

### 4.1 最小烟雾测试（确认 `create_agent` 能装）

```python
# scripts/smoke_create_agent.py
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from agent_sdk import create_agent, RuntimeFeatures

model = FakeListChatModel(responses=["Hello, world!"])
agent = create_agent(model=model, features=RuntimeFeatures(sandbox=False))

result = agent.invoke({"messages": [("user", "Say hello")]})
print(result["messages"][-1].content)   # → "Hello, world!"
```

### 4.2 验证 L2 依赖注入

```python
from pathlib import Path
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from agent_sdk import create_agent, RuntimeFeatures
from agent_sdk.paths import DefaultPathProvider
from agent_sdk.runtime import MiddlewareChainConfig

model = FakeListChatModel(responses=["ok"])
agent = create_agent(
    model=model,
    features=RuntimeFeatures(sandbox=True, vision=True, subagent=True),
    l2_config=MiddlewareChainConfig(
        path_provider=DefaultPathProvider(base_dir=Path("./my-data")),
    ),
)
print("Chain assembled OK")
```

### 4.3 验证 DeerFlow preset 字节级一致

```python
from agent_sdk.presets.deerflow import DeerFlowPathProvider
from pathlib import Path

p = DeerFlowPathProvider(base_dir=Path("/tmp/test"))
assert p.virtual_prefix == "/mnt/user-data"
assert str(p.workspace_dir("thread-1")) == "/tmp/test/threads/thread-1/user-data/workspace"
```

### 4.4 验证 middleware 排序

```python
from agent_sdk import RuntimeFeatures
from agent_sdk.runtime import MiddlewareChainConfig, assemble_chain

chain, _ = assemble_chain(
    RuntimeFeatures(sandbox=False),
    MiddlewareChainConfig(),
)
for i, m in enumerate(chain):
    print(f"[{i}] {type(m).__name__}")
# 最后一行必须是 ClarificationMiddleware（不变量）
assert type(chain[-1]).__name__ == "ClarificationMiddleware"
```

---

## 5. 5 分钟自测清单

如果你只想快速 sanity check SDK 没坏：

```bash
cd sdk-extraction/harness

# 1. ruff 静态检查
uv run ruff check .

# 2. 跑全部 pytest
uv run pytest

# 3. 验证 ADR-010：0 个 backend/deerflow/app 导入
grep -rE "^import |^from " agent_sdk/ --include='*.py' | grep -E "from (backend|deerflow|app)\." | wc -l
# 期望输出：0

# 4. 验证 backend/ 未触碰
cd ../.. && git status backend
# 期望输出：nothing to commit, working tree clean
```

4 步全过 = SDK 健康。

---

## 6. 已知 stub 与计划归属

| 模块 | 状态 | 归属 |
|------|------|------|
| `tools/view_image.py` | ⚠️ stub（返回 `'ok'`） | 阶段 6 集成（MIME 检测 / base64 需 sandbox 后端） |
| `tools/task.py` | ⚠️ stub（返回 `''`） | 阶段 6 集成（依赖 `SubagentExecutor` 完整化） |
| `memory/middleware.py` 的 `after_agent` 写入 | ⚠️ stub（只读） | 5.x memory 完整化（依赖 `get_memory_queue` / `detect_correction` 等 backend 模块） |
| `mcp/oauth.py` | ❌ 未抽 | 5.x follow-up（与 auth 子系统耦合） |
| `mcp/mcpInterceptors` 自定义拦截器 | ❌ 未抽 | 5.x follow-up |
| `skills/installer.py` / `security_scanner.py` / `validation.py` | ❌ 未抽 | 5.x follow-up（installer 强依赖 backend 业务） |
| `middlewares/loop_detection._stable_tool_key` 的 read_file/write_file 分桶 | ⚠️ stub（naive JSON dump） | 阶段 6 集成 |
| `middlewares/uploads` 的 document outline 提取 | ⚠️ stub（无 outline） | plan 显式 first-cut omission |
| `middleware_chain` 装 TokenUsage/DeferredToolFilter | ⚠️ 总是开启（无 config flag） | 后续清理 |

**5.5 已解决**（5.8 体检遗留）：
- ✅ `summarization.skill_rescue_partitioner` 工厂（用 `MiddlewareChainConfig.summarization_partitioner` 注入）
- ✅ `skills/SkillsMiddleware`（`<available_skills>` 块注入；`MiddlewareChainConfig.skills_path` 注入）
- ✅ `guardrails/GuardrailMiddleware`（用 `MiddlewareChainConfig.guardrail_provider` 注入）

详细见 `docs/03-status/changelog.md` 的"5.8 接口对齐体检"章节。

---

## 7. 相关文档

- [`01-design/feature-inventory.md`](../01-design/feature-inventory.md) — 整体特性清单
- [`03-status/progress.md`](../03-status/progress.md) — 阶段进度
- [`03-status/changelog.md`](../03-status/changelog.md) — 变更日志
- [`02-plan/phase-5-l3-foundation.md`](../02-plan/phase-5-l3-foundation.md) — L3 通用层详细计划
- `../05-archive/` — 历史分析（已封存）

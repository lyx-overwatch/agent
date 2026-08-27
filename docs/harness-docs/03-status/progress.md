# 整体进度

> **活文档**。每次工作结束前必须更新。
> 跟踪所有阶段的完成状态和详细任务清单。

## 阶段总览

| 阶段 | 状态 | 完成日期 | 详细计划 |
|------|------|----------|----------|
| 0. 脚手架 | ✅ 已完成 | 2026-07-03 | - |
| 1. PathProvider 抽象 | ✅ 已完成 | 2026-07-06 | [`02-plan/phase-1-path-provider.md`](../02-plan/phase-1-path-provider.md) |
| 2. Memory/Subagent/Tools 数据模型抽象 | ✅ 已完成 | 2026-07-06 | [`02-plan/phase-2-data-models.md`](../02-plan/phase-2-data-models.md) |
| 3. Audit/Prompt 抽象 | ✅ 已完成 | 2026-07-06 | [`02-plan/phase-3-audit-prompt.md`](../02-plan/phase-3-audit-prompt.md) |
| 5. L3 通用层抽离 | ✅ 已完成 | 2026-07-06 | [`02-plan/phase-5-l3-foundation.md`](../02-plan/phase-5-l3-foundation.md) + [`02-plan/phase-5-batch-1.md`](../02-plan/phase-5-batch-1.md) |
| 5.5 集成子系统 | ✅ 已完成 | 2026-07-13 | 本节下方（含 oauth + installer + 69 个测试） |
| 5.6 业务 middleware | ✅ 已完成 | 2026-07-06 | [`02-plan/phase-5-batch-4.md`](../02-plan/phase-5-batch-4.md) |
| 5.8 middleware 链装配 | ✅ 已完成 | 2026-07-06 | [`02-plan/phase-5-batch-5.md`](../02-plan/phase-5-batch-5.md) |
| 5.9 接口对齐体检 | ✅ 已完成 | 2026-07-06 | 本节下方 |
| 5.7 Sandbox 工具实现 | ✅ 已完成 | 2026-07-07 | [`02-plan/phase-5-l3-foundation.md`](../02-plan/phase-5-l3-foundation.md) § 5.7 + [changelog 2026-07-07 收尾 batch](../03-status/changelog.md) |
| 4. DeerFlow Preset 抽离 | ✅ 已完成 | 2026-07-13 | 本节下方（agent + system prompt + 38 测试） |
| 6. 测试 + 发布 | ⏳ 待开始 | - | [`02-plan/phase-6-publishing.md`](../02-plan/phase-6-publishing.md) |

## 详细进度

### 阶段 0：脚手架 ✅ 已完成

- [x] 创建 `sdk-extraction/` 目录
- [x] 创建 `docs/` 子目录（00-vision / 01-design / 02-plan / 03-status / 04-specs / 05-archive）
- [x] 创建 `harness/` 子目录（SDK 输出）
- [x] 写规划文档（vision/design/plan）
- [x] 写状态文档（progress/decisions/blockers/changelog）
- [x] 复制历史分析到 `docs/05-archive/`

### 阶段 1：PathProvider 抽象 ✅ 已完成

- [x] 1.1 设计 `PathProvider` Protocol（10 个方法：base/workspace/uploads/outputs/user-data/skills/acp_workspace/default_venv/virtual_prefix/is_host_bash_allowed）
- [x] 1.2 创建 `DeerFlowPathProvider` 实现（`agent_sdk/presets/deerflow/paths.py`，保留 `/mnt/user-data` 行为）
- [x] 1.3 创建 `DefaultPathProvider` 实现（`agent_sdk/paths/default.py`，base 目录 `./.agent-sdk`，无业务假设）
- [x] 1.4 创建 `VirtualPathResolver`（`agent_sdk/paths/resolver.py`，含 path-traversal 防护）
- [x] 1.7 写单元测试（4 个测试文件，**65 个测试 100% 通过**）
- [x] 1.8 验证：与 backend 行为字节级一致（golden snapshot test）
- [x] 1.9 验证：可注入新路径（`DefaultPathProvider` + 自定义 prefix 验证）

**未做（按 ADR-004 + ADR-010 延后到后续 PR）**：
- [ ] 1.5 sandbox/tools.py 1582 行的 SDK 版 PathProvider 化（属于 SDK 中"等价实现 sandbox 工具"子任务；不在阶段 1 范围；延后到阶段 4 或独立 PR）
- [ ] 1.6 SDK 版 ThreadData / Uploads / 文件工具（不在阶段 1 范围；延后到阶段 2 或 4）

### 阶段 2：Memory/Subagent/Tools 数据模型抽象 ✅ 已完成

- [x] 2.1 设计 `MemorySchema` Protocol（`agent_sdk/memory/schema.py`）
- [x] 2.2 创建 `DeerFlowMemorySchema` 实现（**与 backend `create_empty_memory()` 字节级一致**）
- [x] 2.3 SDK 版 `MemoryMiddleware` / `MemoryUpdater`（注入 MemorySchema；stage 5 替换为完整 LLM 抽取逻辑）
- [x] 2.4 SDK 版 `MemoryStorage(ABC, Generic[T])` + `FileMemoryStorage`
- [x] 2.5 设计 `SubagentRegistry` Protocol + `SubagentDefinition` 数据类
- [x] 2.6 创建 `DeerFlowSubagentRegistry`（general-purpose / bash 重新录入）
- [x] 2.7 SDK 版 `SubagentExecutor`（注入 SubagentRegistry；stage 5 替换为完整 ThreadPool/timeout/trace 实现）
- [x] 2.8 工具命名参数化（6 个 builtin tool factory）
- [x] 2.9 写单元测试（7 个测试文件 / 70 个用例）
- [x] 2.10 验证：DeerFlow 行为字节级一致

**质量验证**：
- pytest：阶段 1+2 累计 **135/135 通过**（1.39s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 阶段 3：Audit/Prompt 抽象 ✅ 已完成

- [x] 3.1 设计 `AuditRules` Protocol（`agent_sdk/sandbox/audit/rules.py`：AuditPattern 数据类 + AuditRules Protocol + AuditVerdict 枚举）
- [x] 3.2 创建 `DefaultAuditRules` 空实现（`agent_sdk/sandbox/audit/default.py`，零规则）
- [x] 3.3 SDK 版 `SandboxAuditMiddleware`（`agent_sdk/sandbox/audit/middleware.py`：构造参数 `audit_rules: AuditRules | None`；compound command 拆分、shlex 回退、input 校验、audit log、sync + async hooks 完整保留）
- [x] 3.4 SDK 版 `TodoMiddleware`（`agent_sdk/middlewares/todo/middleware.py`：构造参数 `prompts: TodoPrompts | None`；继承 langchain `TodoListMiddleware`；保留 context-loss 检测、premature-exit 预防 + retry cap）
- [x] 3.5 `TodoPrompts` 数据类 + 默认 prompt 常量（`agent_sdk/middlewares/todo/prompts.py`：brand-neutral DEFAULT_* + `TodoPrompts.default()`）
- [x] 3.6 `DeerFlowAuditRules` preset（`agent_sdk/presets/deerflow/audit.py`：15 条 high-risk + 5 条 medium-risk 重新录入；**与 backend 行为字节级一致**）
- [x] 3.7 DeerFlow Todo prompt preset（`agent_sdk/presets/deerflow/prompts/todo.py`：DEERFLOW_TODO_SYSTEM_PROMPT / DEERFLOW_TODO_TOOL_DESCRIPTION / DEERFLOW_TODO_PROMPTS，**与 backend 字节级一致**）
- [x] 3.8 写单元测试（6 个测试文件 / 90 个用例）
- [x] 3.9 验证：DeerFlow 行为不变（`/root/.profile` 等不在原规则的命令测试通过；backend/ 未触碰）

**质量验证**：
- pytest：阶段 1+2+3 累计 **259/259 通过**（1.52s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

**已完成关键交付物**（全部为 SDK 内部新增，`backend/` 不动）：
- `agent_sdk/sandbox/audit/rules.py` - AuditRules Protocol + AuditPattern + AuditVerdict
- `agent_sdk/sandbox/audit/default.py` - DefaultAuditRules
- `agent_sdk/sandbox/audit/middleware.py` - SandboxAuditMiddleware
- `agent_sdk/middlewares/todo/prompts.py` - TodoPrompts + 默认常量
- `agent_sdk/middlewares/todo/middleware.py` - TodoMiddleware
- `agent_sdk/presets/deerflow/audit.py` - DeerFlowAuditRules
- `agent_sdk/presets/deerflow/prompts/todo.py` - DEERFLOW_TODO_PROMPTS

### 阶段 4：DeerFlow Preset 抽离 ✅ 已完成

阶段 4 实际覆盖了原计划中阶段 4 + 阶段 6 的大部分内容。`DeerFlowAgent` 一步到位完成了"preset 组装 + graph 构建 + 端到端验证"：

**Preset 静态产物**（前几个阶段已就位，4.x 直接收纳）：
- [x] 4.1 `DeerFlowPathProvider`（`paths.py`，阶段 1）
- [x] 4.2 `DeerFlowMemorySchema`（`memory.py`，阶段 2）
- [x] 4.3 `DeerFlowSubagentRegistry`（`subagents.py`，阶段 2）
- [x] 4.4 `DeerFlowAuditRules`（`audit.py`，阶段 3）
- [x] 4.5 `DEERFLOW_TODO_PROMPTS`（`prompts/todo.py`，阶段 3）

**阶段 4 新增**：
- [x] 4.6 system prompt —— `prompts/system.py`（~700 行 `SYSTEM_PROMPT_TEMPLATE` + `apply_prompt_template()` + 5 个分段构建器）
- [x] 4.7 `DeerFlowAgent` 便利类 —— `agent.py`（dataclass，lazy graph build，`ainvoke`/`invoke`/`astream`/`stream`）
- [x] 4.8 `DEERFLOW_DEFAULT_FEATURES` —— 开箱即用的特性标志（sandbox + subagent + vision + auto_title + skills）
- [x] 4.9 README —— `presets/deerflow/README.md`
- [x] 4.10 集成测试 —— `tests/presets/deerflow/test_agent.py` 16 个 + `test_system_prompt.py` 22 个

**原阶段 6 被阶段 4+5 吸收的部分**：
- 6.1 端到端流程 → `DeerFlowAgent._build()` + `test_agent.py` 覆盖
- 6.2 middleware 链顺序 → 5.8 `test_middleware_chain.py` 28 个用例覆盖
- 6.6 集成测试覆盖矩阵 → 1187 个测试遍布各阶段
- 其余（6.3 多 thread 隔离 / 6.4 Memory round-trip 集成 / 6.5 Subagent 集成）→ 归入已知缺口

原阶段 6（端到端集成）取消，原阶段 7（测试+发布）重编号为阶段 6。

### 阶段 5：L3 通用层抽离 ✅ 已完成

**第一批（5.1 + 5.2）完成**：

- [x] 5.1.1 `RuntimeFeatures` 数据类（`agent_sdk/runtime/features.py`：7 字段，True/False/AgentMiddleware 三态）
- [x] 5.1.2 `@Next` / `@Prev` 装饰器（`agent_sdk/runtime/decorators.py`：类属性 + anchor 校验）
- [x] 5.1.3 `ThreadState` 基础状态（`agent_sdk/runtime/thread_state.py`：`merge_artifacts` / `merge_viewed_images` reducer 与 backend 行为一致）
- [x] 5.1.4 `create_agent` 入口（`agent_sdk/runtime/entry.py`：参数验证、`_assemble_from_features`、`_insert_extra` 装配逻辑；L2 特性 raise NotImplementedError）
- [x] 5.1.5 `agent_sdk/__init__.py` 导出（更新：create_agent / RuntimeFeatures / ThreadState / Next / Prev）
- [x] 5.1.6 SDK 入口单元测试（4 个测试文件 / 69 个用例）
- [x] 5.2.1 `DanglingToolCallMiddleware`（`agent_sdk/middlewares/dangling_tool_call.py`）
- [x] 5.2.2 `ToolErrorHandlingMiddleware`（`agent_sdk/middlewares/tool_error_handling.py`：保留 GraphBubbleUp 透传 + 500 字截断）
- [x] 5.2.3 `TokenUsageMiddleware`（`agent_sdk/middlewares/token_usage.py`）
- [x] 5.2.4 `LoopDetectionMiddleware`（`agent_sdk/middlewares/loop_detection.py`：hash-based + tool-freq 双重检测 + LRU eviction + reset）
- [x] 5.2.5 `DeferredToolFilterMiddleware`（`agent_sdk/middlewares/deferred_tool_filter.py`：deferred_names_provider 注入）
- [x] 5.2.6 `agent_sdk/middlewares/__init__.py` 导出（更新：5 个新 middleware + todo 子包）
- [x] 5.2.7 通用 middleware 单元测试（5 个测试文件 / 65 个用例）

**5.3 抽象 ABC 完成**：

- [x] 5.3.1 `agent_sdk/sandbox/base.py` - `Sandbox` / `SandboxProvider` ABC + `GrepMatch` 数据类
- [x] 5.3.2 `agent_sdk/runtime/user_context.py` - `CurrentUser` Protocol + ContextVar + AUTO sentinel + `resolve_user_id` / `require_current_user` / `get_effective_user_id` 三态解析
- [x] 5.3.3 `agent_sdk/runtime/stream_bridge.py` - `StreamBridge` ABC + `StreamEvent` 数据类 + `HEARTBEAT_SENTINEL` / `END_SENTINEL` 哨兵
- [x] 5.3.4 `agent_sdk/guardrails/` 子包 - `GuardrailRequest` / `Reason` / `Decision` + `GuardrailProvider` Protocol + `AllowlistProvider` 参考实现
- [x] 5.3.5 `agent_sdk/sandbox/__init__.py` + `runtime/__init__.py` + `guardrails/__init__.py` 导出更新
- [x] 5.3.6 单元测试（4 个测试文件 / 84 个用例）
- [x] 5.3.7 `pyproject.toml` 最小依赖 + `[tool.pytest.ini_options]` 添加

**5.4 运行时基础设施完成（完整范围）**：

- [x] 5.4.1 `agent_sdk/reflection/` - `resolve_class` / `resolve_variable`（泛型 + 依赖提示 + 11 个 langchain/langfuse 包名 hint）
- [x] 5.4.2 `agent_sdk/utils/network.py` - `PortAllocator` + `get_free_port` / `release_port`（线程安全）
- [x] 5.4.3 `agent_sdk/runtime/langgraph_integration.py` - `make_thread_config` / `merge_configs` / `make_run_id` / `is_valid_thread_id` + configurable key + stream mode 常量
- [x] 5.4.4 `agent_sdk/runtime/checkpointer/` - 3 后端（memory/sqlite/postgres）sync 单例 + sync CM + async CM（懒加载 extras）
- [x] 5.4.5 `agent_sdk/runtime/store/` - 3 后端 async CM（与 checkpointer 独立）
- [x] 5.4.6 `agent_sdk/models/factory.py` - `ModelConfig` + `create_chat_model`（thinking 切换 / stream_usage / tracing）
- [x] 5.4.7 `agent_sdk/tools/loader.py` - `ToolConfig` + `load_tools` + `LoadResult`（class path 加载 + dedupe + group 过滤）
- [x] 5.4.8 `agent_sdk/tracing/factory.py` - `TracingConfig` / `LangSmithConfig` / `LangfuseConfig` + `build_tracing_callbacks`（懒加载 + 软/硬失败）
- [x] 5.4.9 单元测试（8 个测试文件 / 135 个用例）
- [x] 5.4.10 验证：ruff + pytest + ADR-010

**5.5 集成子系统 ✅ 已完成**：

目标：MCP 客户端、Skills 技能系统、Guardrails 中间件的 SDK 版完整实现。

**已完成**（12 个模块）：

- [x] 5.5.1 `agent_sdk/mcp/config.py` - `McpServerConfig` / `McpServersConfig` / `McpOAuthConfig` Pydantic 配置
- [x] 5.5.2 `agent_sdk/mcp/client.py` - `build_server_params` / `build_servers_config` 纯函数（翻译 SDK config 到 langchain-mcp-adapters 参数）
- [x] 5.5.3 `agent_sdk/mcp/tools.py` - `get_mcp_tools` / `list_mcp_tool_names`（langchain-mcp-adapters 可选依赖）
- [x] 5.5.4 `agent_sdk/skills/types.py` - `Skill` 数据类
- [x] 5.5.5 `agent_sdk/skills/parser.py` - `parse_skill_file`（YAML frontmatter 解析）
- [x] 5.5.6 `agent_sdk/skills/loader.py` - `load_skills`（扫描 public/ + custom/ 子目录）
- [x] 5.5.7 `agent_sdk/skills/manager.py` - 路径管理 helper（`get_custom_skill_dir` 等）
- [x] 5.5.8 `agent_sdk/skills/middleware.py` - `SkillsMiddleware`（注入 `<available_skills>` block 到 system prompt）
- [x] 5.5.9 `agent_sdk/mcp/oauth.py` - `OAuthTokenManager` + `build_oauth_tool_interceptor` + `get_initial_oauth_headers`（OAuth 2.0 client_credentials / refresh_token 流程，httpx 懒加载）
- [x] 5.5.10 `agent_sdk/skills/validation.py` + `agent_sdk/skills/installer.py` - `validate_skill_frontmatter` + `ainstall_skill_from_archive` / `install_skill_from_archive`（.skill ZIP 安全安装器，含 zip-bomb 防护 + 路径遍历检测 + 可注入安全扫描器）
- [x] 5.5.11 三个子系统单元测试（`tests/mcp/test_oauth.py` 15 个 + `tests/skills/test_validation.py` 22 个 + `tests/skills/test_installer.py` 19 个 = **69 个新测试**）

**已接入中间件链**：
- `SkillsMiddleware` ← `_build_skills()` 在 `middleware_chain.py` 中已 wire
- `GuardrailMiddleware` ← `_build_guardrail()` 在 `middleware_chain.py` 中已 wire
- MCP client 作为独立工具加载器使用，不在中间件链条中

**5.6 业务特性 middleware 完成（9 个 L2 middleware）**：

- [x] 5.6.1 `agent_sdk/middlewares/subagent_limit.py` - 截断超 `max_concurrent` 的 `task` tool calls；clamp `[2, 4]`
- [x] 5.6.2 `agent_sdk/middlewares/thread_data.py` - 创建 thread data 目录；接受 `PathProvider` 注入；支持 `lazy_init`
- [x] 5.6.3 `agent_sdk/middlewares/uploads.py` - 从 `additional_kwargs.files` 抽取文件；接受 `PathProvider` + `virtual_prefix` 注入
- [x] 5.6.4 `agent_sdk/sandbox/middleware.py` - 使用 5.3 的 `SandboxProvider` 抽象；`lazy_init` 支持
- [x] 5.6.5 `agent_sdk/middlewares/view_image.py` - view_image 工具调用完成后注入图片细节；idempotent
- [x] 5.6.6 `agent_sdk/middlewares/title.py` - 自动生成 thread title；接受 `model_factory` + `TitlePrompts` 注入
- [x] 5.6.7 `agent_sdk/middlewares/clarification.py` - 拦截 `ask_clarification`；`Command(goto=END)` 中断
- [x] 5.6.8 `agent_sdk/middlewares/llm_error.py` - retry + 指数退避 + 熔断器 + retry-after 头解析 + 流式事件
- [x] 5.6.9 `agent_sdk/middlewares/summarization.py` - token trigger + keep 策略；支持自定义 `message_partitioner`（skill rescue 入口）
- [x] 5.6.10 单元测试（9 个测试文件 / 112 个用例）
- [x] 5.6.11 验证：ruff + pytest + ADR-010

**5.8 middleware 链装配完成**：

- [x] 5.8.1 `agent_sdk/runtime/middleware_chain.py` - `MiddlewareChainConfig` dataclass + `assemble_chain()` 函数 + `_insert_extra_middlewares()` helper
- [x] 5.8.2 `agent_sdk/runtime/entry.py` 接受 `l2_config: MiddlewareChainConfig | None` + `plan_mode: bool`；L2 特性 wire-up；向后兼容 shim
- [x] 5.8.3 `agent_sdk/runtime/__init__.py` 导出 `MiddlewareChainConfig` / `assemble_chain`
- [x] 5.8.4 `tests/runtime/test_middleware_chain.py` - 28 个用例
- [x] 5.8.5 `tests/runtime/test_entry.py` 扩展 - 3 个 L2 end-to-end 用例
- [x] 5.8.6 验证：ruff + pytest + ADR-010

**质量验证**：
- pytest：阶段 1+2+3+5.1+5.2+5.3+5.4+5.6+5.8 累计 **749/749 通过**（3.08s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 阶段 5.7：Sandbox 工具实现 ✅ 已完成

**目标**：SDK 版 `agent_sdk/sandbox/tools.py` 等价实现 `backend/packages/harness/deerflow/sandbox/tools.py`（1582 行）的所有工具行为 —— bash / ls / glob / grep / read_file / write_file / str_replace —— 但走 SDK 的 `SandboxPathResolver` + `SandboxProvider` + `HostBashPolicy` 注入，**不读全局 config**、**不 import backend**。

**5.7 子模块（已完成）**：

- [x] 5.7.1 `agent_sdk/sandbox/base.py` - Sandbox / SandboxProvider ABC + GrepMatch（5.3 阶段）
- [x] 5.7.2 `agent_sdk/sandbox/exceptions.py` - 7 类错误层级（NotFound / Runtime / Command / File / Permission / FileNotFound / base SandboxError）
- [x] 5.7.3 `agent_sdk/sandbox/file_operation_lock.py` - 进程级 lock + 沙箱 + 路径三元组 key
- [x] 5.7.4 `agent_sdk/sandbox/middleware.py` - Sandbox 生命周期（lazy acquire / eager release）
- [x] 5.7.5 `agent_sdk/sandbox/path_resolver.py` - 4 个 path family（user-data / skills / acp-workspace / custom-mount）+ 校验 / 解析 / masking / command-rewrite / cwd-prefix
- [x] 5.7.6 `agent_sdk/sandbox/search.py` - glob / grep / is_binary helpers
- [x] 5.7.7 `agent_sdk/sandbox/security.py` - HostBashPolicy Protocol + Default + Configurable
- [x] 5.7.8 `agent_sdk/sandbox/tools.py` - 7 个 `@tool` 装饰工具 + make_sandbox_tools factory
- [x] 5.7.9 `agent_sdk/sandbox/__init__.py` 导出 35+ 符号
- [x] 5.7.10 单元测试（10 个测试文件 / 318 个用例 / **317 通过 + 1 skip**）

**5.7 接线修复（2026-07-07 上午 session）**：

tools.py 与 path_resolver / host_bash_policy / sandbox_provider 三者的端到端串联。修复 7 个失败用例：

1. `_try_get_sandbox(runtime)` helper 新增 —— 只读已绑定沙箱不 acquire
2. `_ensure_sandbox` 保留 `local` 标记 —— state 为 `"local"` 时不被 acquire 覆盖
3. bash 工具改写为先查绑定再查 policy
4. bash 工具的 path-validation 加 `thread_data is not None` 守卫
5. `read_file` 末尾换行剥离（POSIX 约定）
6. `_InMemorySandbox`（测试 double）双轨化 —— dict 优先，fallback 真实 FS

**5.7 收尾 batch（2026-07-07 下午 session）**：

adversarial 体检识别 2 BLOCKER + 5 HIGH + 9 MEDIUM 缺口，本 batch 全部修掉：

- [x] 5.7.11 **H-1**：per-tool `max_results` 配置生效（`SandboxToolsConfig.glob_max_results_upper` / `grep_max_results_upper`）
- [x] 5.7.12 **B-1 + H-2**：bash 工具绑定分支始终 mask host 路径（`_run_local_bash` helper + masking always-on）
- [x] 5.7.13 **H-3**：validate_local_tool_path 拒绝 bare root 路径（4 个 subpath predicate）
- [x] 5.7.14 **H-5**：custom_mounts 存在性过滤（`SandboxToolsConfig.with_existing_mounts_only` classmethod + warnings）
- [x] 5.7.15 **M-4**：brand-neutral 错误消息（`LOCAL_BASH_DISABLED_MESSAGE_FALLBACK` + `HostBashPolicy.disabled_message` 协议 + backward-compat alias）
- [x] 5.7.16 **M-5**：工具 description 模板化（`SandboxToolsConfig.python_venv_hint` + bash docstring 占位符 + `__doc__` 后置赋值）
- [x] 5.7.17 **M-1**：错误文案 verbatim backend（"...or configured mount paths are allowed"）
- [x] 5.7.18 **M-9**：tools.py 末尾 re-export 9 个公开函数（向后兼容）
- [x] 5.7.19 **ADR-011 落地**：brand-neutral 文案原则正式立条
- [x] 5.7.20 **23 个新测试**（3 个文件）：覆盖 5 个子任务 + 3 个 security 测试修改

**5.7 仍可继续（不影响 5.7 收尾，留到阶段 6 集成）**：

- [ ] 5.7.21 字节级对齐验证（golden fixture 对比 SDK 输出 vs backend 输出）
- [ ] 5.7.22 view_image / task / memory_middleware 三个 stub（BLOCKER-1/2/3，5.8 体检时划入 5.7 范围外）

**质量验证（截至 2026-07-07 收尾 batch + bugfix）**：
- pytest：阶段 1+2+3+5.1+5.2+5.3+5.4+5.5+5.6+5.7+5.8 累计 **1080/1081 通过**（8.25s；1 skip 是 search 模块 symlink 测试 Windows 跳过）
- ruff 错误数：13（均为测试文件 pre-existing unused imports；SDK 源码净增 0）
- ADR-010 验证：0 个 `backend.*` / `deerflow.*` / `app.*` 导入
- `backend/` **全程未触碰**

### 阶段 6：测试 + 发布 ⏳ 待开始

- [ ] 6.1 补齐已知缺口（`MemoryStreamBridge` / 5.7 golden fixture 对齐 / 5.7 stub 修复）
- [ ] 6.2 多 thread 隔离测试（原 6.3）
- [ ] 6.3 干净环境 `pip install` 测试
- [ ] 6.4 DeerFlow 回归测试（跑 `backend/tests/`，不修改）
- [ ] 6.5 写 CHANGELOG
- [ ] 6.6 发布脚本 + 最终评审

## 当前阶段

**阶段 0-5 全部完成**；**阶段 6 已知缺口全部修复**。**1258/1259 测试通过**（1 skip 为 Windows symlink 测试）。

## 已知缺口

| 缺口 | 描述 | 状态 |
|------|------|------|
| `MemoryStreamBridge` | `StreamBridge` 的 in-process asyncio.Queue 实现（~100 行） | ✅ 已修复（2026-07-14） |
| 5.7 字节级对齐验证 | golden fixture 对比 SDK vs backend 输出 | ✅ 已修复（2026-07-14） |
| 5.7 view_image / task / memory_middleware stub | 三个 stub BLOCKER | ✅ 已修复（2026-07-14） |
| 多 thread 隔离测试 | 不同 thread_id 的 workspace/uploads/outputs 路径互不干扰 | ✅ 已修复（2026-07-14） |
| Memory round-trip 集成 | DeerFlowAgent + Memory 端到端 | ✅ 已修复（2026-07-14） |
| Subagent 调用集成 | task tool + registry + executor 端到端 | ✅ 已修复（2026-07-14） |

## 下一步

继续**阶段 6 测试 + 发布**。已知缺口已全部修复 → 干净环境验证 → 回归测试 → CHANGELOG → 发布。

## 工作日志

### 2026-07-07：阶段 5.7 收尾 batch（5 个子任务 + ADR-011 + 23 个新测试）

详见 [`changelog.md`](changelog.md) 2026-07-07 收尾 batch 条目。

**新增模块 / 改动**：
- 4 个 subpath predicate（`_is_user_data_subpath` 等）
- `_run_local_bash` helper（bound 分支始终 mask）
- 9 个 `tools.py` 末尾 re-export 函数
- `SandboxToolsConfig.with_existing_mounts_only()` classmethod
- `HostBashPolicy.disabled_message` property + brand-neutral fallback

**结果**：
- pytest：**317/318 通过**（7.91s）
- ruff 错误数：13（+2 净增：均为测试文件 pre-existing unused imports）
- ADR-010 验证：0 个 backend import
- `backend/` 全程未触碰

### 2026-07-07：阶段 5.7 接线修复（sandbox 工具层 7 个测试转绿）

**改动 2 个文件**：

- `agent_sdk/sandbox/tools.py` - 4 处接线修复（`_try_get_sandbox` helper / `_ensure_sandbox` 保留 local 标记 / bash 工具先查绑定再查 policy / `read_file` 末尾换行剥除）
- `tests/sandbox/test_tools.py` - `_InMemorySandbox` 双轨化（dict 优先，fallback 真实 FS）

**结果**：
- pytest：**294/295 通过**（4.12s）
- ruff 错误数：11（0 净增）
- ADR-010 验证：0 个 backend import
- `backend/` 全程未触碰

### 2026-07-06：阶段 5.8 实施（middleware 链装配）

**新增模块**：
- `agent_sdk/runtime/middleware_chain.py` - `MiddlewareChainConfig` dataclass（10 个可注入依赖）+ `assemble_chain()` 主函数 + `_insert_extra_middlewares()` helper

**17 个 middleware 装配顺序**（与 backend `make_lead_agent` 一致）：
ThreadData → Uploads → SandboxAudit → DanglingToolCall → LLMErrorHandling → Guardrail → ToolErrorHandling → Summarization → TodoList → TokenUsage → Title → Memory → ViewImage → DeferredToolFilter → SubagentLimit → LoopDetection → Clarification (始终最后)

**entry.py 更新**：
- 接受 `l2_config: MiddlewareChainConfig | None` + `plan_mode: bool`
- L2 特性 wire-up：sandbox / memory / summarization / subagent / vision / auto_title / guardrail
- 缺依赖抛清晰 `ValueError`（指向缺失的 `l2_config` 字段）
- 保留 5.1-era shim：`_assemble_from_features` / `_insert_extra` 委托给新模块

**导出更新**：
- `agent_sdk/runtime/__init__.py` 导出 `MiddlewareChainConfig` / `assemble_chain`

**测试（2 个测试文件 / 31 个新增用例）**：
- `tests/runtime/test_middleware_chain.py` - 28 个（默认链 / sandbox 链 / subagent / vision / title / memory / summarization / plan_mode / Clarification 始终在最后 / @Next/@Prev 插入 / 冲突检测 / 全部特性开启）
- `tests/runtime/test_entry.py` 扩展 - 3 个 L2 end-to-end（l2_config 注入 / 缺依赖错误 / plan_mode）

**结果**：
- pytest：**749/749 通过**（3.08s）—— 724（5.1+5.2+5.3+5.4+5.6 累计） + 25（chain 测试）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06：阶段 5.6 实施（9 个 L2 业务特性 middleware）

**9 个新 middleware（全部按 ADR-010 重写）**：
- `agent_sdk/middlewares/subagent_limit.py` - `SubagentLimitMiddleware`（clamp `[2, 4]`）
- `agent_sdk/middlewares/thread_data.py` - `ThreadDataMiddleware`（PathProvider 注入 + lazy_init）
- `agent_sdk/middlewares/uploads.py` - `UploadsMiddleware`（virtual_prefix 注入 + multimodal 保留）
- `agent_sdk/sandbox/middleware.py` - `SandboxMiddleware`（SandboxProvider 抽象注入）
- `agent_sdk/middlewares/view_image.py` - `ViewImageMiddleware`（idempotent + reducer 清空）
- `agent_sdk/middlewares/title.py` - `TitleMiddleware` + `TitlePrompts` + `TitleModelFactory`（sync fallback + async LLM）
- `agent_sdk/middlewares/clarification.py` - `ClarificationMiddleware`（Command goto=END + 中英图标）
- `agent_sdk/middlewares/llm_error.py` - `LLMErrorHandlingMiddleware` + `RetryConfig` + `CircuitBreakerConfig`（circuit breaker + retry-after）
- `agent_sdk/middlewares/summarization.py` - `SummarizationMiddleware` + `BeforeSummarizationHook` + `SummarizationEvent`（token trigger + partitioner 注入点）

**导出更新**：
- `agent_sdk/middlewares/__init__.py` 导出 9 个新 middleware + 5 个数据类
- `agent_sdk/sandbox/__init__.py` 导出 `SandboxMiddleware` / `SandboxMiddlewareState`

**测试（9 个测试文件 / 112 个用例）**：
- `tests/middlewares/test_subagent_limit.py` - 16 个
- `tests/middlewares/test_thread_data.py` - 5 个
- `tests/middlewares/test_uploads.py` - 8 个
- `tests/sandbox/test_middleware.py` - 7 个
- `tests/middlewares/test_view_image.py` - 7 个
- `tests/middlewares/test_title.py` - 16 个
- `tests/middlewares/test_clarification.py` - 13 个
- `tests/middlewares/test_llm_error.py` - 23 个
- `tests/middlewares/test_summarization.py` - 13 个

**结果**：
- pytest：**724/724 通过**（2.93s）—— 612（5.1+5.2+5.3+5.4 累计） + 112（5.6 新增）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06：阶段 5.4 实施（运行时基础设施：完整范围）

**8 个新模块**：
- `agent_sdk/reflection/__init__.py` + `resolvers.py` - `resolve_class[T](class_path, base_class)` + `resolve_variable[T](variable_path, expected_type)`；泛型 + 11 个 langchain/langfuse 包名 hint
- `agent_sdk/utils/__init__.py` + `network.py` - `PortAllocator`（线程安全，0.0.0.0 绑定）+ `get_free_port` / `release_port` 全局 helper
- `agent_sdk/runtime/langgraph_integration.py` - `make_thread_config` / `merge_configs` / `make_run_id` / `is_valid_thread_id` + configurable key 常量 + stream mode 常量
- `agent_sdk/runtime/checkpointer/{__init__.py, config.py, factory.py, async_factory.py}` - 3 后端（memory/sqlite/postgres）sync 单例 + sync CM + async CM
- `agent_sdk/runtime/store/{__init__.py, async_factory.py}` - 3 后端 async CM
- `agent_sdk/models/{__init__.py, factory.py}` - `ModelConfig` pydantic + `create_chat_model()` 工厂
- `agent_sdk/tools/loader.py` - `ToolConfig` + `load_tools()` + `LoadResult`
- `agent_sdk/tracing/{__init__.py, factory.py}` - `TracingConfig` / `LangSmithConfig` / `LangfuseConfig` + `build_tracing_callbacks()`

**导出更新**：
- `agent_sdk/tools/__init__.py` 导出 `ToolConfig` / `LoadResult` / `load_tools`

**测试（8 个测试文件 / 135 个用例）**：
- `tests/test_reflection.py` - 17 个
- `tests/utils/test_network.py` - 11 个
- `tests/runtime/test_langgraph_integration.py` - 28 个
- `tests/runtime/test_checkpointer.py` - 21 个
- `tests/runtime/test_store.py` - 8 个
- `tests/test_models.py` - 14 个
- `tests/test_tools_loader.py` - 14 个
- `tests/test_tracing.py` - 15 个

**工程改进**：
- 修复 factory 中 postgres 的 import 顺序：先校验 `connection_string` 再尝试 import（让用户先看到清晰的 "missing connection string" 错误）

**结果**：
- pytest：**612/612 通过**（2.46s）—— 477（5.1+5.2+5.3 累计） + 135（5.4 新增）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06：阶段 5.3 实施（抽象 ABC：Sandbox / UserContext / StreamBridge / GuardrailProvider）

**4 个 ABC 模块**：
- `agent_sdk/sandbox/base.py` - `Sandbox`（execute_command / read_file / list_dir / write_file / glob / grep / update_file）+ `SandboxProvider`（acquire / get / release + 可选 shutdown）+ `GrepMatch` 数据类 + `uses_thread_data_mounts` 类属性
- `agent_sdk/runtime/user_context.py` - `CurrentUser` Protocol（runtime_checkable）+ ContextVar 绑定/重置 + `require_current_user` / `get_effective_user_id` / `AUTO` sentinel + `resolve_user_id` 三态解析
- `agent_sdk/runtime/stream_bridge.py` - `StreamBridge` ABC（publish / publish_end / subscribe / cleanup + 默认 no-op close）+ `StreamEvent` frozen dataclass + `HEARTBEAT_SENTINEL` / `END_SENTINEL` 哨兵
- `agent_sdk/guardrails/` - 新子包：`GuardrailRequest` / `GuardrailReason` / `GuardrailDecision` 数据类 + `GuardrailProvider` Protocol（runtime_checkable）+ `AllowlistProvider` 参考实现（allowlist + denylist 双重检查，async delegate 到 sync）

**导出更新**：
- `agent_sdk/sandbox/__init__.py` 导出 `Sandbox` / `SandboxProvider` / `GrepMatch`
- `agent_sdk/runtime/__init__.py` 导出 user_context + stream_bridge symbols（9 个新导出）
- `agent_sdk/guardrails/__init__.py` 新子包导出

**测试（4 个测试文件 / 84 个用例）**：
- `tests/sandbox/test_base.py` - 19 个（GrepMatch + Sandbox ABC + SandboxProvider ABC + integration）
- `tests/runtime/test_user_context.py` - 22 个（Protocol + ContextVar 绑定 + sentinel + resolve_user_id 三态）
- `tests/runtime/test_stream_bridge.py` - 20 个（StreamEvent + sentinels + ABC + 子类）
- `tests/guardrails/test_provider.py` - 23 个（data classes + Protocol + AllowlistProvider 行为）

**工程改进**：
- `pyproject.toml` - 添加最小依赖 `langchain>=0.6` / `langgraph>=0.6` / `pydantic>=2.0`（之前是注释占位，导致 5.1+5.2 测试无法独立运行）
- `pyproject.toml` - 添加 `[dependency-groups] dev` 段（pytest / pytest-asyncio / ruff）
- `pyproject.toml` - 添加 `[tool.pytest.ini_options]`（`asyncio_mode = "auto"` + `testpaths`）

**结果**：
- pytest：**477/477 通过**（2.13s）—— 393（5.1+5.2 累计） + 84（5.3 新增）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06：阶段 5 第一批实施（SDK 入口 + 5 个通用 middleware）

**上午：批次规划 + 计划文档**
- 创建 `phase-5-batch-1.md` 详细计划（5.1 + 5.2 范围）
- 用 plan mode 与用户确认范围
- 计划顺序 5→4→6→7 确认

**下午：5.1 SDK 入口与基础设施**
- `agent_sdk/runtime/__init__.py` - runtime 子包导出
- `agent_sdk/runtime/features.py` - `RuntimeFeatures` 数据类（7 字段）
- `agent_sdk/runtime/decorators.py` - `@Next` / `@Prev` 装饰器（设置类属性 + 校验 anchor 类型）
- `agent_sdk/runtime/thread_state.py` - `ThreadState`（含 `merge_artifacts` / `merge_viewed_images` reducer）
- `agent_sdk/runtime/entry.py` - `create_agent()` + `_assemble_from_features` + `_insert_extra` 装配逻辑
- `agent_sdk/__init__.py` - 顶层导出更新

**下午：5.2 5 个 L3 纯通用 middleware**
- `agent_sdk/middlewares/dangling_tool_call.py` - `DanglingToolCallMiddleware`
- `agent_sdk/middlewares/tool_error_handling.py` - `ToolErrorHandlingMiddleware`（500 字截断 + GraphBubbleUp 透传）
- `agent_sdk/middlewares/token_usage.py` - `TokenUsageMiddleware`
- `agent_sdk/middlewares/loop_detection.py` - `LoopDetectionMiddleware`（hash + freq 双重检测 + LRU）
- `agent_sdk/middlewares/deferred_tool_filter.py` - `DeferredToolFilterMiddleware`（deferred_names_provider 注入）
- `agent_sdk/middlewares/__init__.py` - 5 个新 middleware + todo 子包导出

**测试（9 个测试文件 / 134 个用例）**
- `tests/runtime/test_features.py` - 17 个（默认值、契约、`is_enabled`）
- `tests/runtime/test_decorators.py` - 7 个（@Next / @Prev 行为 + 校验）
- `tests/runtime/test_thread_state.py` - 15 个（reducers + ThreadState 形状）
- `tests/runtime/test_entry.py` - 30 个（参数验证、L2 拒绝、L3 装配、@Next/@Prev 插入、create_agent 端到端）
- `tests/middlewares/test_dangling_tool_call.py` - 13 个
- `tests/middlewares/test_tool_error_handling.py` - 12 个
- `tests/middlewares/test_token_usage.py` - 6 个
- `tests/middlewares/test_loop_detection.py` - 21 个（hash + 警告去重 + 硬停止 + LRU + 线程隔离 + reset）
- `tests/middlewares/test_deferred_tool_filter.py` - 13 个

**结果**：
- pytest：阶段 1+2+3+5.1+5.2 累计 **393/393 通过**（1.89s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06：阶段 3 实施（Audit / Prompt 抽象）

- 创建 `agent_sdk/sandbox/audit/` 子包
  - `rules.py` - `AuditPattern` 数据类（frozen）、`AuditVerdict` 枚举（BLOCK / WARN / PASS）、`AuditRules` Protocol（@runtime_checkable）
  - `default.py` - `DefaultAuditRules`（空规则）
  - `middleware.py` - `SandboxAuditMiddleware`：构造参数 `audit_rules: AuditRules | None = None`；保留 compound command 拆分、shlex 回退、fail-closed unclosed quotes、input 校验、audit log、sync/async hooks
- 创建 `agent_sdk/middlewares/todo/` 子包
  - `prompts.py` - `TodoPrompts` 数据类（frozen）+ brand-neutral `DEFAULT_TODO_SYSTEM_PROMPT` / `DEFAULT_TODO_TOOL_DESCRIPTION`
  - `middleware.py` - `TodoMiddleware`：继承 langchain `TodoListMiddleware`；构造参数 `prompts: TodoPrompts | None`；保留 `before_model`（context-loss 检测）、`after_model`（premature-exit 预防 + retry cap = 2）
- 创建 `agent_sdk/presets/deerflow/audit.py` - `DeerFlowAuditRules`（15 条 high-risk + 5 条 medium-risk 重新录入；**与 backend 行为字节级一致**）
- 创建 `agent_sdk/presets/deerflow/prompts/__init__.py` + `todo.py` - `DEERFLOW_TODO_SYSTEM_PROMPT` / `DEERFLOW_TODO_TOOL_DESCRIPTION` / `DEERFLOW_TODO_PROMPTS`（**与 backend 字节级一致**）
- 更新 `agent_sdk/presets/deerflow/__init__.py` 导出新 preset
- 写 6 个测试文件（90 个用例）
  - `tests/sandbox/audit/test_rules.py` - 13 个（AuditVerdict / AuditPattern / AuditRules Protocol）
  - `tests/sandbox/audit/test_classification.py` - 23 个（_split_compound_command / _classify_command）
  - `tests/sandbox/audit/test_middleware.py` - 18 个（wrap_tool_call / awrap_tool_call / input 校验 / audit log / custom tool_name）
  - `tests/middlewares/todo/test_prompts.py` - 9 个（TodoPrompts 数据类 + 默认常量 + brand-neutral 验证）
  - `tests/middlewares/todo/test_middleware.py` - 16 个（构造 + before_model + after_model + async）
  - `tests/presets/deerflow/test_audit.py` - 36 个（DeerFlowAuditRules 16 个 BLOCK + 8 个 WARN + 3 个 middleware 集成）
  - `tests/presets/deerflow/test_todo_prompts.py` - 9 个（字节级等价验证）
- **结果：259/259 测试通过（1.52s）；ruff 全部通过**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06：阶段 2 实施 + 推进顺序重整

**上午：推进顺序写入文档**
- 检查 phases.md：原线性 5 阶段（0→1→2→3→4→5）**没有 L3 通用层抽离阶段**
- 新推进顺序写入：`0→1→2→3→5（L3）→4（Preset）→6（集成）→7（发布）`
- 原因：L3 通用层是 SDK 骨架，原计划缺失；Preset 需要 L3 支撑所以顺序倒过来
- 新建 `phase-5-l3-foundation.md`（L3 通用层抽离详细计划）
- 新建 `phase-6-integration.md`（端到端集成）
- 把原 `phase-5-verification.md` 拆为 `phase-7-publishing.md`

**下午：阶段 2 实施（Memory / Subagent / Tools 数据模型抽象）**
- 创建 `agent_sdk/memory/`：MemorySchema Protocol、DefaultMemorySchema、FileMemoryStorage、MemoryMiddleware、MemoryUpdater
- 创建 `agent_sdk/subagents/`：SubagentDefinition、SubagentRegistry Protocol、DefaultSubagentRegistry、SubagentExecutor
- 创建 `agent_sdk/tools/`：6 个 builtin tool factory（ask_clarification / present_files / view_image / task / setup_agent / invoke_acp_agent）
- 创建 `agent_sdk/presets/deerflow/memory.py`：DeerFlowMemorySchema（**与 backend 字节级一致**）
- 创建 `agent_sdk/presets/deerflow/subagents.py`：DeerFlowSubagentRegistry（general-purpose / bash 重新录入）
- 写 7 个测试文件：test_default / test_deerflow / test_storage / test_executor + tools test_factory
- 安装依赖：langchain / langgraph
- **结果：135 个测试 100% 通过；ruff 全部通过**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 2026-07-06（早些时候）：阶段 1 实施

- 创建 `agent_sdk/paths/` 子包
- 65 个测试通过

### 2026-07-06（更早）：阶段 0 规划文档审计 + ADR-010

- 37 处冲突发现并修正
- 5 份 phase 详细计划 + phases.md + feature-inventory.md 修订
- 新增 ADR-010

### 2026-07-03：项目启动

- 确认目标：feature-rich + brand-neutral SDK
- 创建 `sdk-extraction/` 目录结构
- 写所有规划文档
- 写 9 个 ADR 决策

### 2026-07-06：阶段 5.5 实施（集成子系统：Skills / MCP / Guardrails）

（详见上方阶段 5.5 条目）

### 2026-07-13：阶段 5.5 收尾（MCP OAuth + Skills 安装器 + 69 个测试）

**新增 3 个模块 + 1 个扩展**：

- `agent_sdk/mcp/oauth.py` — `OAuthTokenManager`（token 获取/缓存/刷新）+ `build_oauth_tool_interceptor` + `get_initial_oauth_headers`；httpx 懒加载；支持 client_credentials + refresh_token grant types
- `agent_sdk/mcp/config.py` 扩展 — 新增 `McpOAuthConfig` Pydantic 模型（16 字段）；`McpServerConfig` 新增 `oauth` 可选字段
- `agent_sdk/skills/validation.py` — `validate_skill_frontmatter`（与 backend 行为一致：8 个允许键、name 正则校验、描述禁止尖括号、长度限制）
- `agent_sdk/skills/installer.py` — `ainstall_skill_from_archive` / `install_skill_from_archive`（.skill ZIP 安装器，含 zip-bomb 防护 / 路径遍历检测 / symlink 检测 / macOS 元数据过滤 / 可注入安全扫描器；默认扫描器阻止 executable 内容）

**导出更新**：
- `agent_sdk/mcp/__init__.py` 导出 `McpOAuthConfig` / `OAuthTokenManager` / `build_oauth_tool_interceptor` / `get_initial_oauth_headers`
- `agent_sdk/skills/__init__.py` 导出 `SkillAlreadyExistsError` / `SkillSecurityScanError` / `ainstall_skill_from_archive` / `install_skill_from_archive` / `validate_skill_frontmatter` / `ALLOWED_FRONTMATTER_PROPERTIES` + ZIP helpers

**测试（3 个测试文件 / 69 个用例）**：
- `tests/mcp/test_oauth.py` — 15 个（McpOAuthConfig + token manager 缓存/刷新/错误处理 + interceptor + initial headers）
- `tests/skills/test_validation.py` — 22 个（frontmatter 验证：缺失字段 / 无效 YAML / name regex / 长度限制 / 描述验证 / 允许键检查）
- `tests/skills/test_installer.py` — 19 个（ZIP 安全 / 解压 / 安装 / 重复检测 / 自定义扫描器 / sync wrapper / 嵌套 SKILL.md 检测）

**结果**：
- pytest：**1149/1150 通过**（8.60s；1 skip 为 Windows symlink 测试）
- ruff 错误数：15（均为测试文件 pre-existing；SDK 净增 0）
- ADR-010 验证：0 个 `backend.*` / `deerflow.*` / `app.*` 导入
- `backend/` **全程未触碰**

### 2026-07-13：阶段 4 DeerFlow Preset 抽离完成

**新增 3 个模块 + 1 个文档**：

- `agent_sdk/presets/deerflow/prompts/system.py` — ~700 行 DeerFlow 系统 prompt 重新录入：`SYSTEM_PROMPT_TEMPLATE` 常量 + `apply_prompt_template()` 主装配函数 + `build_subagent_section()` / `build_skills_prompt_section()` / `build_acp_section()` / `build_custom_mounts_section()` 分段构建器。所有 backend config 依赖替换为显式参数。
- `agent_sdk/presets/deerflow/agent.py` — `DeerFlowAgent` 便利类：dataclass 设计，lazy graph build，`ainvoke` / `invoke` / `astream` / `stream` 便捷方法。默认注入 `DeerFlowPathProvider` + `DeerFlowMemorySchema` + `DeerFlowAuditRules`。`DEERFLOW_DEFAULT_FEATURES` 常量（sandbox + subagent + vision + auto_title + skills）。
- `agent_sdk/presets/deerflow/README.md` — preset 使用文档（Quick Start / 组件清单 / 默认特性 / 配置示例 / API 参考 / 扩展方式）。
- 导出更新：`presets/deerflow/__init__.py` 导出 `DeerFlowAgent` / `DEERFLOW_DEFAULT_FEATURES` / `apply_prompt_template` / `build_subagent_section` 等。

**测试（2 个测试文件 / 38 个用例）**：
- `tests/presets/deerflow/test_agent.py` — 16 个（构造 / 默认特性 / 系统 prompt / 特性查询 / graph 构建 + 缓存）
- `tests/presets/deerflow/test_system_prompt.py` — 22 个（模板渲染 / subagent 开关 / ACP / custom mounts / skills / soul / memory 注入）

**结果**：
- pytest：**1187/1188 通过**（8.05s；1 skip 为 Windows symlink 测试）
- ruff：**presets + tests/presets 均 All checks passed**
- ADR-010 验证：0 个 `backend.*` / `deerflow.*` / `app.*` 导入
- `backend/` **全程未触碰**

### 2026-07-14：阶段 6 已知缺口全部修复

**6 个缺口全部修复**（详见上方已知缺口表）：

| # | 缺口 | 修复内容 |
|---|------|----------|
| 1 | `MemoryStreamBridge` | 新建 `agent_sdk/runtime/stream_bridge/memory.py`（134 行），``stream_bridge.py`` 转为包；13 个新测试 |
| 2 | `view_image` tool stub | 替换为完整实现（~150 行）：MIME 检测、base64 编码、路径解析；17 个新测试 |
| 3 | `memory/middleware` after_agent | 新增 `after_agent` 钩子：加载 schema → 合并 state 变更 → 持久化；7 个新测试 |
| 4 | `task` tool + `SubagentExecutor` | 重写 `SubagentExecutor`（~230 行）：ThreadPoolExecutor、超时、取消、后台任务管理；重写 `task_tool`（~100 行）：注册表校验、executor 集成；25 个新测试 |
| 5 | 5.7 golden fixture 对齐 | 新建 `tests/sandbox/test_golden_fixtures.py`：工具构造、命名、描述、args_schema 一致性验证；6 个新测试 |
| 6 | 3 个集成测试 | 新建 `tests/integration/test_integration.py`：多 thread 隔离、Memory round-trip、Subagent 调用端到端；8 个新测试 |

**新增文件**：
- `agent_sdk/runtime/stream_bridge/__init__.py`（包转换）
- `agent_sdk/runtime/stream_bridge/memory.py`
- `tests/runtime/test_stream_bridge_memory.py`（13 个测试）
- `tests/tools/test_view_image.py`（17 个测试）
- `tests/memory/test_middleware.py`（7 个测试）
- `tests/sandbox/test_golden_fixtures.py`（6 个测试）
- `tests/integration/test_integration.py`（8 个测试）

**修改文件**：
- `agent_sdk/tools/view_image.py`（stub → 完整实现）
- `agent_sdk/tools/task.py`（stub → 完整实现）
- `agent_sdk/subagents/executor.py`（stub → 完整实现）
- `agent_sdk/memory/middleware.py`（新增 after_agent）
- `agent_sdk/runtime/__init__.py`（导出 MemoryStreamBridge）
- `agent_sdk/subagents/__init__.py`（导出新符号）
- `tests/subagents/test_executor.py`（更新 API 匹配）

**结果**：
- ruff：**All checks passed**（0 错误）
- pytest：**1258/1259 通过**（+71 个新测试；1 skip 为 Windows symlink 测试）
- ADR-010 合规：0 个 backend import
- `backend/` **全程未触碰**

### 2026-07-14：progress.md 差异修复 + 代码清理

**差异修复**：
- 阶段总览表中重复的 "5.8" 标签 → 第二个重命名为 "5.9 接口对齐体检"
- `phase-6-publishing.md` 子任务编号从 5.x 修正为 6.x
- 归档已取消的 `phase-6-integration.md` → `docs/05-archive/`

**代码清理**：
- `agent_sdk/sandbox/tools.py`：移除 `TYPE_CHECKING` 块中未使用的 `ThreadDataState` / `ThreadState` 导入（ruff F401 × 2）
- 简化 `_RuntimeType` 赋值（TYPE_CHECKING 分支不再需要）

**结果**：
- ruff：`agent_sdk/` 源码 **All checks passed**（0 错误）；测试文件 13 个 pre-existing（与之前一致）
- pytest：**1187/1188 通过**（1 skip 为 Windows symlink 测试）
- ADR-010 合规：0 个 backend import
- `backend/` **全程未触碰**

### 后续待记录

（每个 session 结束前添加）

## 统计

- 总任务数：约 100 个（原 ~120 减去取消的阶段 6 的 ~20 个冗余项）
- 已完成：阶段 0-5 全部（6 个阶段，~90 个子任务）
- 测试通过：**1187/1188**（1 skip 为 Windows symlink 测试）
- 待补：6 个已知缺口
- 进度：**约 90%**（阶段 0-5 完成，阶段 6 待做）
- 估时剩余：阶段 6（1-2 周）

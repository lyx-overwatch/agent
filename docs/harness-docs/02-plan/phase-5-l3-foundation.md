# 阶段 5：L3 通用层抽离（3 周）★ 新增

> 把 L3 纯通用能力抽到 SDK 内部，建立 SDK 骨架。
>
> **为什么需要这个阶段**：原线性 5 阶段计划中 L3 通用层缺失——只提"5 个通用 middleware"但没有专门阶段。L3 是 SDK 的骨架，缺了它 SDK 只是个空壳，preset 也无法跑通。
>
> **为什么放在阶段 4 之前**：因为阶段 4（DeerFlow Preset 打包）需要用到 L3 通用层的 `create_agent` 入口、middleware 链装配、StreamBridge、LangGraph 集成等基础设施。

## 目标

把以下 L3 纯通用能力（无业务假设）抽到 `sdk-extraction/harness/agent_sdk/`：

1. **SDK 入口与基础设施**：`create_agent`、`RuntimeFeatures`、`@Next` / `@Prev` 装饰器、`ThreadState`
2. **5 个通用 middleware**（无业务假设的纯通用能力）
3. **抽象 ABC**（`Sandbox` / `MemoryStorage` / `UserContext` / `StreamBridge` / `GuardrailProvider`）
4. **运行时基础设施**：LangGraph 集成、Checkpointer / Store、ModelFactory、ToolLoader、Reflection、Tracing、Utils
5. **集成子系统**：MCP、Skills、Guardrails
6. **业务特性 middleware**（L2 层但实现在 L3 通用层里）：Todo / Memory / SubagentLimit / Uploads / ThreadData / ViewImage / Title / Summarization / Clarification / LLMErrorHandling / Sandbox / SandboxAudit
7. **Sandbox 工具实现**：SDK 版 1582 行 sandbox 工具（使用 PathProvider 注入）

## 关键交付物

### 5.1 SDK 入口与基础设施（2 天）

- `agent_sdk/__init__.py` - 暴露 `create_agent`、`RuntimeFeatures`
- `agent_sdk/runtime/entry.py` - `create_agent()` 入口
- `agent_sdk/runtime/features.py` - `RuntimeFeatures` 数据类
- `agent_sdk/runtime/decorators.py` - `@Next` / `@Prev` 装饰器
- `agent_sdk/runtime/thread_state.py` - 基础 `ThreadState`（业务字段留给 preset）

### 5.2 5 个通用 middleware（1 周）

全部为 L3 纯通用，直接抽到 SDK：

- `agent_sdk/middlewares/dangling_tool_call.py` - `DanglingToolCallMiddleware`
- `agent_sdk/middlewares/tool_error_handling.py` - `ToolErrorHandlingMiddleware`
- `agent_sdk/middlewares/token_usage.py` - `TokenUsageMiddleware`
- `agent_sdk/middlewares/loop_detection.py` - `LoopDetectionMiddleware`
- `agent_sdk/middlewares/deferred_tool_filter.py` - `DeferredToolFilterMiddleware`

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/middlewares/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 复制粘贴 `backend/agents/middlewares/*` 文件

**做法**：
- 读 `backend/agents/middlewares/*` 作为行为参考
- 在 SDK 内部**重新写**每个 middleware
- 单元测试与 `backend/` 行为字节级一致

### 5.3 抽象 ABC（2 天）

- `agent_sdk/sandbox/base.py` - `Sandbox` / `SandboxProvider` ABC
- `agent_sdk/memory/storage.py` - `MemoryStorage(ABC, Generic[T])`（阶段 2 已有）
- `agent_sdk/runtime/user_context.py` - `UserContext`（ContextVar 抽象）
- `agent_sdk/runtime/stream_bridge.py` - `StreamBridge`
- `agent_sdk/guardrails/provider.py` - `GuardrailProvider` Protocol

**绝对禁止**：
- ❌ 通过继承 `backend/` 现有 ABC 实现 SDK 版
- ❌ `from backend.* import ...`

### 5.4 运行时基础设施（1 周）

- `agent_sdk/runtime/langgraph_integration.py` - LangGraph 0.6+ 集成
- `agent_sdk/runtime/checkpointer.py` - Checkpointer
- `agent_sdk/runtime/store.py` - Store
- `agent_sdk/models/factory.py` - `ModelFactory`
- `agent_sdk/tools/loader.py` - `ToolLoader`（装配逻辑）
- `agent_sdk/reflection/` - Reflection 工具
- `agent_sdk/tracing/factory.py` - Tracing 工厂（LangSmith / Langfuse callback）
- `agent_sdk/utils/` - 文件转换、网络端口分配、HTML 解析

### 5.5 集成子系统（3 天）

- `agent_sdk/mcp/client.py` - `MCPClient`
- `agent_sdk/mcp/oauth.py` - OAuth 拦截器
- `agent_sdk/skills/parser.py` - SKILL.md YAML frontmatter 解析
- `agent_sdk/skills/loader.py` - Skills 加载器
- `agent_sdk/skills/installer.py` - Skills 安装器
- `agent_sdk/guardrails/middleware.py` - Guardrails middleware

### 5.6 业务特性 middleware（L2 实现层，1 周）

这些是 L2 特性（在 L1/L2 抽象之后用 Protocol 注入业务），但实现在 L3 通用层里：

- `agent_sdk/middlewares/todo.py` - `TodoMiddleware`（阶段 3 已经在 L2 实现）
- `agent_sdk/middlewares/memory.py` - `MemoryMiddleware`（阶段 2 已经在 L2 实现）
- `agent_sdk/middlewares/subagent_limit.py` - `SubagentLimitMiddleware`
- `agent_sdk/middlewares/uploads.py` - `UploadsMiddleware`（使用 PathProvider 注入）
- `agent_sdk/middlewares/thread_data.py` - `ThreadDataMiddleware`（使用 PathProvider 注入）
- `agent_sdk/middlewares/view_image.py` - `ViewImageMiddleware`
- `agent_sdk/middlewares/title.py` - `TitleMiddleware`
- `agent_sdk/middlewares/summarization.py` - `SummarizationMiddleware`
- `agent_sdk/middlewares/clarification.py` - `ClarificationMiddleware`
- `agent_sdk/middlewares/llm_error.py` - `LLMErrorHandlingMiddleware`
- `agent_sdk/sandbox/middleware.py` - `SandboxMiddleware`
- `agent_sdk/sandbox/audit/middleware.py` - `SandboxAuditMiddleware`（阶段 3 已经在 L2 实现）

### 5.7 Sandbox 工具实现（1 周）

- `agent_sdk/sandbox/tools.py` - SDK 版 1582 行 sandbox 工具（mask_local_paths_in_output、replace_virtual_paths_in_command、validate_local_tool_path、validate_local_bash_command_paths 等），所有硬编码路径通过 PathProvider 注入

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/sandbox/tools.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 复制粘贴 `backend/sandbox/tools.py` 文件

**做法**：
- 读 `backend/sandbox/tools.py` 作为行为参考
- 在 SDK 内部**重新写** 1582 行等价实现
- 全局常量 `VIRTUAL_PATH_PREFIX = "/mnt/user-data"` 移到 `DeerFlowPathProvider` 的常量
- 全局常量 `_DEFAULT_SKILLS_CONTAINER_PATH`、`_ACP_WORKSPACE_VIRTUAL_PATH` 移到 SDK 配置参数
- 单元测试与 `backend/` 行为字节级一致

### 5.8 middleware 链装配（1 周）

- `agent_sdk/runtime/middleware_chain.py` - middleware 链装配
- 18 个 middleware 按正确顺序装配：
  ```
  ThreadData → Uploads → Sandbox → DanglingToolCall →
  LLMErrorHandling → Guardrail → SandboxAudit → ToolErrorHandling →
  Summarization → TodoList → TokenUsage → Title →
  Memory → ViewImage → DeferredToolFilter →
  SubagentLimit → LoopDetection → Clarification
  ```
- 顺序由 `@Next` / `@Prev` 装饰器驱动
- 单元测试验证顺序

## 任务清单

- [ ] 5.1 SDK 入口与基础设施（2 天）
- [ ] 5.2 5 个通用 middleware（1 周）
- [ ] 5.3 抽象 ABC（2 天）
- [ ] 5.4 运行时基础设施（1 周）
- [ ] 5.5 集成子系统（3 天）
- [ ] 5.6 业务特性 middleware（1 周）
- [ ] 5.7 Sandbox 工具实现（1 周）
- [ ] 5.8 middleware 链装配（1 周）
- [ ] 5.9 单元测试 + 与 backend 行为字节级对齐
- [ ] 5.10 验证 `backend/tests/` 基线回归（仅跑，不修改）

## 不在阶段 5 范围

- 修改 `backend/packages/harness/deerflow/agents/middlewares/*` 等现有文件
- 修改 `backend/packages/harness/deerflow/sandbox/tools.py`
- `from backend.* import ...` 或 `from deerflow.* import ...`
- 复制粘贴 `backend/` 任何文件

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| 18 个 middleware 装配顺序错误 | 高 | 单元测试验证顺序；参考 `backend/agents/factory.py` 的装配逻辑但不 import |
| 1582 行 sandbox 工具行为不一致 | 高 | golden fixture 字节级对比；分小批实现 |
| LangGraph 0.6+ 集成 API 变更 | 中 | 锁定 langgraph 版本；充分测试 |
| DeerFlow 业务耦合漏到 L3 层 | 中 | 严格审查每个模块的"业务假设"；L3 必须无业务假设 |
| SDK 体积膨胀 | 低 | 业务 middleware 推到阶段 4 preset；L3 只保留最通用能力 |

## 依赖

- 阶段 1-3 全部完成（已建立 PathProvider / MemorySchema / SubagentRegistry / AuditRules Protocol）

## 产出（**全部在 SDK 内部，`backend/` 不动**）

- `sdk-extraction/harness/agent_sdk/`
  - `runtime/` - 入口、ThreadState、middleware 链、StreamBridge、UserContext、Checkpointer、Store
  - `middlewares/` - 5 个通用 + 13 个业务特性 middleware
  - `sandbox/` - ABC + tools + middleware + audit
  - `memory/` - storage ABC（阶段 2 已有）
  - `subagents/` - registry（阶段 2 已有）
  - `models/` - ModelFactory
  - `tools/` - factory（阶段 2 已有）+ ToolLoader
  - `mcp/` - MCPClient + OAuth
  - `skills/` - 加载器 + 安装器
  - `guardrails/` - Provider + Middleware
  - `reflection/` - 工具
  - `tracing/` - 工厂
  - `utils/` - 工具
  - `paths/` - 阶段 1 已有

- `sdk-extraction/harness/tests/`
  - 各模块单元测试 + golden fixture

## 完成标准

- [ ] 5.1-5.10 全部完成
- [ ] SDK 内部单元测试 100% 通过
- [ ] 18 个 middleware 按正确顺序装配并通过测试
- [ ] SDK 版 1582 行 sandbox 工具与 `backend/sandbox/tools.py` 行为字节级一致
- [ ] **`backend/` 全程未触碰**
- [ ] ADR-010 验证：`grep` SDK 全部代码 0 处 import `backend.*` / `deerflow.*` / `app.*`
- [ ] `backend/tests/` 基线回归通过（仅跑，不修改）

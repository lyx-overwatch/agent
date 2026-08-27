# SDK 特性清单

> 抽离后 SDK 必须保留的所有 DeerFlow 特性。每项标注：原文件位置、L 分类、抽离策略。

## 1. 任务规划（TodoList）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py` |
| L 分类 | L2（特性 + 可配置业务） |
| 抽离策略 | 保留 `TodoMiddleware` 在 SDK；`write_todos` tool 描述与 system_prompt 通过参数注入 |
| 业务耦合 | prompt 文案、tool description |
| 协议 | `TodoSystemPrompt` Protocol（可选） |

## 2. 长期记忆（Memory）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/agents/memory/` |
| L 分类 | L2（特性 + 可配置业务） |
| 抽离策略 | `MemoryMiddleware` + `MemoryUpdater` + `MemoryStorage` 抽到 SDK；数据模型 + prompt 注入 |
| 业务耦合 | workContext 三段式、memory.json 格式、抽取 prompt |
| 协议 | `MemorySchema` Protocol、`MemoryStorage` ABC（已有） |

## 3. 多 Agent 协同（Subagent）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/subagents/` |
| L 分类 | L2（特性 + 可配置业务） |
| 抽离策略 | `SubagentExecutor` + `SubagentConfig` + `SubagentRegistry` 抽到 SDK；角色定义通过注册表注入 |
| 业务耦合 | general-purpose / bash 角色、并发数、timeout |
| 协议 | `SubagentRegistry` Protocol |

## 4. 文件管理（Uploads / Workspace / Outputs）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/uploads/manager.py`、`agents/middlewares/uploads_middleware.py`、`agents/middlewares/thread_data_middleware.py` |
| L 分类 | L2（特性 + 可配置业务） |
| 抽离策略 | `UploadsMiddleware` + `ThreadDataMiddleware` 抽到 SDK；路径通过 `PathProvider` 注入；CRUD 业务逻辑提供抽象 |
| 业务耦合 | `/mnt/user-data` 路径前缀、`validate_thread_id` 字符白名单 |
| 协议 | `PathProvider` Protocol |

## 5. 沙箱（Sandbox）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/sandbox/` |
| L 分类 | L3（沙箱 ABC）+ L2（工具实现） |
| 抽离策略 | `Sandbox` / `SandboxProvider` ABC 抽到 SDK；工具实现（bash/grep/glob/ls）作为默认实现移到 preset 或 community |
| 业务耦合 | `sandbox/tools.py` 1582 行的具体工具实现 |
| 协议 | `Sandbox` / `SandboxProvider` ABC（已有） |

## 6. 安全审计（Sandbox Audit）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py` |
| L 分类 | L2（特性 + 可配置业务） |
| 抽离策略 | `SandboxAuditMiddleware` 抽到 SDK；规则列表通过参数注入 |
| 业务耦合 | chmod 777、LD_PRELOAD、fork bomb 等具体规则 |
| 协议 | `AuditRules` Protocol |

## 7. Skills（SKILL.md 协议）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/skills/` |
| L 分类 | L3（协议本身通用）+ L2（部分业务） |
| 抽离策略 | SKILL.md 协议 + 解析器 + 加载器 + 安装器 抽到 SDK；`security_scanner` + `manager.py` 移到 preset |
| 业务耦合 | security_scanner 的 LLM 评估、manager CRUD |
| 协议 | SKILL.md 格式（已有） |

## 8. MCP 集成

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/mcp/` |
| L 分类 | L3（纯通用） |
| 抽离策略 | 整个 `mcp/` 抽到 SDK |
| 业务耦合 | 无 |
| 协议 | MCP（标准协议） |

## 9. Guardrails（OAP 协议）

| 项 | 值 |
|----|----|
| 原文件 | `backend/packages/harness/deerflow/guardrails/` |
| L 分类 | L3（纯通用） |
| 抽离策略 | 整个 `guardrails/` 抽到 SDK |
| 业务耦合 | 无（OAP 是标准协议） |
| 协议 | `GuardrailProvider` Protocol（已有） |

## 10. 通用能力

### 5 个通用 middleware

| Middleware | 原文件 | L 分类 | 抽离策略 |
|------------|--------|--------|----------|
| DanglingToolCallMiddleware | `agents/middlewares/dangling_tool_call_middleware.py` | L3 | 直接抽到 SDK |
| ToolErrorHandlingMiddleware | `agents/middlewares/tool_error_handling_middleware.py` | L3 | 直接抽到 SDK |
| TokenUsageMiddleware | `agents/middlewares/token_usage_middleware.py` | L3 | 直接抽到 SDK |
| LoopDetectionMiddleware | `agents/middlewares/loop_detection_middleware.py` | L3 | 直接抽到 SDK |
| DeferredToolFilterMiddleware | `agents/middlewares/deferred_tool_filter_middleware.py` | L3 | 直接抽到 SDK |

### 抽象与工具

| 项 | 原文件 | L 分类 | 抽离策略 |
|----|--------|--------|----------|
| `RuntimeFeatures` | `agents/features.py` | L3 | 直接抽到 SDK |
| `@Next` / `@Prev` 装饰器 | `agents/features.py` | L3 | 直接抽到 SDK |
| `ThreadState`（基础部分） | `agents/thread_state.py` | L3 | 基础 `AgentState` 抽到 SDK，业务字段移到 preset |
| `create_agent` | `agents/factory.py` | L3 | 直接抽到 SDK |
| Reflection | `reflection/` | L3 | 直接抽到 SDK |
| Tracing | `tracing/` | L3 | 直接抽到 SDK |
| Utils | `utils/` | L3 | 直接抽到 SDK |
| StreamBridge | `runtime/stream_bridge/` | L3 | 直接抽到 SDK |
| Serialization | `runtime/serialization.py` | L3 | 直接抽到 SDK |
| UserContext | `runtime/user_context.py` | L3 | 抽到 SDK，ContextVar 抽象 |
| Checkpointer | `runtime/checkpointer/` | L3 | 直接抽到 SDK |
| Store | `runtime/store/` | L3 | 直接抽到 SDK |
| ModelFactory | `models/factory.py` | L3 | 直接抽到 SDK |
| ToolLoader | `tools/tools.py`（装配逻辑部分） | L3 | 装配器抽到 SDK |

## 11. 不在 SDK 中复制粘贴（`backend/` 现有文件保持原样）

**关键原则**：抽离 PR 期间 `backend/` 任何现有文件**完全不动**（ADR-004）。本节列出的文件**不通过复制粘贴或 import 方式搬入 SDK**；如有等价业务逻辑需要，由 SDK 内部**以新代码**实现（参考 `backend/` 行为但**不引用** `backend.*`）。

| 项 | 原文件 | 备注 |
|----|--------|------|
| `make_lead_agent` | `agents/lead_agent/agent.py` | YAML 驱动的应用工厂，**不抽离**（属于应用层而非 SDK 特性） |
| `apply_prompt_template` | `agents/lead_agent/prompt.py` | 760 行 DeerFlow 业务 prompt；SDK 等价物在 `presets/deerflow/prompts/system.py` **以新代码实现**（**不 import** `backend.*`） |
| `DeerFlowClient` | `client.py` | DeerFlow 应用门面；SDK 提供 `DeerFlowAgent` 便利类**作为新 API**，**不替换** `DeerFlowClient` |
| 9 个 builtin tool | `tools/builtins/*` | 强 DeerFlow 业务（ask_clarification / present_files / view_image / setup_agent / invoke_acp_agent / task 等）；SDK 等价物在 `presets/deerflow/tools/` **以新代码实现** |
| `skill_manage_tool` | `tools/skill_manage_tool.py` | DeerFlow UX；SDK 等价物在 `presets/deerflow/tools/skill_manage.py` **以新代码实现** |
| `subagents/builtins/` | `subagents/builtins/` | general-purpose / bash 业务角色；SDK 等价物在 `presets/deerflow/subagents.py` **以新代码实现** |
| `SubagentExecutor` 业务实现 | `subagents/executor.py` | 强 DeerFlow 业务（轮询、trace_id）；SDK 等价物在 `agent_sdk/subagents/executor.py` **以新代码实现** |
| `sandbox/tools.py` 业务实现 | `sandbox/tools.py` | 1582 行 DeerFlow 沙箱工具；SDK 等价物在 `agent_sdk/sandbox/tools.py` **以新代码实现** |
| `sandbox/local/*` | `sandbox/local/` | 本地沙箱业务实现；SDK 等价物在 `agent_sdk/sandbox/local.py` **以新代码实现** |
| `sandbox/middleware.py` 业务实现 | `sandbox/middleware.py` | DeerFlow 沙箱中间件；SDK 等价物在 `agent_sdk/sandbox/middleware.py` **以新代码实现** |
| `persistence/*` | `persistence/` | SQLAlchemy ORM 业务表（**不抽离**） |
| `community/*` | `community/` | 第三方集成（**不抽离**） |
| `models/credential_loader.py` | `models/credential_loader.py` | Claude Code CLI 凭证（**不抽离**） |
| `models/*_provider.py` | `models/*_provider.py` | Provider 实现应独立成包（**不抽离**） |
| `models/patched_*.py` | `models/patched_*.py` | 模型补丁应独立成包（**不抽离**） |
| `runtime/runs/` | `runtime/runs/` | LangGraph Platform 兼容层（**不抽离**） |
| `runtime/events/store/` | `runtime/events/store/` | LangGraph Platform 事件存储（**不抽离**） |
| `config/agents_config.py` | `config/agents_config.py` | SOUL.md 业务（**不抽离**） |
| `config/acp_config.py` | `config/acp_config.py` | ACP 业务集成（**不抽离**） |

## 12. 待定（阶段 1 详细分析）

| 项 | 状态 |
|----|------|
| `extensions_config.py` 加载 | 阶段 1 分析：是否可独立 |
| `summarization_middleware.py` | 阶段 1 分析：技能路径依赖 |

## 总结

抽离后 SDK 包含：
- **3 个核心入口**：`create_agent` / `RuntimeFeatures` / 各 Protocol
- **10 大特性**：Todo、Memory、Subagent、Uploads、Workspace、Sandbox、Audit、Skills、MCP、Guardrails
- **5 个通用 middleware** + 抽象 ABC
- **完整文档 + 测试**

预计代码量：~8000 行（精简后） vs 现有 ~30000 行（混合体）。

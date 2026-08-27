# 阶段 5 第一批：SDK 入口 + 5 个通用 middleware

> **为什么分批**：阶段 5 是 3 周规模（10 个子任务）。第一批聚焦"最通用 + 后续所有工作的基础"——5.1 SDK 入口基础设施 + 5.2 五个 L3 纯通用 middleware。
>
> **第一批范围（5.1 + 5.2）**：
> - SDK 入口与基础设施：`create_agent` / `RuntimeFeatures` / `@Next` / `@Prev` / `ThreadState`
> - 5 个 L3 纯通用 middleware：`DanglingToolCall` / `ToolErrorHandling` / `TokenUsage` / `LoopDetection` / `DeferredToolFilter`
>
> **不在第一批范围（后续批次）**：
> - 5.3 抽象 ABC（Sandbox / UserContext / StreamBridge / GuardrailProvider）
> - 5.4 运行时基础设施（LangGraph 集成 / Checkpointer / ModelFactory / ToolLoader / Reflection / Tracing / Utils）
> - 5.5 集成子系统（MCP / Skills / Guardrails）
> - 5.6 业务特性 middleware（13 个）
> - 5.7 Sandbox 工具实现（1582 行）
> - 5.8 middleware 链装配
> - 5.9-5.10 验证

## 任务清单

- [ ] 5.1.1 `RuntimeFeatures` 数据类（`agent_sdk/runtime/features.py`）
- [ ] 5.1.2 `@Next` / `@Prev` 装饰器（`agent_sdk/runtime/decorators.py`）
- [ ] 5.1.3 `ThreadState` 基础状态（`agent_sdk/runtime/thread_state.py`）
- [ ] 5.1.4 `create_agent` 入口（`agent_sdk/runtime/entry.py`）
- [ ] 5.1.5 `agent_sdk/__init__.py` 导出（更新）
- [ ] 5.1.6 单元测试（features / decorators / thread_state / entry）
- [ ] 5.2.1 `DanglingToolCallMiddleware`（`agent_sdk/middlewares/dangling_tool_call.py`）
- [ ] 5.2.2 `ToolErrorHandlingMiddleware`（`agent_sdk/middlewares/tool_error_handling.py`）
- [ ] 5.2.3 `TokenUsageMiddleware`（`agent_sdk/middlewares/token_usage.py`）
- [ ] 5.2.4 `LoopDetectionMiddleware`（`agent_sdk/middlewares/loop_detection.py`）
- [ ] 5.2.5 `DeferredToolFilterMiddleware`（`agent_sdk/middlewares/deferred_tool_filter.py`）
- [ ] 5.2.6 `agent_sdk/middlewares/__init__.py` 导出（更新）
- [ ] 5.2.7 单元测试（5 个 middleware 各 1 个测试文件）
- [ ] 验证：ruff + pytest 全部通过
- [ ] 验证：ADR-010 0 处违规

## 设计要点

### 5.1 SDK 入口与基础设施

**`RuntimeFeatures`**（数据类）
- 7 个字段：`sandbox` / `memory` / `summarization` / `subagent` / `vision` / `auto_title` / `guardrail`
- 每个字段：`True`（用默认）/ `False`（禁用）/ `AgentMiddleware` 实例（自定义）
- `summarization` / `guardrail` 限制为 `False | AgentMiddleware`（无内置默认）

**`@Next` / `@Prev` 装饰器**
- 设置类属性 `_next_anchor` / `_prev_anchor`
- 校验 anchor 是 `AgentMiddleware` 子类
- 仅做位置声明，不立即执行插入

**`ThreadState`**
- 基于 `langchain.agents.AgentState`（`messages` + `jump_to`）
- 提供 reducer：`merge_artifacts` / `merge_viewed_images`（与 backend 行为一致）
- 业务字段（`sandbox` / `thread_data` / `todos` / `uploaded_files`）作为可选项留给 preset 扩展
- 严禁依赖 `deerflow.agents.thread_state`

**`create_agent`**（简化版，与 `create_deerflow_agent` 行为对齐但更小）
- 接受：`model` / `tools` / `system_prompt` / `middleware` / `features` / `extra_middleware` / `state_schema` / `checkpointer` / `name`
- `middleware` 与 `features` 互斥（与 backend 行为一致）
- `extra_middleware` 通过 `@Next` / `@Prev` 插入
- 调用 `langchain.agents.create_agent`
- 严禁 import `backend.*` / `deerflow.*` / `app.*`

### 5.2 5 个通用 middleware

每个 middleware 在 SDK 内部**完全重写**（不复制 backend 文件）。行为对齐点：
- 输入/输出参数签名一致
- 关键决策点（block / warn / pass）行为一致
- 错误信息文案一致

| Middleware | 行为对齐 | 测试覆盖 |
|------------|----------|----------|
| `DanglingToolCall` | 检测 AIMessage.tool_calls 没有对应 ToolMessage 时插入合成错误消息 | 含/不含 tool_calls 消息、含/不含 tool_call_id、多次连续 dangling |
| `ToolErrorHandling` | 把 tool 异常转成 error ToolMessage；保留 GraphBubbleUp | 正常 / 异常 / 多种异常类型 / GraphBubbleUp 透传 |
| `TokenUsage` | 从最后 AIMessage.usage_metadata 记录日志 | 有/无 usage_metadata、缺字段、None |
| `LoopDetection` | hash-based + tool-freq 双重检测；warn / hard-stop 阈值 | LRU eviction、警告去重、硬停止清空 tool_calls、跨线程隔离 |
| `DeferredToolFilter` | 从 request.tools 移除 deferred 工具 | 无 registry、registry 存在时过滤、blocked_tool_message 行为 |

**DeerFlow 业务耦合剥离点**：
- `DeferredToolFilter` 中"`deerflow.tools.builtins.tool_search`" 依赖 → SDK 接受 `deferred_registry_provider: Callable[[], AbstractSet[str] | None]` 参数
- `LoopDetection` 中"thread_id" 通过 `runtime.context.get("thread_id")` 抽取 → SDK 保持同样行为（context 是 LangGraph 标准）

## 产出（全部在 SDK 内部，`backend/` 不动）

```
sdk-extraction/harness/agent_sdk/
├── __init__.py                    # 更新：导出 create_agent, RuntimeFeatures
├── runtime/
│   ├── __init__.py
│   ├── entry.py                   # create_agent()
│   ├── features.py                # RuntimeFeatures
│   ├── decorators.py              # @Next, @Prev
│   └── thread_state.py            # ThreadState + reducers
└── middlewares/
    ├── __init__.py                # 更新：导出 5 个新 middleware
    ├── dangling_tool_call.py      # DanglingToolCallMiddleware
    ├── tool_error_handling.py     # ToolErrorHandlingMiddleware
    ├── token_usage.py             # TokenUsageMiddleware
    ├── loop_detection.py          # LoopDetectionMiddleware
    └── deferred_tool_filter.py    # DeferredToolFilterMiddleware

sdk-extraction/harness/tests/
├── runtime/
│   ├── __init__.py
│   ├── test_features.py
│   ├── test_decorators.py
│   ├── test_thread_state.py
│   └── test_entry.py
└── middlewares/
    ├── test_dangling_tool_call.py
    ├── test_tool_error_handling.py
    ├── test_token_usage.py
    ├── test_loop_detection.py
    └── test_deferred_tool_filter.py
```

## 完成标准

- [ ] 5.1 + 5.2 所有任务完成
- [ ] ruff check 全部通过
- [ ] pytest 100% 通过（包含已有 259 个 + 新增约 60-80 个）
- [ ] 0 处 import `backend.*` / `deerflow.*` / `app.*`
- [ ] `backend/` 全程未触碰

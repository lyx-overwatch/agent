# 阶段 5 第二批：抽象 ABC（Sandbox / UserContext / StreamBridge / GuardrailProvider）

> **为什么独立成批**：5.3 是 4 个独立的 ABC + 数据类，输出形态与其他批次（中间件 / 基础设施）不同。独立成批便于评审。
>
> **第二批范围（5.3）**：
> - 4 个抽象：`Sandbox` / `SandboxProvider` / `UserContext` / `StreamBridge` / `GuardrailProvider`
> - 相关数据类与参考实现
>
> **不在第二批范围（后续批次）**：
> - 5.4 运行时基础设施（LangGraph 集成 / Checkpointer / ModelFactory / ToolLoader / Reflection / Tracing / Utils）
> - 5.5 集成子系统（MCP / Skills / Guardrails 中间件）
> - 5.6 业务特性 middleware（13 个）
> - 5.7 Sandbox 工具实现（1582 行）
> - 5.8 middleware 链装配

## 任务清单

- [x] 5.3.1 `Sandbox` / `SandboxProvider` ABC（`agent_sdk/sandbox/base.py`）
- [x] 5.3.2 `UserContext` 模块（`agent_sdk/runtime/user_context.py`）
- [x] 5.3.3 `StreamBridge` ABC（`agent_sdk/runtime/stream_bridge.py`）
- [x] 5.3.4 `GuardrailProvider` Protocol（`agent_sdk/guardrails/provider.py` + `builtin.py` + `__init__.py`）
- [x] 5.3.5 `agent_sdk/sandbox/__init__.py` 导出更新
- [x] 5.3.6 `agent_sdk/runtime/__init__.py` 导出更新
- [x] 5.3.7 单元测试（4 个测试文件 / 84 个用例）
- [x] 5.3.8 `pyproject.toml` 添加最小依赖 + pytest 配置
- [x] 验证：ruff + pytest 全部通过
- [x] 验证：ADR-010 0 处违规

## 设计要点

### Sandbox / SandboxProvider

**`Sandbox`（ABC）**
- 7 个抽象方法：`execute_command` / `read_file` / `list_dir` / `write_file` / `glob` / `grep` / `update_file`
- 不可变 `id` 属性
- `glob` / `grep` 返回 `(matches, truncated)` 元组，截断标志在第二个元素
- 与 backend `deerflow.sandbox.Sandbox` 字节级行为一致

**`SandboxProvider`（ABC）**
- 3 个抽象方法：`acquire(thread_id=None) -> id` / `get(sandbox_id) -> Sandbox | None` / `release(sandbox_id) -> None`
- 1 个可选方法：`shutdown()`（默认 no-op）
- 1 个类属性：`uses_thread_data_mounts: bool = False`（容器化沙箱可覆盖为 `True`）
- **不包含** backend 的 `get_sandbox_provider` / `set_sandbox_provider` / `reset_sandbox_provider` 单例（避免硬编码进程级单例；按 SDK 设计，provider 由调用方显式构造与注入）

**`GrepMatch`（数据类，frozen）**
- 字段：`path: str` / `line_number: int` / `line: str`
- 与 backend 字段名一致

### UserContext

**`CurrentUser`（Protocol，runtime_checkable）**
- 单字段：`id: str`
- 任何有 `.id: str` 属性的对象结构化满足

**ContextVar helpers**
- `set_current_user(user) -> Token`
- `reset_current_user(token)`
- `get_current_user() -> CurrentUser | None`（从不变 raise）
- `require_current_user() -> CurrentUser`（unset 时 raise `RuntimeError`）
- `get_effective_user_id() -> str`（unset 时回退 `DEFAULT_USER_ID = "default"`；强转 str）

**AUTO sentinel**
- 单例 `_AutoSentinel()`（私有）+ 模块级常量 `AUTO`
- `repr == "<AUTO>"`

**`resolve_user_id(value, *, method_name="repository method")`**
- 三态：`AUTO` → contextvar；`str` → verbatim；`None` → 旁路
- 错误信息包含 `method_name` 便于排错
- 强转 `user.id` 为 `str`（兼容 `UUID` / `int` 等）

### StreamBridge

**`StreamEvent`（frozen dataclass）**
- 字段：`id: str` / `event: str` / `data: Any`
- 保留名 `__heartbeat__` / `__end__` 留给哨兵

**Sentinels**
- `HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)`
- `END_SENTINEL = StreamEvent(id="", event="__end__", data=None)`

**`StreamBridge`（ABC）**
- 4 个抽象方法：`publish` / `publish_end` / `subscribe` (async generator) / `cleanup`
- 1 个可选方法：`close()` 默认 no-op
- `subscribe` 接受 `last_event_id: str | None` 用于 `Last-Event-ID` 重连
- `subscribe` 接受 `heartbeat_interval: float = 15.0` 控制心跳频率
- 契约：fan-out 是 bridge 的责任；iterator 必须终止（`END_SENTINEL` 或 close 异常）
- **不包含** backend 的 `MemoryStreamBridge` 实现（5.4 运行时基础设施阶段会单独建一个 `agent_sdk/runtime/stream_bridge_memory.py`）

### GuardrailProvider

**数据类**
- `GuardrailRequest`：`tool_name` / `tool_input` + 可选 `agent_id` / `thread_id` / `is_subagent` / `timestamp`
- `GuardrailReason`：`code` / `message`（OAP reason object 对齐）
- `GuardrailDecision`：`allow` + `reasons` + `policy_id` + `metadata`（OAP decision object 对齐）

**`GuardrailProvider`（Protocol，runtime_checkable）**
- 属性：`name: str`
- 方法：`evaluate(request) -> Decision`（sync）+ `aevaluate(request) -> Decision`（async）
- 任何同时具备这三个成员的对象结构化满足；in-tree `AllowlistProvider` 不继承该 Protocol

**`AllowlistProvider`（参考实现）**
- 构造：`allowed_tools: list[str] | None` / `denied_tools: list[str] | None`
- 规则顺序：① 允许列表外 → 拒绝（reason `oap.tool_not_allowed`）② 拒绝列表中 → 拒绝 ③ 允许（reason `oap.allowed`）
- `aevaluate` 委托给 `evaluate`（无 async I/O 可优化）
- `name = "allowlist"`

## 产出

```
sdk-extraction/harness/agent_sdk/
├── sandbox/
│   ├── base.py                       # 新增
│   └── __init__.py                   # 更新（导出 Sandbox / SandboxProvider / GrepMatch）
├── runtime/
│   ├── user_context.py               # 新增
│   ├── stream_bridge.py              # 新增
│   └── __init__.py                   # 更新（导出 9 个新符号）
└── guardrails/                       # 新子包
    ├── __init__.py
    ├── provider.py
    └── builtin.py                    # AllowlistProvider

sdk-extraction/harness/tests/
├── sandbox/
│   └── test_base.py                  # 新增
├── runtime/
│   ├── test_user_context.py          # 新增
│   └── test_stream_bridge.py         # 新增
└── guardrails/
    ├── __init__.py
    └── test_provider.py              # 新增
```

## 完成标准

- [x] 5.3 所有任务完成
- [x] ruff check 全部通过
- [x] pytest 100% 通过（累计 477/477）
- [x] 0 处 import `backend.*` / `deerflow.*` / `app.*`
- [x] `backend/` 全程未触碰

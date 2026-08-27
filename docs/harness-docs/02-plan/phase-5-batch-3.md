# 阶段 5 第三批：运行时基础设施（完整范围）

> **范围**：用户已确认完整范围。5.4 是 1 周规模（7+ 个模块），本批完成全部。
>
> **第三批范围（5.4）**：
> - Reflection（`resolve_class` / `resolve_variable`）
> - Utils（PortAllocator）
> - LangGraph 集成（configurable keys / config builders / run id / stream modes）
> - Checkpointer 工厂（3 后端：memory/sqlite/postgres，sync + async）
> - Store 工厂（3 后端 async）
> - ModelFactory（class path → instance + thinking 切换 + stream_usage + tracing）
> - ToolLoader（class path 加载 + dedupe + group 过滤）
> - Tracing 工厂（LangSmith + Langfuse 懒加载回调）
>
> **不在第三批范围（后续批次）**：
> - 5.5 集成子系统（MCP / Skills / Guardrails 完整中间件）
> - 5.6 业务特性 middleware（13 个）
> - 5.7 Sandbox 工具实现（1582 行）
> - 5.8 middleware 链装配

## 任务清单

- [x] 5.4.1 `agent_sdk/reflection/{__init__.py, resolvers.py}` - `resolve_class[T](class_path, base_class)` + `resolve_variable[T](variable_path, expected_type)`；泛型 + 11 个 langchain/langfuse 包名 hint
- [x] 5.4.2 `agent_sdk/utils/{__init__.py, network.py}` - `PortAllocator`（线程安全，0.0.0.0 绑定）+ `get_free_port` / `release_port` 全局 helper
- [x] 5.4.3 `agent_sdk/runtime/langgraph_integration.py` - `make_thread_config` / `merge_configs` / `make_run_id` / `is_valid_thread_id` + configurable key 常量 + stream mode 常量
- [x] 5.4.4 `agent_sdk/runtime/checkpointer/{__init__.py, config.py, factory.py, async_factory.py}` - 3 后端 sync 单例 + sync CM + async CM
- [x] 5.4.5 `agent_sdk/runtime/store/{__init__.py, async_factory.py}` - 3 后端 async CM
- [x] 5.4.6 `agent_sdk/models/{__init__.py, factory.py}` - `ModelConfig` pydantic + `create_chat_model()`
- [x] 5.4.7 `agent_sdk/tools/loader.py` - `ToolConfig` + `load_tools()` + `LoadResult`
- [x] 5.4.8 `agent_sdk/tracing/{__init__.py, factory.py}` - `TracingConfig` + `build_tracing_callbacks()`
- [x] 5.4.9 单元测试（8 个测试文件 / 135 个用例）
- [x] 5.4.10 验证：ruff + pytest + ADR-010

## 设计要点

### 1. Reflection

**`resolve_variable[T](variable_path, expected_type=None) -> T`**
- 接受 `"module.path:attribute"` 路径
- `expected_type` 触发 `isinstance` 校验（失败 → `ValueError`）
- 缺失包用 `MODULE_TO_PACKAGE_HINTS` 翻译成 `uv add langchain-anthropic` 等可操作提示
- `ImportError` 包裹时保留原始错误作为 `__cause__`

**`resolve_class[T](class_path, base_class=None) -> type[T]`**
- 委托给 `resolve_variable(expected_type=type)`
- `base_class` 触发 `issubclass` 校验

### 2. Utils

**`PortAllocator`**
- 线程安全（`threading.Lock`）
- 绑定 `0.0.0.0`（不是 `127.0.0.1`），匹配 Docker 行为
- `allocate_context` context manager 在 exit 时释放端口（包括异常路径）

### 3. LangGraph 集成

**configurable key 常量**：`THREAD_ID` / `USER_ID` / `RUN_ID` / `CHECKPOINT_NS`

**`make_thread_config(thread_id, *, user_id=None, run_id=None, checkpoint_ns="")`**
- 返回 `{"configurable": {...}}` 形状

**`merge_configs(*configs)`**
- `configurable` 块按 key 合并（后者覆盖），其他顶层 key 整体替换
- `None` / `{}` 自动跳过

**`make_run_id()`**
- UUID4 hex（32 字符），URL/header safe

**`is_valid_thread_id(thread_id)`**
- 长度 ≤ 128；仅字母数字 / `-` / `_` / `.`（与 path 组件兼容性）

**stream mode 常量**：`STREAM_MODE_VALUES` 元组 + 单值别名（`STREAM_MODE_UPDATES` / `STREAM_MODE_MESSAGES` / `STREAM_MODE_VALUES_DEFAULT`）

### 4. Checkpointer

**`CheckpointerConfig`**（pydantic）
- `type: "memory" | "sqlite" | "postgres"`
- `connection_string: str | None`（sqlite 文件路径或 postgres DSN）

**三后端实现要点**：
- **memory**：`InMemorySaver`（langgraph 自带，无需 extras）
- **sqlite**：懒加载 `langgraph.checkpoint.sqlite.{aio,}`；父目录自动创建；`:memory:` 透传
- **postgres**：懒加载 `langgraph.checkpoint.postgres.{aio,}`；先校验 `connection_string` 非空（**关键：先校验后 import**，否则缺 extras 时报"缺 import"而不是"缺连接串"）

**API 表面**：
- `configure(config)` / `get_checkpointer()` / `reset_checkpointer()` — 进程级单例
- `checkpointer_context(config=None)` — sync context manager（不缓存）
- `make_checkpointer(config=None)` — async context manager

### 5. Store

**`make_store(config=None)`** — async context manager；与 checkpointer 独立（用户可传相同或不同 config）

### 6. ModelFactory

**`ModelConfig`**（pydantic）：name / use (class path) / display_name / supports_thinking / supports_reasoning_effort / supports_vision / when_thinking_enabled / when_thinking_disabled / thinking / model_settings

**`create_chat_model(config, *, thinking_enabled=False, tracing_callbacks=None, **kwargs)`**
- class path → instance
- thinking 切换：合并 `when_thinking_enabled` 或 `when_thinking_disabled` block
- `supports_thinking=False` 且 `thinking_enabled=True` → `ValueError`
- `supports_reasoning_effort=False` 时静默删除 `reasoning_effort` 设置
- OpenAI-compatible + 自定义 `base_url` → 自动 `stream_usage=True`
- `tracing_callbacks` 合并到 `model.callbacks`（保留已有）

### 7. ToolLoader

**`ToolConfig`**（pydantic）：name / use (class path) / group

**`load_tools(configs=None, *, builtin_tools=None, extra_tools=None, groups=None) -> LoadResult`**
- 按 `groups` 过滤
- config 工具先按 class path 解析
- name mismatch（config name vs tool.name）记录到 `LoadResult.mismatched_names` + WARNING
- 重复名 → 跳过（保留首次出现），记录到 `skipped_duplicates`
- 顺序：`config → builtin → extra`

### 8. Tracing

**配置 dataclass**：
- `LangSmithConfig`（project）
- `LangfuseConfig`（secret_key / public_key / host）
- `TracingConfig`（providers 列表 + 两个子 config）

**`build_tracing_callbacks(config=None, *, raise_on_missing=False)`**
- 缺包默认 WARNING 跳过（生产环境不因单个 tracing provider 故障导致模型不可用）
- `raise_on_missing=True` 切换到 `RuntimeError` 硬失败
- 未知 provider 名称 WARNING 跳过

## 产出

```
agent_sdk/
├── reflection/                       # 新子包
│   ├── __init__.py
│   └── resolvers.py
├── utils/                            # 新子包
│   ├── __init__.py
│   └── network.py
├── runtime/
│   ├── langgraph_integration.py      # 新增
│   ├── checkpointer/                 # 新子包
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── factory.py
│   │   └── async_factory.py
│   └── store/                        # 新子包
│       ├── __init__.py
│       └── async_factory.py
├── models/                           # 新子包
│   ├── __init__.py
│   └── factory.py
├── tools/
│   └── loader.py                     # 新增（__init__.py 更新）
└── tracing/                          # 新子包
    ├── __init__.py
    └── factory.py

tests/
├── test_reflection.py                # 新增
├── test_models.py                    # 新增
├── test_tools_loader.py              # 新增
├── test_tracing.py                   # 新增
├── utils/
│   └── test_network.py               # 新增
└── runtime/
    ├── test_langgraph_integration.py # 新增
    ├── test_checkpointer.py          # 新增
    └── test_store.py                 # 新增
```

## 完成标准

- [x] 5.4 所有任务完成
- [x] ruff check 全部通过
- [x] pytest 100% 通过（累计 612/612）
- [x] 0 处 import `backend.*` / `deerflow.*` / `app.*`
- [x] `backend/` 全程未触碰

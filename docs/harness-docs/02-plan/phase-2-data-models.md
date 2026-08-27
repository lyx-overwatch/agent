# 阶段 2：Memory / Subagent / Tools 数据模型抽象（2 周）

> 解开数据模型和工具命名的硬编码，建立 `MemorySchema` / `SubagentRegistry` / `ToolName` 注入点。

## 目标

把以下硬编码替换为可注入的 Protocol/参数：
- `workContext` / `personalContext` / `topOfMind` 三段式数据模型
- `general-purpose` / `bash` subagent 角色定义
- `ask_clarification` / `present_files` / `view_image` 工具命名

## 关键交付物

1. **`MemorySchema` Protocol**（SDK 内部，`agent_sdk/memory/schema.py`）
2. **`SubagentRegistry` Protocol**（SDK 内部，`agent_sdk/subagents/registry.py`）
3. **`ToolName` 参数化**（每个 builtin tool 接受名称参数，`agent_sdk/tools/factory.py`）
4. **SDK 版 `MemoryMiddleware` / `MemoryUpdater`**（`agent_sdk/memory/middleware.py`、`updater.py`）
5. **SDK 版 `SubagentExecutor` / `task tool`**（`agent_sdk/subagents/executor.py`、`agent_sdk/tools/task.py`）
6. **SDK 版 builtin tools**（`agent_sdk/tools/clarification.py` 等）

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/memory/*` 任何文件
- ❌ 修改 `backend/packages/harness/deerflow/subagents/builtins/*` 任何文件
- ❌ 修改 `backend/packages/harness/deerflow/tools/builtins/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`

## 任务清单

### 2.1 设计 `MemorySchema` Protocol（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/memory/schema.py`

**设计**：
```python
from typing import Protocol, Any


class MemorySchema(Protocol):
    """Defines the data model for long-term memory.

    Different products may use different schemas:
    - DeerFlow: workContext / personalContext / topOfMind
    - Others: user preferences, conversation history, etc.
    """

    def to_dict(self) -> dict[str, Any]:
        """Serialize the memory data to a dict for storage."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemorySchema":
        """Deserialize memory data from storage."""
        ...

    def get_user_profile(self) -> dict[str, Any]:
        """Get user-level information (injected into system prompt)."""
        ...

    def get_conversation_history(self) -> list[dict[str, Any]]:
        """Get past conversation summaries."""
        ...
```

### 2.2 创建 `DeerFlowMemorySchema` 实现（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/presets/deerflow/memory.py`

**设计**：
```python
class DeerFlowMemorySchema:
    """DeerFlow memory schema: workContext / personalContext / topOfMind."""

    def __init__(self, data: dict):
        self._data = data or create_empty_memory()

    def to_dict(self) -> dict:
        return self._data

    @classmethod
    def from_dict(cls, data: dict) -> "DeerFlowMemorySchema":
        return cls(data)

    def get_user_profile(self) -> dict:
        user = self._data.get("user", {})
        return {
            "work_context": user.get("workContext", {}).get("summary", ""),
            "personal_context": user.get("personalContext", {}).get("summary", ""),
            "top_of_mind": user.get("topOfMind", {}).get("summary", ""),
        }

    def get_conversation_history(self) -> list[dict]:
        history = self._data.get("history", {})
        return [
            {"period": "recent_months", "summary": history.get("recentMonths", {}).get("summary", "")},
            {"period": "earlier_context", "summary": history.get("earlierContext", {}).get("summary", "")},
            {"period": "long_term", "summary": history.get("longTermBackground", {}).get("summary", "")},
        ]
```

### 2.3 在 SDK 中实现 MemoryMiddleware 和 MemoryUpdater（2 天）

**位置**：`sdk-extraction/harness/agent_sdk/memory/middleware.py`、`updater.py`

**任务**：以新代码实现 SDK 版 `MemoryMiddleware` 和 `MemoryUpdater`，使用新的 `MemorySchema` Protocol，构造参数 `memory_schema: MemorySchema`。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/memory/storage.py`
- ❌ 修改 `backend/packages/harness/deerflow/agents/memory/updater.py`
- ❌ 修改 `backend/packages/harness/deerflow/agents/memory/middleware.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`

**做法**：
- 读 `backend/agents/memory/storage.py` 作为行为参考
- 在 SDK 内部**重新写**等价实现
- `create_empty_memory()` 函数移到 `DefaultMemorySchema`（无业务假设的默认实现）
- `workContext` / `personalContext` / `topOfMind` 三段式数据移到 `DeerFlowMemorySchema` preset
- 单元测试与 `backend/` 行为字节级一致（golden fixture 模式）

### 2.4 在 SDK 中定义 MemoryStorage（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/memory/storage.py`

**任务**：在 SDK 内部**新定义** `MemoryStorage(ABC, Generic[T])`，使用泛型签名 `load() -> T`（返回 `MemorySchema` 实例）。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/memory/storage.py` 中的 `MemoryStorage` ABC 签名
- ❌ 通过继承方式实现 SDK 版 `MemoryStorage`（即不 `from backend... import MemoryStorage`）

**做法**：
- SDK 内部独立定义 `MemoryStorage` ABC，不依赖 `backend/` 版本
- `FileMemoryStorage` 在 SDK 内部重新实现，使用 SDK 版的 `MemoryStorage` ABC + `PathProvider`
- 提供 Protocol 风格替代方案（如果不需要严格 ABC）

### 2.5 设计 `SubagentRegistry` Protocol（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/subagents/registry.py`

**设计**：
```python
class SubagentDefinition(Protocol):
    name: str
    description: str
    system_prompt: str
    tools: list[str] | None  # None = 继承所有
    disallowed_tools: list[str] | None
    model: str | None  # None = 继承
    max_turns: int | None


class SubagentRegistry(Protocol):
    """Registry of available subagent types."""

    def get(self, name: str) -> SubagentDefinition | None:
        """Get a subagent definition by name."""
        ...

    def list(self) -> list[str]:
        """List all available subagent names."""
        ...

    def register(self, definition: SubagentDefinition) -> None:
        """Register a new subagent (custom)."""
        ...
```

### 2.6 创建 `DeerFlowSubagentRegistry` 实现（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/presets/deerflow/subagents.py`

**设计**：
```python
class DeerFlowSubagentRegistry:
    """DeerFlow's default subagent definitions: general-purpose and bash."""

    def __init__(self):
        self._builtins = {
            "general-purpose": SubagentDefinition(
                name="general-purpose",
                description="For ANY non-trivial task...",
                system_prompt=GENERAL_PURPOSE_PROMPT,
                tools=None,  # 继承所有
                ...
            ),
            "bash": SubagentDefinition(
                name="bash",
                description="For command execution...",
                system_prompt=BASH_PROMPT,
                tools=["bash"],
                ...
            ),
        }
        self._custom: dict[str, SubagentDefinition] = {}

    def get(self, name: str) -> SubagentDefinition | None:
        return self._builtins.get(name) or self._custom.get(name)
    # ...
```

### 2.7 在 SDK 中实现 SubagentExecutor 和 task tool（2 天）

**位置**：`sdk-extraction/harness/agent_sdk/subagents/executor.py`、`agent_sdk/tools/task.py`

**任务**：以新代码实现 SDK 版 `SubagentExecutor` 和 `task tool`，使用 `SubagentRegistry` 注入，构造参数 `registry: SubagentRegistry`。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/subagents/builtins/*` 任何文件
- ❌ 修改 `backend/packages/harness/deerflow/subagents/executor.py` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ "built-ins/ 移到 `presets/deerflow/`"——`backend/subagents/builtins/` **保持原状**

**做法**：
- SDK 内部重新实现 `SubagentExecutor`，参数 `registry: SubagentRegistry`
- SDK 内部重新实现 `task_tool`，通过 `registry.get(subagent_type)` 查找角色
- `general-purpose` / `bash` 角色定义在 `agent_sdk/presets/deerflow/subagents.py` **重新录入**（不 import `backend/subagents/builtins/`）
- 单元测试与 `backend/` 行为字节级一致

### 2.8 在 SDK 中实现 builtin tool factory（2 天）

**位置**：`sdk-extraction/harness/agent_sdk/tools/factory.py`、`agent_sdk/tools/clarification.py`、`agent_sdk/tools/present_file.py`、`agent_sdk/tools/view_image.py`、`agent_sdk/tools/setup_agent.py`、`agent_sdk/tools/invoke_acp.py`、`agent_sdk/tools/task.py`

**任务**：以新代码实现 SDK 版 builtin tool 工厂，每个 tool 函数接受 `tool_name: str` 参数，装饰器动态生成。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/tools/builtins/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ "tools/builtins/ 移到 `presets/deerflow/tools/`"——`backend/tools/builtins/` **保持原状**

**做法**：
- 工厂模式：
  ```python
  # agent_sdk/tools/factory.py
  def make_ask_clarification_tool(tool_name: str = "ask_clarification"):
      @tool(tool_name, parse_docstring=True)
      def ask_clarification(...):
          ...
      return ask_clarification
  ```
- 6 个 builtin tool（ask_clarification、present_files、view_image、task、setup_agent、invoke_acp_agent）每个在 SDK 内部**独立文件**重新实现
- 工具命名 `ask_clarification` / `present_files` 等作为默认参数；`DeerFlowAgent` 创建时传入与 `backend/` 一致的命名
- 单元测试验证命名和描述与 `backend/` 一致

### 2.9 写单元测试（1 天）

**测试文件**：
- `sdk-extraction/harness/tests/memory/test_schema.py`
- `sdk-extraction/harness/tests/subagents/test_registry.py`
- `sdk-extraction/harness/tests/tools/test_naming.py`

**测试用例**：
- [ ] `DefaultMemorySchema` 正常工作
- [ ] `DeerFlowMemorySchema` 与原版行为一致
- [ ] `DeerFlowSubagentRegistry` 包含 general-purpose / bash
- [ ] 自定义 `SubagentRegistry` 可注入
- [ ] 工具命名参数化生效
- [ ] 工具描述保留

### 2.10 验证 SDK 与 backend 行为字节级一致（1 天）

**成功标准**：
- SDK 内部单元测试 100% 通过
- 记忆内容（`workContext` / `personalContext` / `topOfMind` 等字段）与 `backend/agents/memory/storage.py` 行为**字节级一致**（golden fixture 对比）
- subagent 角色（`general-purpose` / `bash`）与 `backend/subagents/builtins/` 一致
- 工具名称和描述（`ask_clarification` / `present_files` / `view_image` 等）与 `backend/tools/builtins/*` 一致
- `backend/tests/` 基线回归通过（**仅运行**，**不修改**其中任何代码、fixture 或 conftest.py）

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| `MemorySchema` 抽象不完整 | 高 | 保留 `to_dict` / `from_dict` 接口确保字节级兼容 |
| `SubagentDefinition` 字段遗漏 | 中 | 详细对比现有 builtin；保留扩展点 |
| 工具命名参数化破坏 LLM 工具调用 | 中 | 默认值与原版一致；测试覆盖 |
| `MemoryStorage` 泛型化引入类型问题 | 低 | 谨慎处理；保留 `dict` 兼容路径 |

## 依赖

- 阶段 1（PathProvider）完成

## 产出

- `sdk-extraction/harness/agent_sdk/memory/`
  - `schema.py` - MemorySchema Protocol
  - `default.py` - DefaultMemorySchema
- `sdk-extraction/harness/agent_sdk/subagents/`
  - `registry.py` - SubagentRegistry Protocol
  - `definition.py` - SubagentDefinition 数据类
- `sdk-extraction/harness/agent_sdk/tools/`
  - `factory.py` - 工具工厂（接受 tool_name 参数）
- `sdk-extraction/harness/agent_sdk/presets/deerflow/`
  - `memory.py` - DeerFlowMemorySchema
  - `subagents.py` - DeerFlowSubagentRegistry
  - `tools.py` - 工具 preset
- `sdk-extraction/harness/tests/`
  - `memory/`
  - `subagents/`
  - `tools/`

## 完成标准

- [ ] 2.1-2.10 全部完成
- [ ] SDK 单元测试 100% 通过
- [ ] DeerFlow 回归测试 100% 通过
- [ ] 文档更新

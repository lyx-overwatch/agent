# 阶段 3：Audit / Prompt 抽象（1 周）

> 解开安全规则和 prompt 文案的硬编码。

## 目标

把以下硬编码替换为可注入的 Protocol/参数：
- `chmod 777` / `LD_PRELOAD` / fork bomb 等安全规则
- TodoList system_prompt 和 tool description
- 任何其他硬编码 prompt 文案

## 关键交付物

1. **`AuditRules` Protocol**（SDK 内部）
2. **`TodoSystemPrompt` / `TodoToolDescription` 参数化**
3. **`AuditMiddleware` 抽到 SDK**
4. **`DeerFlowAuditRules` preset**

## 任务清单

### 3.1 设计 `AuditRules` Protocol（半天）

**文件**：`sdk-extraction/harness/agent_sdk/sandbox/audit/rules.py`

**设计**：
```python
from dataclasses import dataclass
from typing import Protocol
import re


@dataclass
class AuditPattern:
    pattern: re.Pattern[str]
    risk_level: str  # "high" | "medium" | "low"
    description: str


class AuditRules(Protocol):
    """Defines the security audit rules for command execution."""

    def get_high_risk_patterns(self) -> list[AuditPattern]:
        """Patterns that should BLOCK command execution."""
        ...

    def get_medium_risk_patterns(self) -> list[AuditPattern]:
        """Patterns that should WARN but allow execution."""
        ...

    def get_low_risk_patterns(self) -> list[AuditPattern]:
        """Patterns that are LOGGED but not warned."""
        ...
```

### 3.2 创建 `DeerFlowAuditRules` 实现（半天）

**文件**：`sdk-extraction/harness/agent_sdk/presets/deerflow/audit.py`

**设计**：
```python
class DeerFlowAuditRules:
    """DeerFlow's default audit rules."""

    # 由 SDK 作者按 backend/agents/middlewares/sandbox_audit_middleware.py 现有规则重新录入
    # 绝对禁止：from backend.* import ... 或从 backend 文件复制粘贴
    _HIGH_RISK = [
        AuditPattern(re.compile(r"rm\s+-[^\s]*r[^\s]*\s+(/\*?|~/?\*?|...)"), "high", "rm -rf on root"),
        AuditPattern(re.compile(r"dd\s+if="), "high", "dd disk operation"),
        # ... 所有现有高危规则
    ]

    _MEDIUM_RISK = [
        AuditPattern(re.compile(r"chmod\s+777"), "medium", "world-writable permissions"),
        # ...
    ]

    def get_high_risk_patterns(self) -> list[AuditPattern]:
        return self._HIGH_RISK

    def get_medium_risk_patterns(self) -> list[AuditPattern]:
        return self._MEDIUM_RISK
```

**绝对禁止**：
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 从 `backend/agents/middlewares/sandbox_audit_middleware.py` 复制粘贴规则列表

### 3.3 在 SDK 中实现 SandboxAuditMiddleware（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/sandbox/audit/middleware.py`

**任务**：以新代码实现 SDK 版 `SandboxAuditMiddleware`，构造参数 `audit_rules: AuditRules | None = None`（默认 `DeerFlowAuditRules`）。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`

**做法**：
- SDK 内部**重新写** `SandboxAuditMiddleware`，构造参数 `audit_rules: AuditRules | None`
- 默认无注入时使用 `DeerFlowAuditRules()`（在 `agent_sdk/presets/deerflow/audit.py`）
- 读 `backend/agents/middlewares/sandbox_audit_middleware.py` 作为行为参考，验证 SDK 版与 `backend/` 行为字节级一致

```python
class SandboxAuditMiddleware(AgentMiddleware):
    def __init__(self, audit_rules: AuditRules | None = None):
        self._rules = audit_rules or DeerFlowAuditRules()

    def _check_command(self, command: str) -> tuple[bool, str]:
        for pattern in self._rules.get_high_risk_patterns():
            if pattern.pattern.search(command):
                return False, f"BLOCKED: {pattern.description}"
        # ... etc
```

### 3.4 在 SDK 中实现 TodoMiddleware（支持 prompt 注入）（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/middlewares/todo/middleware.py`

**任务**：以新代码实现 SDK 版 `TodoMiddleware`，构造参数 `prompts: TodoPrompts | None = None`（默认 `TodoPrompts()` 使用无 DeerFlow 业务假设的最小通用文案）。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/factory.py` 中的 `_TODO_SYSTEM_PROMPT` / `_TODO_TOOL_DESCRIPTION` 常量
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`

**做法**：
- SDK 内部**重新写** `TodoMiddleware`，构造参数 `prompts: TodoPrompts | None`
- 默认 `TodoPrompts` 使用**无 DeerFlow 业务假设的最小通用文案**（如"Use write_todos for tasks with 3+ steps"这种通用规则）
- DeerFlow 业务 prompt 移到 `agent_sdk/presets/deerflow/prompts/todo.py`，由 `DeerFlowTodoPrompts` 重新录入
- 读 `backend/agents/factory.py` 作为行为参考

```python
@dataclass
class TodoPrompts:
    system_prompt: str
    tool_description: str


class TodoMiddleware(AgentMiddleware):
    def __init__(
        self,
        prompts: TodoPrompts | None = None,
        tool_name: str = "write_todos",
    ):
        prompts = prompts or TodoPrompts(
            system_prompt=DEFAULT_TODO_SYSTEM_PROMPT,
            tool_description=DEFAULT_TODO_TOOL_DESCRIPTION,
        )
        ...
```

### 3.5 默认 prompt 移到 SDK 常量（半天）

**文件**：`sdk-extraction/harness/agent_sdk/middlewares/todo/defaults.py`

**设计**：
```python
# 最小可用的 TodoList prompt（无 DeerFlow 业务）
DEFAULT_TODO_SYSTEM_PROMPT = """
<todo_list_system>
You have access to the `write_todos` tool to help manage complex multi-step objectives.
Rules:
- Mark todos as completed IMMEDIATELY after finishing each step
- Keep exactly one task as `in_progress` at any time
- Use this for complex tasks (3+ steps); for simple tasks, complete directly
</todo_list_system>
"""

DEFAULT_TODO_TOOL_DESCRIPTION = """
Use this tool to create and manage a structured task list for complex work sessions.
Only use for complex tasks (3+ steps).
"""
```

### 3.6 DeerFlow 业务 prompt 移到 preset（半天）

**文件**：`sdk-extraction/harness/agent_sdk/presets/deerflow/prompts/todo.py`

**设计**：
```python
# DeerFlow 风格的 TodoList prompt（760 行原 prompt 的一部分）
DEERFLOW_TODO_SYSTEM_PROMPT = """
<todo_list_system>
You have access to the `write_todos` tool...
**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly
...
"""  # 完整保留 DeerFlow 文案

DEERFLOW_TODO_TOOL_DESCRIPTION = "..."  # 完整保留
```

### 3.7 验证 SDK 内部 system_prompt 不被硬编码（半天）

**审查范围**（**仅限 SDK 内部**）：
- `sdk-extraction/harness/agent_sdk/middlewares/sandbox.py`
- `sdk-extraction/harness/agent_sdk/middlewares/memory.py`
- `sdk-extraction/harness/agent_sdk/middlewares/uploads.py`
- `sdk-extraction/harness/agent_sdk/middlewares/view_image.py`
- `sdk-extraction/harness/agent_sdk/middlewares/subagent_limit.py`
- `sdk-extraction/harness/agent_sdk/middlewares/llm_error.py`
- `sdk-extraction/harness/agent_sdk/middlewares/summarization.py`

**绝对禁止**：
- ❌ 审查或修改 `backend/packages/harness/deerflow/agents/middlewares/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`

**目标**：所有 SDK 内部 middleware 的 `state["messages"]` 注入文本都通过参数传入，不硬编码；不引用 `backend/` 任何 prompt。

### 3.8 写单元测试（半天）

**测试用例**：
- [ ] `DeerFlowAuditRules` 包含原版所有规则
- [ ] 自定义 `AuditRules` 生效
- [ ] 默认 `TodoPrompts` 工作
- [ ] `DeerFlowTodoPrompts` 与原版一致
- [ ] `SandboxAuditMiddleware` 阻断高危命令

### 3.9 验证 DeerFlow 行为不变（半天）

**成功标准**：
- 现有测试 100% 通过
- 审计规则与原版字节级一致
- TodoList prompt 与原版一致

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| 审计规则遗漏某些 edge case | 中 | 详细对比原文件；保留 `DeerFlowAuditRules` 完整实现 |
| TodoList prompt 文案差异 | 中 | 字节级对比；测试覆盖 |
| 漏掉某处硬编码 prompt | 中 | 全文搜索 `'<'` 模式；逐步审查 |

## 依赖

- 阶段 1-2 完成

## 产出

- `sdk-extraction/harness/agent_sdk/sandbox/audit/`
  - `rules.py` - AuditRules Protocol
  - `default.py` - DefaultAuditRules（空规则）
  - `middleware.py` - SandboxAuditMiddleware
- `sdk-extraction/harness/agent_sdk/middlewares/todo/`
  - `prompts.py` - TodoPrompts 数据类 + 默认值
- `sdk-extraction/harness/agent_sdk/presets/deerflow/`
  - `audit.py` - DeerFlowAuditRules
  - `prompts/todo.py` - DeerFlowTodoPrompts

## 完成标准

- [ ] 3.1-3.9 全部完成
- [ ] SDK 单元测试 100% 通过
- [ ] DeerFlow 回归测试 100% 通过

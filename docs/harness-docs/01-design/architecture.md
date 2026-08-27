# 总体架构：三层分离

## 目标架构图

```
┌─────────────────────────────────────────────────────────────┐
│  sdk-extraction/harness/                       [SDK 输出]      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Layer 1: 通用抽象 (Pure)                              │ │
│  │  LangGraph 集成、5 个通用 middleware、ABC             │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ Layer 2: 特性实现 (Feature + Protocol 注入)          │ │
│  │  memory / todo / subagent / uploads / sandbox 工具   │ │
│  │  + Protocol 抽象（PathProvider, MemorySchema 等）     │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ Layer 3: DeerFlow Preset (Product)                    │ │
│  │  agent_sdk.presets.deerflow                            │ │
│  │  路径、数据模型、prompt、工具名、安全规则             │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↑
                              │ pip install
                              │
┌─────────────────────────────────────────────────────────────┐
│  backend/  [DeerFlow 应用 - 抽离期间不动]                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  app/  (FastAPI Gateway, IM 集成)                     │ │
│  │  langgraph.json  (lead_agent 入口)                    │ │
│  │  packages/harness/deerflow/  (现有代码)               │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↑
                              │ import (after migration)
                              │
                          (未来)
```

## SDK 内部三层详解

### Layer 1: 通用抽象（Pure）

**职责**：任何 agent runtime 都需要的基础设施

**内容**：
- LangChain / LangGraph 0.6+ 集成
- 5 个通用 middleware：
  - `DanglingToolCallMiddleware`
  - `ToolErrorHandlingMiddleware`
  - `TokenUsageMiddleware`
  - `LoopDetectionMiddleware`
  - `DeferredToolFilterMiddleware`
- 抽象 ABC：
  - `Sandbox` / `SandboxProvider`
  - `MemoryStorage`
  - `UserContext`
  - `StreamBridge`
- `RuntimeFeatures` 数据类
- `@Next` / `@Prev` 装饰器
- `create_agent()` 入口

**特点**：
- 无任何 DeerFlow 业务耦合
- 无任何硬编码路径 / 字段名 / prompt
- 可独立 `pip install` 并使用

### Layer 2: 特性实现（Feature + Protocol 注入）

**职责**：DeerFlow 现有的所有 agent 特性，每个特性的业务选择通过 Protocol 解耦

**内容**：
| 特性 | 实现位置 | 业务注入点 |
|------|----------|------------|
| 任务规划 | `TodoMiddleware` | `TodoSystemPrompt` Protocol |
| 长期记忆 | `MemoryMiddleware` + `MemoryUpdater` | `MemorySchema` Protocol |
| 多 Agent | `SubagentExecutor` | `SubagentRegistry` Protocol |
| 文件管理 | `UploadsMiddleware` | `PathProvider` |
| 沙箱 | `SandboxMiddleware` + 工具 | `PathProvider` + `AuditRules` |
| 安全审计 | `SandboxAuditMiddleware` | `AuditRules` Protocol |
| Skills | `SkillsLoader` + `SkillsInstaller` | （协议本身通用） |
| MCP | `MCPClient` + `MCPCache` | （协议本身通用） |
| Guardrails | `GuardrailMiddleware` | （OAP 协议通用） |

**特点**：
- 特性逻辑保留
- 业务选择通过 Protocol 注入
- 可选择性启用（通过 `RuntimeFeatures` 开关）

### Layer 3: DeerFlow Preset（Product）

**职责**：打包 DeerFlow 的所有业务选择，作为 SDK 的"产品预设"

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/`

**内容**：
- `DEERFLOW_PATHS`：`DeerFlowPathProvider` 实现（`/mnt/user-data`）
- `DEERFLOW_MEMORY_SCHEMA`：memory.json 的 workContext/personalContext/topOfMind 数据模型
- `DEERFLOW_PROMPT`：760 行 DeerFlow 系统 prompt
- `DEERFLOW_SUBAGENTS`：general-purpose / bash 角色定义
- `DEERFLOW_AUDIT_RULES`：bash 黑名单规则
- `DEERFLOW_TOOL_NAMES`：ask_clarification / present_files / view_image 等命名
- `DeerFlowAgent`：包装 `create_agent` 的便利类

**特点**：
- DeerFlow 应用通过 preset 导入
- 行为与抽离前完全一致
- 可选择性使用（不依赖）

## 用户视角

### DeerFlow 用户

```python
# 推荐用法（行为与抽离前完全一致）
from agent_sdk.presets.deerflow import DeerFlowAgent

client = DeerFlowAgent()

# 或显式启用 preset
from agent_sdk import create_agent
from agent_sdk.presets.deerflow import (
    DEERFLOW_PATHS,
    DEERFLOW_MEMORY_SCHEMA,
    DEERFLOW_PROMPT,
    DEERFLOW_SUBAGENTS,
    DEERFLOW_AUDIT_RULES,
)
from agent_sdk.agents.features import RuntimeFeatures

agent = create_agent(
    model=model,
    system_prompt=DEERFLOW_PROMPT,
    path_provider=DEERFLOW_PATHS,
    memory_schema=DEERFLOW_MEMORY_SCHEMA,
    subagent_registry=DEERFLOW_SUBAGENTS,
    audit_rules=DEERFLOW_AUDIT_RULES,
    features=RuntimeFeatures(
        memory=True,
        todo=True,
        subagent=True,
        vision=True,
        auto_title=True,
    ),
)
```

### 其他项目用户

```python
from agent_sdk import create_agent
from agent_sdk.agents.features import RuntimeFeatures
from agent_sdk.paths import PathProvider
from agent_sdk.memory import MemorySchema
from langchain_openai import ChatOpenAI


class MyPathProvider(PathProvider):
    def get_workspace_dir(self, thread_id: str) -> Path:
        return Path(f"/workspace/{thread_id}")
    # ... 其他方法


class MyMemorySchema(MemorySchema):
    def get_user_profile(self) -> dict:
        return {"name": "user", "preferences": []}
    # ... 其他方法


agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    system_prompt="You are a helpful assistant.",
    path_provider=MyPathProvider(),
    memory_schema=MyMemorySchema(),
    features=RuntimeFeatures(
        memory=True,
        todo=True,
        subagent=True,
    ),
)
```

## 关键设计原则

### 1. 协议优先（Protocol-First）

每个业务选择都先定义 Protocol，然后：
- SDK 提供 Protocol 抽象
- Preset 提供 Protocol 的 DeerFlow 实现
- 用户可提供自己的实现

### 2. 默认即 preset（DeerFlow-Friendly）

SDK 默认不预装任何业务选择，但：
- 引入 `agent_sdk.presets.deerflow` 时**一行启用**
- DeerFlow 应用使用 preset 时行为完全不变

### 3. 可选启用（Opt-in Features）

`RuntimeFeatures` 让用户控制启用哪些特性：
- `memory=False` 不启用长期记忆
- `todo=False` 不启用任务规划
- `subagent=False` 不启用多 agent

### 4. 不破坏现有（Backward Compatible）

- 抽离期间 `backend/` 完全不动
- 抽离完成后，DeerFlow 通过 preset 保持原行为
- 旧代码与新 SDK 可共存

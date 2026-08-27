# 项目目标

## 核心目标

把 `backend/packages/harness/deerflow`（**框架+应用混合**）抽离成 **feature-rich + brand-neutral** 的通用 Python SDK。

## 子目标

### 1. 特性完整性
SDK 提供 DeerFlow 现有的所有 agent 特性：
- 任务规划（TodoList）
- 长期记忆（Memory）
- 多 Agent 协同（Subagent）
- 文件管理（Uploads / Workspace / Outputs）
- 沙箱（Sandbox）
- 安全审计（Sandbox Audit）
- Skills（SKILL.md 协议）
- MCP 集成
- Guardrails（OAP 协议）

### 2. 品牌中性
所有 DeerFlow 业务选择通过 Protocol/参数注入，可被任意项目替换：
- 路径前缀（`/mnt/user-data` → 用户可注入）
- 数据模型（`workContext` 三段式 → 用户可注入）
- 工具名（`ask_clarification` → 用户可注入）
- Prompt 文案（"open-source super agent" → 用户可注入）
- Subagent 角色（`general-purpose` / `bash` → 用户可注入）
- 安全规则（`chmod 777` 黑名单 → 用户可注入）

### 3. 独立可发布
`sdk-extraction/harness/` 最终是一个独立 Python 包，可：
- `pip install` 到任何项目
- 不依赖 `backend/` 任何代码
- 可选择性 import `agent_sdk.presets.deerflow` 启用 DeerFlow 业务

### 4. 不破坏现有
抽离过程中 `backend/` 现有代码**完全不动**，确保：
- DeerFlow 应用行为不变
- 测试套件不需要修改
- 抽离可分阶段进行，每阶段结束 DeerFlow 都可正常工作

## 成功标准

### 标准 1：任意 Python 项目可用 SDK
```python
# 任何非 DeerFlow 项目都能写这样的代码
from agent_sdk import create_agent
from langchain_openai import ChatOpenAI

agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    system_prompt="You are a helpful assistant.",
    features=RuntimeFeatures(memory=True, todo=True, subagent=True),
)
result = agent.invoke({"messages": [("user", "Hello")]})
assert "messages" in result
```

### 标准 2：DeerFlow 应用行为不变
```python
# DeerFlow 应用从 preset 导入
from agent_sdk.presets.deerflow import DeerFlowAgent

client = DeerFlowAgent()
response = client.chat("Hello", thread_id="t1")
# 行为与抽离前完全一致（包括 prompt 内容、工具名、内存格式等）
```

### 标准 3：SDK 可独立发布
```bash
# 任何项目都能这样安装
pip install agent-sdk

# 任何项目都能选择性启用 DeerFlow preset
pip install agent-sdk[deerflow-preset]
```

### 标准 4：协议化完成
所有 L1 业务耦合点都有对应的 Protocol：
- `PathProvider` Protocol（路径）
- `MemorySchema` Protocol（数据模型）
- `SubagentRegistry` Protocol（角色注册）
- `AuditRules` Protocol（审计规则）
- `ToolName` Protocol 或参数（工具命名）

## 非目标（见 `non-goals.md`）

明确**不做**的事情，避免 scope creep。

## 关键参考

- 包结构分析：`05-archive/HARNESS_PACKAGE_ANALYSIS.md`
- 业务耦合分析：`05-archive/HARNESS_BUSINESS_COUPLING.md`
- 架构设计：`01-design/architecture.md`
- 阶段计划：`02-plan/phases.md`

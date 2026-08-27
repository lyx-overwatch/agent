# DeerFlow SDK 抽离项目

> 把 `backend/packages/harness/deerflow` 抽离成 feature-rich + brand-neutral 的通用 Python SDK

## 一句话说明

当前 `deerflow-harness` 包是"框架+应用混合体"——里面既有通用的 agent runtime 逻辑，也有 DeerFlow 产品特有的业务选择（路径名、数据模型、工具名、prompt 文案）。

本项目把这两层**解耦**：
- **SDK 层**（`sdk-extraction/harness/`）：保留所有 agent 特性，但所有业务选择通过 Protocol 注入
- **Preset 层**（SDK 内部）：打包 DeerFlow 的所有业务选择，作为 SDK 的"产品预设"

抽离完成后，DeerFlow 应用通过 preset 保持原行为，其他项目可使用 SDK 但用自己注入业务选择。

## 关键设计

- SDK 保留 DeerFlow 的所有 agent 特性：任务规划、长期记忆、多 agent 协同、文件管理、沙箱、审计、Skills、MCP
- SDK 不绑定 DeerFlow 的业务选择：路径前缀、数据模型、工具名、prompt 文案**全部可注入**
- DeerFlow 应用通过 preset 使用 SDK 的特性
- 抽离过程中 `backend/` 现有代码**完全不动**

## 状态

- **当前阶段**：阶段 0（脚手架）
- **详细进度**：`docs/03-status/progress.md`
- **决策日志**：`docs/03-status/decisions.md`

## 文档导航

| 路径 | 内容 |
|------|------|
| `00-vision/` | WHY - 为什么做这件事（目标、范围、非目标） |
| `01-design/` | WHAT - 怎么设计（架构、边界、特性清单） |
| `02-plan/` | HOW - 怎么分步（阶段计划） |
| `03-status/` | NOW - 当前状态（进度、决策、阻塞、变更） |
| `04-specs/` | DETAIL - 详细规格（待填充） |
| `05-archive/` | 历史分析文档 |

## SDK 输出

- 目录：`sdk-extraction/harness/`
- 当前状态：脚手架
- 最终目标：独立可发布的 Python 包

## 用法预览（抽离完成后）

```python
# DeerFlow 用户（行为与抽离前完全一致）
from agent_sdk.presets.deerflow import DeerFlowAgent

client = DeerFlowAgent()

# 其他项目用户（自己注入所有业务选择）
from agent_sdk import create_agent
from langchain_openai import ChatOpenAI

agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    system_prompt="You are a helpful assistant.",
    features=RuntimeFeatures(
        memory=True,
        todo=True,
        subagent=True,
    ),
)
```

## 历史

- 2026-07-03: 项目启动
- 详见 `docs/03-status/changelog.md`

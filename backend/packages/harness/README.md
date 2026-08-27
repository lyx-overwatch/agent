# agent-sdk

> **Feature-rich + brand-neutral agent runtime SDK**
> **状态**：阶段 0-5 完成，阶段 6 收尾中
> **测试**：1258 passed, 1 skipped

## 概述

`agent-sdk` 是从 DeerFlow 抽离出的通用 agent runtime SDK。它提供了构建 AI agent 所需的全部基础设施——middleware 链、沙箱执行、长期记忆、多 agent 协同、Skills、MCP 集成——但**不绑定任何特定业务逻辑**。

所有业务选择（路径前缀、数据模型、工具命名、prompt 文案）通过 Protocol 注入，调用方可以用自己的实现替换。

## 安装

```bash
pip install -e /path/to/sdk-extraction/harness

# 或从 PyPI（待发布）
pip install agent-sdk
```

依赖：`langchain>=0.6`、`langgraph>=0.6`、`pydantic>=2.0`，Python 3.12+。

## 快速开始

### 最小用法（品牌中立）

```python
from agent_sdk import create_agent, RuntimeFeatures
from langchain_openai import ChatOpenAI

agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    system_prompt="You are a helpful assistant.",
    features=RuntimeFeatures(
        sandbox=True,
        memory=True,
        subagent=True,
    ),
)
result = await agent.ainvoke({"messages": [("user", "Hello")]})
```

### DeerFlow preset（参考实现）

```python
from agent_sdk.presets.deerflow import DeerFlowAgent
from langchain_openai import ChatOpenAI

agent = DeerFlowAgent(
    model=ChatOpenAI(model="gpt-4o"),
    # sandbox_provider=...,  # 注入你的沙箱后端
    # memory_storage=...,     # 注入你的存储后端
)
result = await agent.ainvoke({"messages": [("user", "Hello")]})
```

## 架构

```
agent_sdk/
├── runtime/          # create_agent() 入口、middleware 链装配、StreamBridge、checkpointer
├── sandbox/          # SandboxProvider ABC、7 个沙箱工具、审计、路径解析
├── memory/           # MemorySchema Protocol、storage、middleware、updater
├── subagents/        # SubagentRegistry Protocol、executor（线程池 + 超时 + 取消）
├── middlewares/      # 18 个 middleware（todo、loop_detection、summarization 等）
├── models/           # ModelConfig + create_chat_model 工厂
├── tools/            # 7 个 builtin tool factory（bash/ls/glob/grep/read/write/str_replace）
├── skills/           # Skills 加载器、安装器（.zip ZIP）、YAML 解析
├── mcp/              # MCP 客户端、OAuth token 管理
├── tracing/          # LangSmith / Langfuse 工厂
├── paths/            # PathProvider Protocol + VirtualPathResolver
├── reflection/       # resolve_class / resolve_variable
├── utils/            # 网络端口分配、文件转换
└── presets/
    └── deerflow/     # DeerFlow 参考实现（PathProvider、MemorySchema、AuditRules、system prompt）
```

## 核心设计原则

1. **Protocol 注入**：所有扩展点通过 Protocol 定义，调用方注入实现
2. **品牌中立**：默认 prompt、错误消息、工具描述不含任何产品名称
3. **ADR-010**：SDK 不 import `backend.*` / `deerflow.*` / `app.*`
4. **backend 不动**：抽离全程不修改 `backend/` 任何代码

## 开发

```bash
cd sdk-extraction/harness
uv sync
uv run pytest          # 1258 测试
uv run ruff check      # Lint
```

## 文档导航

- 阶段总览：`../docs/02-plan/phases.md`
- 当前进度：`../docs/03-status/progress.md`
- 决策日志：`../docs/03-status/decisions.md`
- 变更日志：`CHANGELOG.md`
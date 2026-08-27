# 阶段 4：在 SDK 内部新建 DeerFlow Preset 子包（1 周）

> 在 `sdk-extraction/harness/agent_sdk/presets/deerflow/` 内以新代码实现 DeerFlow 业务选择 preset，**不触碰 `backend/`**。

## 目标

将所有 DeerFlow 业务耦合（路径、数据模型、prompt、角色、规则）在 SDK 内部以新代码实现为 `agent_sdk.presets.deerflow` 子包，作为 SDK 的"产品预设"。

**阶段 4 完成后**：
- SDK 提供 `agent_sdk.presets.deerflow` 子包
- 任何项目（包括 DeerFlow）可一行 import 启用 DeerFlow 业务选择
- **`backend/` 完全不动**
- DeerFlow 应用切换到 preset 的迁移属于**后续应用迁移 PR**，不在本抽离范围

## 关键交付物

`sdk-extraction/harness/agent_sdk/presets/deerflow/` 子包（**SDK 内部新增，`backend/` 不动**）：

```
presets/deerflow/
├── __init__.py              # 导出 DeerFlowAgent 便利类
├── agent.py                 # DeerFlowAgent（SDK 内部便利类，**不替换** backend/client.py 的 DeerFlowClient）
├── paths.py                 # DeerFlowPathProvider
├── memory.py                # DeerFlowMemorySchema + FileMemoryStorage
├── subagents.py             # DeerFlowSubagentRegistry
├── audit.py                 # DeerFlowAuditRules
├── prompts/
│   ├── __init__.py
│   ├── system.py            # 760 行 DeerFlow system prompt（**重新录入**）
│   ├── todo.py              # TodoList prompts
│   ├── memory.py            # 事实抽取 prompts
│   ├── subagent.py          # subagent role prompts
│   └── citation.py          # 引用格式 prompts
├── tools/
│   ├── __init__.py
│   ├── clarification.py     # ask_clarification tool
│   ├── present_files.py     # present_files tool
│   ├── view_image.py        # view_image tool
│   ├── setup_agent.py       # setup_agent tool
│   ├── task.py              # task tool
│   ├── skill_manage.py      # skill_manage tool
│   └── invoke_acp.py        # invoke_acp_agent tool
├── middlewares/
│   ├── __init__.py
│   ├── thread_data.py       # ThreadDataMiddleware
│   ├── uploads.py           # UploadsMiddleware
│   ├── view_image.py        # ViewImageMiddleware
│   ├── todo.py              # TodoMiddleware (DeerFlow prompts)
│   ├── subagent_limit.py    # SubagentLimitMiddleware
│   ├── llm_error.py         # LLMErrorHandlingMiddleware
│   └── summarization.py     # SummarizationMiddleware
├── sandbox/
│   ├── __init__.py
│   ├── tools.py             # 1582 行 sandbox 工具
│   └── local.py             # LocalSandbox 实现
└── README.md                # preset 使用文档
```

**关键边界**：
- 整个 `presets/deerflow/` 子包是 SDK 内部新增，**不依赖** `backend.*` 任何模块
- `DeerFlowAgent` 是 SDK 内部便利类，**不替换** `backend/client.py` 的 `DeerFlowClient`
- DeerFlow 应用切换到 preset 的迁移属于**后续应用迁移 PR**

## 任务清单

### 4.1 创建 preset 子包结构（半天）

**任务**：建立 `agent_sdk.presets.deerflow` 目录结构和 `__init__.py`

### 4.2 收纳 DeerFlowPathProvider 到标准 preset 目录（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/paths.py`

**任务**：将阶段 1 创建的 `DeerFlowPathProvider` 收纳到 `presets/deerflow/paths.py`（如果在阶段 1 已放在此位置则保留）。如果阶段 1 放在 `agent_sdk/paths/deerflow.py`，则**移动**文件到 `presets/deerflow/paths.py`（不引用 `backend.*`）。

### 4.3 在 SDK 中实现 DeerFlowMemorySchema 和 FileMemoryStorage（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/memory.py`

**任务**：以新代码实现 `DeerFlowMemorySchema` 和 `DeerFlowFileMemoryStorage`（基于 `PathProvider` 注入），事实抽取 prompts 重新录入。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/memory/storage.py` 或 `updater.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 从 `backend/agents/memory/storage.py` 复制粘贴

**做法**：
- 读 `backend/agents/memory/storage.py` 和 `updater.py` 作为行为参考
- 在 SDK 内部**重新写** `DeerFlowMemorySchema` 和 `DeerFlowFileMemoryStorage`
- 行为与 `backend/` 原版字节级一致（golden fixture 验证）

### 4.4 在 SDK 中实现 DeerFlowSubagentRegistry（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/subagents.py`

**任务**：以新代码实现 `DeerFlowSubagentRegistry`，包含 `general-purpose` 和 `bash` 角色定义、角色 system prompts。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/subagents/builtins/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 从 `backend/subagents/builtins/` 复制粘贴角色定义

**做法**：
- 读 `backend/subagents/builtins/` 作为行为参考
- 在 SDK 内部**重新写**角色定义和 system prompts
- 行为与 `backend/` 字节级一致

### 4.5 收纳 DeerFlowAuditRules 到 preset 目录（半天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/audit.py`

**任务**：将阶段 3 创建的 `DeerFlowAuditRules` 收纳到 `presets/deerflow/audit.py`（如果在阶段 3 已放在此位置则保留）。如不在此位置则**移动**到 `presets/deerflow/audit.py`。

### 4.6 在 SDK 中实现 DeerFlow system prompts（半天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/prompts/system.py`

**任务**：以新代码重新录入 760 行 DeerFlow system prompt。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 从 `backend/agents/lead_agent/prompt.py` 复制粘贴 prompt 文本

**做法**：
- 读 `backend/agents/lead_agent/prompt.py` 作为行为参考
- 在 SDK 内部**重新录入** 760 行 prompt
- 行为与 `backend/` 字节级一致

### 4.7 在 SDK 中实现 DeerFlow builtin tools（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/tools/`

**任务**：以新代码实现 7 个 DeerFlow builtin tools：
- `clarification.py` - ask_clarification
- `present_files.py` - present_files
- `view_image.py` - view_image
- `setup_agent.py` - setup_agent
- `task.py` - task (基于 SubagentRegistry)
- `skill_manage.py` - skill_manage
- `invoke_acp.py` - invoke_acp_agent

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/tools/builtins/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 从 `backend/tools/builtins/*.py` 复制粘贴

**做法**：
- 读 `backend/tools/builtins/*.py` 作为行为参考
- 在 SDK 内部**重新写**每个 tool
- 行为与 `backend/` 字节级一致

### 4.8 在 SDK 中实现 DeerFlow middleware 业务实现（1 天）

**位置**：`sdk-extraction/harness/agent_sdk/presets/deerflow/middlewares/`

**任务**：以新代码实现 7 个 DeerFlow middleware 业务实现：
- `thread_data.py` - ThreadDataMiddleware (DeerFlow path)
- `uploads.py` - UploadsMiddleware (DeerFlow format)
- `view_image.py` - ViewImageMiddleware
- `todo.py` - TodoMiddleware (DeerFlow prompts)
- `subagent_limit.py` - SubagentLimitMiddleware
- `llm_error.py` - LLMErrorHandlingMiddleware (含 circuit breaker)
- `summarization.py` - SummarizationMiddleware (DeerFlow 业务)

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/middlewares/*` 任何文件
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 从 `backend/agents/middlewares/*` 复制粘贴

**做法**：
- 读 `backend/agents/middlewares/*` 作为行为参考
- 在 SDK 内部**重新写**每个 middleware
- 行为与 `backend/` 字节级一致

### 4.9 创建 `DeerFlowAgent` 便利类（半天）

**文件**：`presets/deerflow/agent.py`

**设计**：
```python
class DeerFlowAgent:
    """Convenience class for DeerFlow users.

    Equivalent to the original DeerFlowClient behavior.
    """

    def __init__(
        self,
        config: dict | None = None,
        features: RuntimeFeatures | None = None,
        extra_middleware: list[AgentMiddleware] | None = None,
    ):
        # 1. 加载 config
        # 2. 加载 760 行 prompt
        # 3. 加载所有 DeerFlow 业务选择
        # 4. 调用 create_agent
        self._agent = create_agent(
            model=self._load_model(),
            system_prompt=DEERFLOW_PROMPT,
            tools=self._load_tools(),
            path_provider=DeerFlowPathProvider(),
            memory_schema=DeerFlowMemorySchema(...),
            subagent_registry=DeerFlowSubagentRegistry(),
            audit_rules=DeerFlowAuditRules(),
            features=features or DEERFLOW_DEFAULT_FEATURES,
            extra_middleware=extra_middleware,
        )
```

### 4.10 写 preset 文档（半天）

**文件**：`presets/deerflow/README.md`

**内容**：
- preset 是什么
- 如何使用
- 与原 DeerFlow 行为的兼容性
- 自定义扩展方式

### 4.11 写集成测试（1 天）

**测试目标**：在 SDK 内部验证 `DeerFlowAgent` 行为与 `backend/client.py` 原版字节级一致

**测试位置**：`sdk-extraction/harness/tests/presets/deerflow/`

**绝对禁止**：
- ❌ 修改 `backend/` 来运行 DeerFlow 应用
- ❌ 测试代码 `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 测试代码引用 `backend.tests.*` 的 fixture

**测试用例**（通过 mock + 离线录制的 golden fixture 验证）：
- [ ] `DeerFlowAgent().chat("Hello")` 输出与 `backend/client.py` 原版相同格式（golden fixture 对比）
- [ ] `DeerFlowAgent().stream(...)` 流式事件与原版一致
- [ ] 工具名称与原版一致（`ask_clarification`、`present_files` 等）
- [ ] Memory 格式与原版一致（`workContext` 字段）
- [ ] Subagent 角色与原版一致（`general-purpose`、`bash`）
- [ ] 路径解析与原版一致（`/mnt/user-data`）

**Golden fixture 来源**：从 `backend/client.py` 真实输出离线录制为 JSON 字符串，存放在 `sdk-extraction/harness/tests/fixtures/presets/deerflow/`，**不引用** `backend.*` 任何模块。

### 4.12 端到端验证（1 天）

**任务**（**全部在 SDK 内部，`backend/` 不动**）：
1. 干净环境 `pip install -e sdk-extraction/harness/`
2. 运行 `sdk-extraction/harness/tests/` 全部测试
3. **可选地**只跑 `backend/tests/`（**不修改**其中任何代码）确认 DeerFlow 行为基线
4. **不修改** `backend/` 让它用 preset
5. 端到端 DeerFlow 应用切换到 preset 属于**后续应用迁移 PR**，不在本抽离范围

**成功标准**：
- SDK 内部集成测试 100% 通过
- 所有 golden fixture 字节级匹配
- `backend/tests/` 基线回归通过（仅跑，不修改）

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| 重新实现过程中遗漏 DeerFlow 业务逻辑 | 高 | 详细对比；逐个文件重新实现；集成测试 + golden fixture 覆盖 |
| 路径解析与原版不一致 | 中 | 字节级对比；保留所有边缘情况 |
| Prompt 文案差异 | 中 | 重新录入；golden fixture 测试覆盖 |
| DeerFlowAgent API 与 DeerFlowClient 不完全兼容 | 中 | SDK 内部 `DeerFlowAgent` 是新建 API，不要求与 `DeerFlowClient` 字面相同；记录 breaking changes |

## 依赖

- 阶段 1-3 全部完成

## 产出（**全部在 SDK 内部，`backend/` 不动**）

- `sdk-extraction/harness/agent_sdk/presets/deerflow/` 完整子包
- `sdk-extraction/harness/tests/presets/deerflow/` 集成测试
- `sdk-extraction/harness/tests/fixtures/presets/deerflow/` golden fixture（离线录制，不引用 `backend.*`）
- `sdk-extraction/harness/agent_sdk/presets/deerflow/README.md`

## 完成标准

- [ ] 4.1-4.12 全部完成
- [ ] SDK 内部集成测试 100% 通过
- [ ] 所有 golden fixture 字节级匹配
- [ ] `backend/tests/` 基线回归通过（仅跑，不修改）
- [ ] 文档完整
- [ ] **`backend/` 全程未触碰**

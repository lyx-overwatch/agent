# DeerFlow Harness 业务耦合度分析

> **目标**：评估 `deerflow-harness` 包与 DeerFlow 业务代码的耦合程度，定位哪些模块"不可抽离"、哪些是"运行时"、哪些是"业务实现"，并给出抽离为通用 Python 组件的路径。
>
> **核心问题**：`deerflow` 包能否独立于 DeerFlow 应用代码，作为通用 agent 运行环境被任意 Python 项目使用？

---

## 一、目标架构

我们要的是这样一个组件：

```python
# 任何 Python 项目都可以这么用
from deerflow import create_agent
from langchain_openai import ChatOpenAI

agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    system_prompt="You are a helpful assistant.",
    tools=[my_tool_1, my_tool_2],
)

result = agent.invoke({"messages": [("user", "Hello")]})
```

**关键约束**：

- 任何参数、对象、行为都**可注入**，没有隐式全局状态
- 没有任何 `/mnt/user-data/...`、`agent_name`、`ask_clarification` 这类 DeerFlow 特有概念
- 可以独立 `pip install` 并被嵌入到任何 Python 项目
- **不带 config.yaml、不带 skills 目录、不带 extensions_config.json**

---

## 二、5 个业务耦合层面

代码里散落着 5 个不同层次的业务耦合，必须逐层剥离开。

### 2.1 概念层耦合：DeerFlow 特有命名

`agents/lead_agent/prompt.py` 的 760 行 prompt 模板里**全是 DeerFlow 业务**：

```python
SYSTEM_PROMPT_TEMPLATE = """
<role>
You are {agent_name}, an open-source super agent.   # ← "super agent" 是 DeerFlow 品牌
</role>
...
**Example 1: "Why is Tencent's stock price declining?"**  # ← 业务示例
**Example 2: "Compare 5 cloud providers"**               # ← README 示例
**Example 3: "Refactor the authentication system"**       # ← 业务示例
...
<working_directory existed="true">
- User uploads: `/mnt/user-data/uploads`                 # ← 硬编码虚拟路径
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
</working_directory>
...
**Citation format**: `[citation:TITLE](URL)`              # ← DeerFlow 特有引用格式
...
- Skill First: Always load the relevant skill before starting **complex** tasks.
- Output Files: Final deliverables must be in `/mnt/user-data/outputs`  # ← 业务约束
- Including Images and Mermaid: ...                                       # ← 业务偏好
...
"""
```

还有 `TodoMiddleware` 的 system_prompt：

```python
# agents/lead_agent/agent.py
system_prompt = """
<todo_list_system>
You have access to the `write_todos` tool ...   # ← DeerFlow 业务描述
**Best Practices:** ...
"""
```

**耦合度**：⭐⭐⭐⭐⭐ **完全业务**

**抽离方法**：把 `apply_prompt_template` 改为 **接受 `system_prompt: str | None` 参数**。SDK 不应有任何默认 prompt；它应该透传用户的 prompt，或提供一个最简的 fallback。

### 2.2 状态层耦合：`ThreadState` 强假设

`agents/thread_state.py` 的所有字段都假设 DeerFlow 业务场景：

```python
class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]              # ← 假设有沙箱
    thread_data: NotRequired[ThreadDataState | None]        # ← 假设有 thread 隔离
    title: NotRequired[str | None]                         # ← "标题生成"业务
    artifacts: Annotated[list[str], merge_artifacts]        # ← "artifacts"业务概念
    todos: NotRequired[list | None]                        # ← 假设有 TodoList
    uploaded_files: NotRequired[list[dict] | None]         # ← "上传文件"业务
    viewed_images: Annotated[dict[str, ViewedImageData], ...]  # ← "view_image"业务
```

**耦合度**：⭐⭐⭐⭐ **强业务**

**抽离方法**：
- `ThreadState` 应该是 SDK 的**默认 state schema**（`AgentState` + `messages`），不预设任何 DeerFlow 字段
- DeerFlow 业务字段（artifacts / uploaded_files / viewed_images）应该**通过中间件注入**到扩展 schema
- `merge_artifacts`、`merge_viewed_images` 这种 reducer 应该是 middleware 的一部分，不是 state 的一部分

### 2.3 路径层耦合：`/mnt/user-data` 硬编码

`config/paths.py:7` 写死：

```python
VIRTUAL_PATH_PREFIX = "/mnt/user-data"
```

`Paths` 类（`config/paths.py:61`）把目录布局完全硬编码：

```python
class Paths:
    """
    Directory layout (host side):
        {base_dir}/
        ├── memory.json                    # ← DeerFlow 特有的 memory.json
        ├── USER.md                        # ← 全局 user profile（业务）
        ├── agents/
        │   └── {agent_name}/              # ← DeerFlow 特有的 agent 概念
        │       ├── config.yaml
        │       ├── SOUL.md                # ← "人格"业务
        │       └── memory.json
        └── threads/
            └── {thread_id}/
                └── user-data/             # ← 硬编码
                    ├── workspace/
                    ├── uploads/           # ← 业务
                    └── outputs/           # ← 业务
    """
```

被侵入的地方：

- `sandbox/tools.py:37`: `_DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"`
- `sandbox/tools.py:38`: `_ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"`
- `sandbox/tools.py:1229`: 硬编码 `/mnt/user-data/workspace/.venv`
- `agents/middlewares/uploads_middleware.py`：扫 `/mnt/user-data/uploads`
- `agents/middlewares/thread_data_middleware.py`：创建 `/mnt/user-data/...`
- `tools/builtins/present_file_tool.py:14`: `OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"`
- `tools/builtins/view_image_tool.py:14-18`: 三个允许的虚拟根
- `uploads/manager.py`：所有上传路径逻辑
- `tools/builtins/invoke_acp_agent_tool.py:35-50`：`{base_dir}/threads/{thread_id}/acp-workspace/`

**耦合度**：⭐⭐⭐⭐⭐ **完全硬编码**

**抽离方法**：
- 抽象 `PathProvider` Protocol：`get_sandbox_root() / get_uploads_dir(thread_id) / get_outputs_dir(thread_id) / get_workspace_dir(thread_id)`
- 路径前缀应该作为参数注入或可配置
- `Paths` 类应该提供默认实现，**但不强制使用** `/mnt/user-data`

### 2.4 中间件层耦合：14 个 middleware 多数是业务

`_build_middlewares`（`agents/lead_agent/agent.py:244`）组装了 14 个 middleware，但**绝大多数是 DeerFlow 业务**：

| Middleware | 业务耦合度 | 备注 |
|------------|------------|------|
| `ThreadDataMiddleware` | ⭐⭐⭐⭐⭐ | 创建 `/mnt/user-data/...`，强 DeerFlow 业务 |
| `UploadsMiddleware` | ⭐⭐⭐⭐⭐ | 读 `<uploaded_files>`，是 DeerFlow 文件上传业务 |
| `SandboxMiddleware` | ⭐⭐⭐⭐ | 与 `SandboxProvider` 强绑定，可以抽象但目前 hardcode 沙箱 |
| `DanglingToolCallMiddleware` | ⭐ | **完全通用**，可保留 |
| `LLMErrorHandlingMiddleware` | ⭐⭐ | 含 circuit breaker（DeerFlow 业务），但异常重试是通用模式 |
| `GuardrailMiddleware` | ⭐⭐⭐ | OAP 协议通用，但当前实现只有白名单 |
| `SandboxAuditMiddleware` | ⭐⭐⭐⭐⭐ | 含 DeerFlow 特有的 bash 审计规则（高危命令、dd、mkfs...） |
| `ToolErrorHandlingMiddleware` | ⭐ | **完全通用**（`agent.py:19-50`） |
| `SummarizationMiddleware` | ⭐⭐ | 摘要本身通用，但需要 `skills_container_path` DeerFlow 业务 |
| `TodoMiddleware` | ⭐⭐⭐⭐ | `write_todos` 工具 + DeerFlow 业务 prompt |
| `TokenUsageMiddleware` | ⭐ | **完全通用**（按 token 计费） |
| `TitleMiddleware` | ⭐⭐⭐⭐⭐ | "生成对话标题"完全是 DeerFlow 业务 |
| `MemoryMiddleware` | ⭐⭐⭐⭐⭐ | `memory.json` + LLM 抽取事实，完全 DeerFlow 业务 |
| `ViewImageMiddleware` | ⭐⭐⭐⭐ | `view_image` 工具 + image base64 注入，业务 |
| `DeferredToolFilterMiddleware` | ⭐ | **完全通用**（Claude Code 风格延迟工具发现） |
| `SubagentLimitMiddleware` | ⭐⭐⭐ | 与 `subagent_type` 业务概念绑定 |
| `LoopDetectionMiddleware` | ⭐ | **完全通用**（哈希滑动窗口） |
| `ClarificationMiddleware` | ⭐⭐⭐⭐⭐ | `ask_clarification` 工具 + 5 种 clarification_type，业务 |

**统计**：
- **完全通用**（可保留在 SDK）：5 个 —— `DanglingToolCall`、`ToolErrorHandling`、`TokenUsage`、`DeferredToolFilter`、`LoopDetection`
- **业务耦合**：13 个

**抽离方法**：
- SDK 默认**不提供**任何业务 middleware
- SDK 提供一个**注册中心**让用户通过 `features=RuntimeFeatures(...)` 启用业务 middleware
- 业务 middleware 应全部移到 `deerflow/presets/deerflow/` 子包

### 2.5 工具层耦合：sandbox/tools.py 1582 行

`Sandbox` 的 7 个工具（`bash` / `ls` / `read_file` / `write_file` / `str_replace` / `glob` / `grep`）都是 LangChain `@tool` 装饰器，**但**：

```python
# sandbox/tools.py:1223
@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """Execute a bash command in a Linux environment.

    - Use `python` to run Python code.
    - Prefer a thread-local virtual environment in `/mnt/user-data/workspace/.venv`.  # ← 硬编码
    - Use `python -m pip` (inside the virtual environment) to install Python packages.
    ...
    """
    if is_local_sandbox(runtime):
        if not is_host_bash_allowed():
            return f"Error: {LOCAL_HOST_BASH_DISABLED_MESSAGE}"   # ← DeerFlow 安全策略
        ...
        thread_data = get_thread_data(runtime)                    # ← 强 DeerFlow 业务
        validate_local_bash_command_paths(command, thread_data)
        command = replace_virtual_paths_in_command(command, thread_data)  # ← 虚拟路径业务
```

1582 行里**90% 是路径处理 / 业务校验**：
- `mask_local_paths_in_output` —— 把 host 路径 mask 成虚拟路径（业务）
- `validate_local_bash_command_paths` —— 白名单路径（业务）
- `replace_virtual_paths_in_command` —— 路径翻译（业务）
- `validate_local_tool_path` —— 路径校验（业务）
- `_LOCAL_BASH_SYSTEM_PATH_PREFIXES`（`tools.py:28`）—— 黑名单系统命令（业务）
- `_LOCAL_BASH_CWD_COMMANDS`、`_LOCAL_BASH_COMMAND_WRAPPERS` —— 业务规则

**耦合度**：⭐⭐⭐⭐⭐ **完全业务**

**抽离方法**：
- 沙箱本身（`Sandbox` / `SandboxProvider` ABC）是 SDK 抽象
- 但默认工具实现**不应在 SDK 里**，应由 `community/aio_sandbox` 等可选包提供
- SDK 只提供接口和最少 1 个"最小可用"实现（如 `LocalSandbox` + `bash` 工具），无任何路径翻译

### 2.6 Subagent 耦合

`subagents/builtins/` 定义了 `general-purpose` 和 `bash` 两个内置 subagent，**完全是 DeerFlow 业务**。

`SubagentExecutor`（676 行）也是业务实现：
- `_background_tasks` 全局单例
- 三个 ThreadPoolExecutor（`_scheduler_pool` / `_execution_pool` / `_isolated_loop_pool`）
- trace_id 关联是 DeerFlow 业务

`tools/builtins/task_tool.py`（12.7 KB）有大量 subagent 业务：
- "general-purpose"、"bash" 业务角色
- `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE` 安全策略
- `max_turns` 业务参数

**耦合度**：⭐⭐⭐⭐ **强业务**

**抽离方法**：
- `SubagentConfig` 数据类可以保留为 SDK 抽象
- `SubagentExecutor` 应该支持**用户自定义实现**或通过 Plugin 注入
- `subagents/builtins/` 移到 `deerflow/presets/deerflow/`

### 2.7 客户端门面层耦合

`client.py`（1202 行）—— **完全是 DeerFlow 应用门面**：

```python
# client.py:1
"""DeerFlowClient — Embedded Python client for DeerFlow agent system.

Provides direct programmatic access to DeerFlow's agent capabilities
without requiring LangGraph Server or Gateway API processes.
"""
```

```python
# client.py:35-54
from deerflow.agents.lead_agent.agent import _build_middlewares        # ← 私有函数跨层
from deerflow.agents.lead_agent.prompt import apply_prompt_template    # ← 业务 prompt
from deerflow.config.agents_config import AGENT_NAME_PATTERN           # ← 业务
from deerflow.config.extensions_config import ...                       # ← extensions
from deerflow.skills.installer import install_skill_from_archive       # ← skills 业务
from deerflow.uploads.manager import (                                 # ← 上传业务
    claim_unique_filename,
    delete_file_safe,
    ...
)
```

**耦合度**：⭐⭐⭐⭐⭐ **完全业务**

**抽离方法**：`client.py` 应**保留在应用层**（如 `app/client.py` 或 `deerflow.app.client`），不应进入 SDK。

---

## 三、模块级耦合矩阵

| 模块 | 通用度 | 业务度 | 抽离建议 |
|------|--------|--------|----------|
| `agents/factory.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**，但 `RuntimeFeatures` 默认值改为 `False`（不预装业务 middleware） |
| `agents/features.py` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（`@Next` / `@Prev` / `RuntimeFeatures` 是纯抽象） |
| `agents/thread_state.py` | ⭐⭐ | ⭐⭐⭐ | **拆**：基础 `AgentState` 抽到 SDK，业务字段移到 `presets/deerflow/` |
| `agents/lead_agent/agent.py` | ⭐ | ⭐⭐⭐⭐⭐ | **不抽**，留应用层 |
| `agents/lead_agent/prompt.py` | ⭐ | ⭐⭐⭐⭐⭐ | **不抽** |
| `agents/memory/*` | ⭐ | ⭐⭐⭐⭐⭐ | **不抽**，全在 `presets/deerflow/memory/` |
| `agents/middlewares/clarification_middleware.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/title_middleware.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/memory_middleware.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/view_image_middleware.py` | ⭐ | ⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/uploads_middleware.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/thread_data_middleware.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/todo_middleware.py` | ⭐ | ⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/sandbox_audit_middleware.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/middlewares/` |
| `agents/middlewares/summarization_middleware.py` | ⭐⭐ | ⭐⭐⭐ | 业务（要 skills_container_path） |
| `agents/middlewares/subagent_limit_middleware.py` | ⭐⭐ | ⭐⭐⭐ | 业务（subagent_type 业务） |
| `agents/middlewares/loop_detection_middleware.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（完全通用模式） |
| `agents/middlewares/dangling_tool_call_middleware.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（完全通用） |
| `agents/middlewares/tool_error_handling_middleware.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（完全通用） |
| `agents/middlewares/llm_error_handling_middleware.py` | ⭐⭐ | ⭐⭐⭐ | 部分业务（circuit breaker），主体可抽 |
| `agents/middlewares/token_usage_middleware.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `agents/middlewares/deferred_tool_filter_middleware.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（Claude Code 风格通用） |
| `config/app_config.py` | ⭐⭐⭐ | ⭐⭐ | **抽到 SDK**，但应该是**可选**（用户也可不传 config） |
| `config/paths.py` | ⭐ | ⭐⭐⭐⭐⭐ | **拆**：`PathProvider` Protocol 抽到 SDK；`Paths` 类移到 `presets/deerflow/` |
| `config/extensions_config.py` | ⭐⭐⭐ | ⭐⭐ | **抽到 SDK**（MCP 是通用协议） |
| `config/model_config.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `config/tool_config.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `config/agents_config.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到应用层 |
| `config/acp_config.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到应用层 |
| `guardrails/*` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（完全通用） |
| `mcp/*` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（MCP 是通用协议） |
| `models/factory.py` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（完全通用的反射工厂） |
| `models/credential_loader.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/` |
| `models/*_provider.py` | ⭐⭐⭐⭐ | ⭐ | 抽到独立子包（按 provider） |
| `models/patched_*.py` | ⭐⭐⭐⭐ | ⭐ | 抽到独立子包 |
| `persistence/*` | ⭐⭐ | ⭐⭐⭐ | **拆**：ABC 抽到 SDK；SQL 实现留应用层 |
| `reflection/*` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `runtime/serialization.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `runtime/stream_bridge/*` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `runtime/user_context.py` | ⭐⭐⭐ | ⭐⭐ | **抽到 SDK**（提供 `UserContext` Protocol，业务实现 `ContextUserContext` 留应用层） |
| `runtime/runs/*` | ⭐⭐ | ⭐⭐⭐ | **拆**：StreamBridge 接口抽；`run_agent` 是 LangGraph 平台兼容层，留应用层 |
| `runtime/checkpointer/*` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（LangGraph 标准抽象） |
| `runtime/store/*` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `sandbox/sandbox.py` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（纯 ABC） |
| `sandbox/sandbox_provider.py` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（纯 ABC） |
| `sandbox/search.py` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（glob/grep 算法） |
| `sandbox/tools.py` | ⭐ | ⭐⭐⭐⭐⭐ | **不抽**，留 `presets/deerflow/sandbox/` |
| `sandbox/local/*` | ⭐ | ⭐⭐⭐⭐ | **不抽**（仅 trusted 模式） |
| `sandbox/middleware.py` | ⭐⭐⭐ | ⭐⭐ | **抽到 SDK**（抽象 `SandboxMiddleware`） |
| `skills/{types,parser,loader,validation,installer}.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（SKILL.md 是 DeerFlow 发明的协议） |
| `skills/manager.py` | ⭐⭐ | ⭐⭐⭐ | 业务管理 API，留应用层 |
| `skills/security_scanner.py` | ⭐ | ⭐⭐⭐⭐ | 业务，留应用层 |
| `subagents/{config,registry}.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（抽象 subagent 概念） |
| `subagents/executor.py` | ⭐ | ⭐⭐⭐⭐ | **不抽**，留 `presets/deerflow/subagents/` |
| `subagents/builtins/*` | ⭐ | ⭐⭐⭐⭐⭐ | **不抽** |
| `tools/builtins/clarification_tool.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/tools/` |
| `tools/builtins/present_file_tool.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务（虚拟路径），移到 `presets/deerflow/tools/` |
| `tools/builtins/view_image_tool.py` | ⭐ | ⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/tools/` |
| `tools/builtins/setup_agent_tool.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/tools/` |
| `tools/builtins/task_tool.py` | ⭐ | ⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/tools/` |
| `tools/builtins/invoke_acp_agent_tool.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/tools/` |
| `tools/builtins/tool_search.py` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK**（Claude Code 风格通用） |
| `tools/tools.py` | ⭐⭐⭐ | ⭐⭐ | **拆**：装配逻辑抽到 SDK；DeerFlow 业务工具注册表留应用层 |
| `tools/skill_manage_tool.py` | ⭐ | ⭐⭐⭐⭐ | 业务，移到 `presets/deerflow/tools/` |
| `tracing/*` | ⭐⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `uploads/manager.py` | ⭐ | ⭐⭐⭐⭐⭐ | 业务，移到应用层 |
| `utils/*` | ⭐⭐⭐⭐ | ⭐ | **抽到 SDK** |
| `community/*` | ⭐⭐⭐⭐ | ⭐ | 抽到独立子包 |
| `client.py` | ⭐ | ⭐⭐⭐⭐⭐ | **不抽**，留应用层 |

---

## 四、抽离后的目标目录结构

```
deerflow-harness/                            # 通用 SDK（重命名/抽离后）
├── runtime/                                 # ⭐ 通用 agent 运行时
│   ├── agent.py                             # create_agent() 纯参数入口
│   ├── features.py                          # RuntimeFeatures + @Next/@Prev
│   ├── state.py                             # 基础 AgentState（不预设业务字段）
│   ├── stream_bridge.py                     # 生产者-消费者解耦
│   ├── serialization.py                     # LC 对象序列化
│   ├── user_context.py                      # ContextVar + UserContext Protocol
│   ├── checkpointer/                        # LangGraph 集成
│   ├── store/                               # LangGraph 集成
│   └── middlewares/                         # ⭐ 通用 middleware
│       ├── dangling_tool_call.py
│       ├── loop_detection.py
│       ├── tool_error_handling.py
│       ├── token_usage.py
│       └── deferred_tool_filter.py
│
├── sandbox/                                 # ⭐ 通用沙箱抽象
│   ├── base.py                              # Sandbox ABC
│   ├── provider.py                          # SandboxProvider ABC
│   ├── search.py                            # glob/grep
│   └── middleware.py                        # 抽象 SandboxMiddleware
│
├── paths/                                   # ⭐ 通用路径抽象
│   ├── provider.py                          # PathProvider Protocol
│   └── resolver.py                          # 虚拟路径解析
│
├── config/                                  # ⭐ 通用配置
│   ├── schema.py                            # AgentConfig / ModelConfig / ToolConfig
│   ├── loader.py                            # YAML 加载（可选）
│   └── extensions.py                        # MCP 扩展配置
│
├── models/                                  # ⭐ 通用模型
│   ├── factory.py                           # create_chat_model 反射工厂
│   └── providers/                           # OpenAI/Anthropic/...
│
├── tools/                                   # ⭐ 通用工具装配
│   ├── registry.py                          # ToolRegistry Protocol
│   ├── deferred.py                          # DeferredToolRegistry
│   └── loader.py                            # 反射加载工具
│
├── skills/                                  # ⭐ SKILL.md 协议
│   ├── types.py
│   ├── parser.py
│   ├── loader.py
│   ├── validation.py
│   └── installer.py
│
├── subagents/                               # ⭐ 通用 subagent 概念
│   ├── config.py                            # SubagentConfig 数据类
│   └── registry.py                          # 注册表（不含执行器）
│
├── mcp/                                     # ⭐ MCP 集成
│   ├── client.py
│   ├── cache.py
│   ├── oauth.py
│   └── tools.py
│
├── guardrails/                              # ⭐ OAP 协议
│   ├── provider.py
│   ├── middleware.py
│   └── builtin.py
│
├── tracing/                                 # ⭐ 通用追踪
│   └── factory.py
│
├── reflection/                              # ⭐ 反射工具
│   └── resolvers.py
│
└── utils/                                   # ⭐ 通用工具
    ├── file_conversion.py
    ├── network.py
    └── readability.py

deerflow-app/                                # ⭐ DeerFlow 应用层（留在 app/）
├── agents/
│   ├── lead_agent/
│   │   ├── agent.py                         # make_lead_agent (YAML 驱动)
│   │   └── prompt.py                        # 760 行 DeerFlow prompt
│   ├── memory/                              # memory.json + LLM 抽取
│   └── middlewares/                         # 14 个 DeerFlow 业务 middleware
│       ├── thread_data.py
│       ├── uploads.py
│       ├── sandbox_audit.py
│       ├── clarification.py
│       ├── title.py
│       ├── memory.py
│       ├── view_image.py
│       ├── todo.py
│       ├── subagent_limit.py
│       └── llm_error_handling.py
├── sandbox/
│   ├── tools.py                             # 1582 行 DeerFlow 沙箱工具
│   ├── local/                               # 本地沙箱
│   └── audit_rules.py                       # bash 黑名单
├── subagents/
│   ├── executor.py                          # 676 行 executor
│   └── builtins/                            # general-purpose, bash
├── tools/
│   ├── builtins/                            # clarification, present_files, view_image, ...
│   ├── skill_manage.py
│   └── registry.py                          # DeerFlow 工具注册表
├── skills/
│   ├── manager.py
│   └── security_scanner.py
├── uploads/manager.py                       # 文件上传业务
├── persistence/                             # SQLAlchemy ORM
│   ├── engine.py
│   ├── models/
│   └── ...
├── paths/
│   └── deerflow_paths.py                    # Paths 类（实现 PathProvider）
├── config/
│   ├── agents.py
│   ├── acp.py
│   └── ...
├── client.py                                # DeerFlowClient 应用门面
├── community/                               # 第三方集成
└── presets/
    └── deerflow/                            # DeerFlow 业务 preset
        ├── features.py                      # 默认 RuntimeFeatures（启用所有业务 middleware）
        ├── prompt.py                        # 默认 system_prompt
        └── state.py                         # 扩展 ThreadState
```

---

## 五、抽离的 4 个关键问题

### Q1：`create_deerflow_agent` 默认应该装哪些 middleware？

**当前**（`agents/factory.py:155-280`）默认装 14 个 middleware。

**抽离后**：默认应该**只装完全通用的 5 个**：

```python
# SDK 默认
DEFAULT_CHAIN = [
    DanglingToolCallMiddleware(),         # 通用
    ToolErrorHandlingMiddleware(),        # 通用
    TokenUsageMiddleware(),               # 通用
    LoopDetectionMiddleware(),            # 通用
]
```

**业务 middleware 通过 `RuntimeFeatures` 显式启用**：

```python
# DeerFlow 用户的标准用法
from deerflow.presets.deerflow import DEERFLOW_FEATURES
from deerflow.presets.deerflow.prompt import DEFAULT_PROMPT

agent = create_agent(
    model=model,
    system_prompt=DEFAULT_PROMPT,  # DeerFlow 760 行 prompt
    features=DEERFLOW_FEATURES,    # 启用所有 DeerFlow 业务 middleware
)

# 其他项目的用法
agent = create_agent(
    model=model,
    system_prompt="You are a helpful assistant.",  # 用户自己写
    # features 不传 → 0 业务 middleware
)
```

### Q2：`ThreadState` 默认应该有哪些字段？

**当前**预设了 7 个业务字段（`sandbox` / `thread_data` / `title` / `artifacts` / `todos` / `uploaded_files` / `viewed_images`）。

**抽离后**：

```python
# deerflow.runtime.state
class BaseState(AgentState):
    """SDK default state — only LangChain standard fields."""
    # 没有任何业务字段
    pass

# deerflow.presets.deerflow.state
class DeerFlowState(BaseState):
    """DeerFlow business extension — uses middleware-injected fields."""
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], ...]
    todos: NotRequired[list | None]
    # sandbox / thread_data 通过 SandboxMiddleware 注入
```

这样**业务字段是 middlewares 的扩展点**，而不是 state 的预设。

### Q3：`/mnt/user-data` 怎么从 SDK 里消失？

**当前**：所有路径硬编码 `/mnt/user-data`。

**抽离后**：抽象 `PathProvider` Protocol：

```python
# deerflow.paths.provider
class PathProvider(Protocol):
    """Provides filesystem path resolution for a runtime."""
    def get_workspace_dir(self, thread_id: str) -> Path: ...
    def get_uploads_dir(self, thread_id: str) -> Path: ...
    def get_outputs_dir(self, thread_id: str) -> Path: ...
    def get_skills_dir(self) -> Path: ...
    def get_base_dir(self) -> Path: ...

# deerflow.paths.resolver
class VirtualPathResolver:
    """Translates between virtual paths (e.g. /mnt/user-data/...) and physical paths."""
    def __init__(self, path_provider: PathProvider, prefix: str = "/mnt/user-data"):
        ...
    def virtualize(self, physical: Path) -> str: ...
    def resolve(self, virtual: str) -> Path: ...

# deerflow.presets.deerflow.paths  (实现)
class DeerFlowPathProvider:
    """Default implementation: {base_dir}/threads/{thread_id}/user-data/..."""
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def get_workspace_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id / "user-data" / "workspace"
    ...
```

这样**默认是 `/mnt/user-data`，但用户可注入任意前缀**。

### Q4：业务 middleware 怎么从 SDK 剥离开？

**当前**：14 个 middleware 全在 `agents/middlewares/` 下，`create_deerflow_agent` 默认装。

**抽离后**：

```python
# deerflow.runtime.middlewares — SDK 自带的 5 个通用 middleware
from deerflow.runtime.middlewares import (
    DanglingToolCallMiddleware,
    ToolErrorHandlingMiddleware,
    TokenUsageMiddleware,
    LoopDetectionMiddleware,
    DeferredToolFilterMiddleware,
)

# deerflow.presets.deerflow.middlewares — DeerFlow 业务 middleware
from deerflow.presets.deerflow.middlewares import (
    ThreadDataMiddleware,
    UploadsMiddleware,
    SandboxAuditMiddleware,
    ClarificationMiddleware,
    TitleMiddleware,
    MemoryMiddleware,
    ViewImageMiddleware,
    TodoMiddleware,
    SubagentLimitMiddleware,
    LLMErrorHandlingMiddleware,
    SummarizationMiddleware,
    SandboxMiddleware,
)

# deerflow.presets.deerflow.features
DEERFLOW_FEATURES = RuntimeFeatures(
    sandbox=True,            # ThreadData + Uploads + Sandbox middleware
    memory=True,             # MemoryMiddleware
    summarization=False,     # 用户配置
    subagent=True,           # SubagentLimit + 提供 SUBAGENT_TOOLS
    vision=True,             # ViewImageMiddleware
    auto_title=True,         # TitleMiddleware
    guardrail=False,
)
```

`RuntimeFeatures` 保持原样，但**默认值改为 `False`**（不预装业务）：

```python
@dataclass
class RuntimeFeatures:
    sandbox: bool | AgentMiddleware = False           # ← 改 False
    memory: bool | AgentMiddleware = False             # ← 已经是 False
    summarization: Literal[False] | AgentMiddleware = False
    subagent: bool | AgentMiddleware = False           # ← 改 False
    vision: bool | AgentMiddleware = False             # ← 改 False
    auto_title: bool | AgentMiddleware = False         # ← 改 False
    guardrail: Literal[False] | AgentMiddleware = False
```

---

## 六、抽离步骤（4 阶段）

### 阶段 1：纯通用辅助包（无 DeerFlow 业务，1 周）

- 抽 `reflection/` → 独立包
- 抽 `tracing/` → 独立包
- 抽 `utils/` → 独立包
- 抽 `runtime/stream_bridge/` → SDK 内部
- **风险**：极低。这些模块已经是无业务依赖的。

### 阶段 2：路径抽象（核心解耦，2 周）

**关键工作**：

1. 创建 `deerflow.paths.provider.PathProvider` Protocol
2. 创建 `deerflow.paths.resolver.VirtualPathResolver`（接受 `PathProvider`）
3. 把 `config/paths.py` 的 `Paths` 类移到 `deerflow.presets.deerflow.paths.DeerFlowPathProvider`
4. 修改所有引用 `VIRTUAL_PATH_PREFIX` 的地方 → 通过 `PathProvider.virtualize()` / `resolve()` 调用
5. 抽出 `PathProvider` 默认实现，提供无 `/mnt/user-data` 假设的版本

**风险**：中。涉及 `sandbox/tools.py`、`uploads/manager.py`、6+ 个 middleware 的路径调用。

### 阶段 3：Middleware 拆分（3 周）

**关键工作**：

1. 把 SDK 通用 middleware（`DanglingToolCall`、`ToolErrorHandling`、`TokenUsage`、`LoopDetection`、`DeferredToolFilter`）保留在 `deerflow.runtime.middlewares`
2. 把 13 个业务 middleware 移到 `deerflow.presets.deerflow.middlewares`
3. 修改 `agents/factory.py::RuntimeFeatures` 默认值（`sandbox`/`subagent`/`vision`/`auto_title` 改 `False`）
4. 创建 `deerflow.presets.deerflow.features.DEERFLOW_FEATURES` 提供 DeerFlow 默认配置
5. `ThreadState` 拆分：`BaseState` + `DeerFlowState`（业务字段在 preset 里）

**风险**：高。要保持现有 DeerFlow 行为完全不变。

### 阶段 4：Subagent + Tools + Sandbox 业务实现剥离（3 周）

**关键工作**：

1. `subagents/builtins/` → `deerflow.presets.deerflow.subagents.builtins`
2. `subagents/executor.py` → 拆：抽象 `SubagentExecutorBase` 留 SDK，业务实现移到 preset
3. `tools/builtins/*` → `deerflow.presets.deerflow.tools.builtins`（除 `tool_search.py`）
4. `sandbox/tools.py` 1582 行 → 拆：抽象工具接口留 SDK，业务工具移到 preset
5. `sandbox/local/*` → `deerflow.presets.deerflow.sandbox.local`
6. `client.py` → 移到 `app/client.py`（DeerFlow 应用门面）

**风险**：高。涉及大量文件移动和 import 路径修改。

---

## 七、抽离后如何验证

**单元测试**：

```python
# test_sdk_standalone.py
def test_sdk_no_business_coupling():
    """SDK 可以在不读 config.yaml 的情况下创建 agent。"""
    from deerflow import create_agent
    from langchain_openai import ChatOpenAI

    agent = create_agent(
        model=ChatOpenAI(model="gpt-4o"),
        system_prompt="You are a helpful assistant.",
    )
    assert agent is not None

def test_sdk_no_deerflow_paths():
    """SDK 不应硬编码 /mnt/user-data。"""
    from deerflow.paths import get_default_path_provider
    provider = get_default_path_provider()
    # 默认应该是 NoOpPathProvider 或空 PathProvider
    assert not any("/mnt/user-data" in str(p) for p in [
        provider.get_workspace_dir("test"),
        provider.get_uploads_dir("test"),
    ])

def test_sdk_no_business_middleware():
    """SDK 不应预装业务 middleware。"""
    from deerflow import create_agent
    from langchain_openai import ChatOpenAI
    from langchain.agents.middleware import AgentMiddleware

    agent = create_agent(
        model=ChatOpenAI(model="gpt-4o"),
        system_prompt="test",
    )
    # 默认 chain 应该只有 5 个通用 middleware
    assert len(agent.middleware) <= 5
```

**集成测试**：

```python
# test_deerflow_app_uses_sdk.py
def test_deerflow_app_uses_sdk_with_preset():
    """DeerFlow 应用通过 preset 启用业务 middleware。"""
    from deerflow.presets.deerflow import DEERFLOW_FEATURES, DEFAULT_PROMPT
    from deerflow import create_agent
    from langchain_openai import ChatOpenAI

    agent = create_agent(
        model=ChatOpenAI(model="gpt-4o"),
        system_prompt=DEFAULT_PROMPT,
        features=DEERFLOW_FEATURES,
    )
    # 业务 middleware 全部装上
    assert any("Title" in type(m).__name__ for m in agent.middleware)
    assert any("Memory" in type(m).__name__ for m in agent.middleware)
    assert any("Clarification" in type(m).__name__ for m in agent.middleware)
```

---

## 八、最终建议

### 8.1 立即可做的（无破坏性）

1. **创建 `deerflow.presets.deerflow` 子包**（不动现有代码）
   - 在 `agents/` 下创建 `presets/deerflow/` 空目录
   - 把 `agents/lead_agent/agent.py` 移到 `presets/deerflow/agent.py`
   - 把 `agents/lead_agent/prompt.py` 移到 `presets/deerflow/prompt.py`
   - 旧 import path 留 `__init__.py` 兼容 shim
   - **零业务风险**，只是物理位置调整

2. **抽 `reflection/` `tracing/` `utils/` 到独立子包**（1 周）
   - 与 DeerFlow 应用零耦合
   - 立刻可做

### 8.2 关键解耦（1-2 月）

3. **路径抽象**：引入 `PathProvider` Protocol，把 `Paths` 移出 SDK
   - 一旦完成，所有 `/mnt/user-data` 引用都可解耦
   - 这是**最难也最有价值**的一步

4. **Middleware 拆分**：13 个业务 middleware 移到 `presets/deerflow/middlewares/`
   - 改 `RuntimeFeatures` 默认值为 `False`
   - 提供 `DEERFLOW_FEATURES` preset

5. **ThreadState 拆分**：`BaseState` + `DeerFlowState`
   - 业务字段通过 middleware 注入

### 8.3 完全剥离（3+ 月）

6. **Subagent / Tools / Sandbox 业务实现剥离**
7. **`client.py` 移到应用层**
8. **持久化（persistence/）拆：ABC 抽到 SDK，SQL 留应用层**

### 8.4 不建议做的

- **`sandbox/tools.py` 1582 行** 不要原样抽到独立子包，应**整体移到 `presets/deerflow/sandbox/`**。它太业务化，独立成包得不偿失。
- **`agents/memory/*`** 不要拆，**整体移到 `presets/deerflow/memory/`**。这是一个完整的"事实抽取"业务。
- **`agents/lead_agent/prompt.py` 760 行** 不要拆，**整体移到 `presets/deerflow/prompt.py`**。它是 DeerFlow 业务灵魂。

---

## 九、总结

DeerFlow 的 `deerflow-harness` 包当前是一个"**框架 + 应用**"混合体：

- **运行时部分**（LangChain 集成 / 沙箱抽象 / MCP 集成 / Skills 协议 / 反射 / 工具 / 流式桥）可以**完整抽离**到通用 SDK
- **应用部分**（DeerFlow 业务 prompt / 业务 middleware / 业务工具 / `/mnt/user-data` 路径 / `memory.json` / 业务 subagent / DeerFlowClient 门面）**必须留在应用层**

抽离后：

| 抽象层 | 责任 | 行数（估算） |
|--------|------|------------|
| **SDK（deerflow.runtime + 通用子包）** | agent 运行时、沙箱/工具/模型/路径抽象、MCP/Guardrails/Skills 协议 | ~8000 行 |
| **Preset（deerflow.presets.deerflow）** | DeerFlow 业务 middleware / prompt / 工具 / 状态扩展 | ~6000 行 |
| **App（app/）** | FastAPI Gateway / IM 集成 / 持久化 / 客户端门面 | ~5000 行 |

抽离的核心原则是**"先路径后业务"**：先把 `/mnt/user-data` 这种硬编码抽成 `PathProvider`，再拆 middleware，最后拆 subagent/tools。这条路最稳。

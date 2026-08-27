# Middleware 与 Tool 架构分层

## 概述

DeerFlow 基于 LangChain 的 `create_agent()` 构建 agent。`create_agent()` 编译出的 LangGraph 图只有 **2 个核心节点**（`model` 和 `tools`），所有横切关注点通过 **Middleware** 机制注入。

本文档解释 Middleware 与 LangGraph Node 的关系，以及 Sandbox、Subagent、MCP、Skills、Memory 五个核心概念在 Middleware 层和 Tool 层的分工。

---

## 一、Middleware 与 LangGraph Node 的关系

### 1.1 核心区别

| 概念 | 所属层级 | 职责 |
|------|----------|------|
| **LangGraph Node** | 图拓扑层 | 定义流程步骤（调用 LLM、执行工具） |
| **Middleware** | 节点内部层 | 在节点执行前后做拦截、加工、增强 |

**Middleware 不是替代 Node 的，而是在 Node 内部做拦截和加工。**

### 1.2 图结构

`create_agent()` 编译出的图只有 2 个核心节点：

```
START → [*.before_agent] → [*.before_model] → [model] ←──────────┐
                                                    │              │
                                                    ▼              │
                                                 [tools] ──────────┘
                                                    │
                                                    ▼
                                            [*.after_model] → [*.after_agent] → END
```

- **`model`**：调用 LLM，拿到 AIMessage（可能含 tool_calls）
- **`tools`**：LangGraph 内置的 `ToolNode`，统一执行所有工具
- **`*.before_agent` / `*.before_model` / `*.after_model` / `*.after_agent`**：middleware 的 hook 节点

所有工具（bash、file_read、task、MCP 工具…）共享同一个 `tools` 节点，不是每个工具一个 node。

### 1.3 Middleware 的两种介入方式

#### 方式一：作为独立 Graph Node（hook 节点）

当一个 middleware 覆盖了 `before_model` / `after_model` / `before_agent` / `after_agent`，`create_agent` 会为它创建独立 node，串在 graph 里：

```python
# 源码: langchain/agents/factory.py:1390
graph.add_node(f"{m.name}.before_model", before_node, ...)
```

#### 方式二：作为洋葱链拦截器（wrap 链）

`wrap_model_call` 和 `wrap_tool_call` 不创建新 node，而是在 `model` 和 `tools` 节点内部形成洋葱式调用链：

```
请求进入 model 节点
  → ThreadData.wrap_model_call     (修改 request)
    → Sandbox.wrap_model_call       (挂载虚拟路径)
      → Guardrail.wrap_model_call   (安全检查)
        → LLMErrorHandling.wrap_model_call
          → _execute_model_sync     (真正调 LLM)
        → ToolErrorHandling.wrap_model_call
      → Summarization.wrap_model_call
    → LoopDetection.wrap_model_call
  → Clarification.wrap_model_call   (拦截澄清请求)
返回给 graph
```

Middleware 在链中的顺序由 `_build_middlewares()` 严格控制（参见 `backend/packages/harness/deerflow/agents/lead_agent/agent.py`）。

### 1.4 所有 Middleware 共享同一个 State

整个 graph 只有一个 `AgentState` 对象，像流水线一样流过所有 middleware：

```python
class AgentState(TypedDict):
    messages: Required[Annotated[list[AnyMessage], add_messages]]  # 消息历史
    jump_to: NotRequired[JumpTo | None]   # 控制流跳转信号
    structured_response: NotRequired[Any]  # 结构化输出
```

每个 hook 的返回值 `dict[str, Any] | None` 被 LangGraph 合并回 state。DeerFlow 扩展了 `ThreadState`，增加了 `sandbox`、`thread_data` 等字段。

### 1.5 Middleware 的 6 个 Hook 点

`AgentMiddleware` 基类提供 6 个 hook 点（另有对应的 async 版本）：

| Hook | 执行时机 | 执行频率 | 修改 state 方式 |
|------|----------|----------|----------------|
| `before_agent` | agent 启动前 | 一次 | 返回 state 更新 dict |
| `before_model` | 每次调 LLM 前 | 多次（每轮循环） | 返回 state 更新 dict |
| `wrap_model_call` | 包裹 LLM 调用 | 多次 | 修改 request/response，不直接改 state |
| `after_model` | 每次调 LLM 后 | 多次 | 返回 state 更新 dict |
| `wrap_tool_call` | 包裹工具执行 | 多次 | 修改 tool call request/response |
| `after_agent` | agent 结束前 | 一次 | 返回 state 更新 dict |

一个 middleware 可以实现任意组合的 hook。`create_agent` 在编译 graph 时逐个检查每个 middleware 覆盖了哪些 hook，决定创建哪些 node 和洋葱链。

---

## 二、五大核心概念的分层

### 总览

```
概念        Middleware 层（干什么）               Tool 层（LLM 看到什么）
─────────────────────────────────────────────────────────────────────
Sandbox     ✅ 管理沙箱生命周期、虚拟路径映射      ✅ bash, ls, glob, grep, read_file, write_file, str_replace
Subagent    ✅ 限制并发子智能体数量               ✅ task(description, prompt, subagent_type)
MCP         ❌ 没有 middleware                   ✅ 来自 MCP 服务器的所有工具
Skills      ❌ 没有专用 middleware*               ✅ SKILL.md → 注入 prompt + skill_manage 工具
Memory      ✅ 队列化记忆更新、去重               ❌ 不暴露给 LLM
```

---

### 2.1 Sandbox（沙箱）

**文件：**
- Middleware: `backend/packages/harness/deerflow/sandbox/middleware.py`
- Tools: `backend/packages/harness/deerflow/sandbox/tools.py`

#### Middleware 层 — `SandboxMiddleware`

管理沙箱环境的生命周期：

- **Lazy 模式（默认）**：不在 `before_agent` 获取沙箱，由工具首次调用时通过 `ensure_sandbox_initialized()` 懒加载
- **Eager 模式**：在 `before_agent` 中调用 `get_sandbox_provider().acquire(thread_id)` 提前获取
- **`after_agent`**：释放沙箱 `get_sandbox_provider().release(sandbox_id)`
- 沙箱在同一个 thread 内跨轮次复用，不在每次 agent 调用后释放

#### Tool 层 — 7 个沙箱工具

| 工具 | 功能 |
|------|------|
| `bash` | 在沙箱中执行 bash 命令，校验路径、替换虚拟路径、遮蔽宿主机路径 |
| `ls` | 以树形格式列出目录内容 |
| `glob` | 按 glob 模式查找文件/目录 |
| `grep` | 在文本文件中搜索匹配行 |
| `read_file` | 读取文本文件内容，支持行范围 |
| `write_file` | 写入文本内容到文件 |
| `str_replace` | 替换文件中的子字符串 |

#### 协作关系

Middleware 在 state 里写入 `sandbox_id`，Tool 执行时从 `runtime.state["sandbox"]` 读取，知道该往哪个沙箱执行命令。Middleware 是"房子的钥匙"，Tool 是"房子里的家具"。

#### 容器生命周期（Warm-Pool 复用机制）

**源码位置：** `backend/packages/harness/agent_sdk/community/aio_sandbox/provider.py`

Sandbox 基于 Docker 容器运行 AIO sandbox 镜像（默认 `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest`）。容器**不会每次对话都创建和销毁**，而是通过 warm-pool 机制复用。

##### 镜像拉取策略

Docker 的默认行为：**只在本地缓存不存在时 pull**。代码中没有传 `--pull=always`，所以首次 `docker run` 后，后续都使用本地缓存的镜像。

```python
# provider.py 常量
DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_IDLE_TIMEOUT = 600    # 空闲 10 分钟后销毁
DEFAULT_REPLICAS = 3          # 最多同时保留 3 个容器（软限制，超出可突破）
IDLE_CHECK_INTERVAL = 60      # 每 60 秒检查一次空闲
```

##### 三层获取策略（acquire 方法）

`acquire(thread_id)` 不直接创建容器，而是按以下优先级查找：

```
Layer 1: 进程内缓存（内存）
  → thread_id 已绑定 sandbox_id 且 sandbox 还在内存中
  → 直接返回，零开销

Layer 1.5: Warm Pool（内存）
  → 上次对话 release 后放入 warm pool 的容器
  → 从 warm pool 取出，重新绑定到 thread
  → logger: "Reclaimed warm-pool sandbox xxx"

Layer 2: 跨进程发现（文件锁 + Docker 查询）
  → 检查是否有同名容器（deterministic 命名: skillhub-sandbox-{sha256[:8]}）
  → 有 → 发现并复用
  → 无 → 创建新容器

Layer 3: 创建新容器
  → docker run --rm -d -p {port}:8080 --name {name} [mounts...] {image}
  → wait_for_sandbox_ready: 轮询 /v1/sandbox 健康检查，最多等 60 秒
  → 如果并发数超过 replicas(3)，先驱逐 warm pool 中最旧的容器
```

##### 容器命名与 thread_id 绑定

```python
@staticmethod
def _deterministic_sandbox_id(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode()).hexdigest()[:8]
# 容器名: skillhub-sandbox-{sandbox_id}
```

同一 thread_id 每次生成相同的 sandbox_id，所以即使进程重启，也能通过跨进程发现找到之前的容器。

##### 完整生命周期流程

```
用户发起对话 (thread_id = "abc123")
  │
  ▼
SandboxMiddleware.before_agent() / 首次工具调用
  → acquire("abc123")
  → 哈希得 sandbox_id = "a1b2c3d4"
  → 三层查找: 无
  → docker run --name skillhub-sandbox-a1b2c3d4
  → 等待健康检查通过
  → 返回 sandbox_id
  │
  ▼
Agent ReAct 循环（多轮工具调用）
  → bash("pip install numpy")  │
  → read_file("/mnt/user-data/workspace/main.py")  ├─ 全部复用
  → write_file("/mnt/user-data/workspace/test.py")  │  同一个容器
  → str_replace(...)            │
  → 容器内文件状态在整个对话中累积保留
  │
  ▼
SandboxMiddleware.after_agent()
  → release(sandbox_id)
  → 容器不销毁！放入 warm pool
  → logger: "Released sandbox a1b2c3d4 to warm pool (container still running)"
  │
  ▼
空闲等待（若同一 thread 再次对话）
  → acquire("abc123") → warm pool 命中 → 直接复用，毫秒级
  │
  ▼
空闲超时 (600s 无活动)
  → _idle_checker_loop 检测到
  → destroy(sandbox_id)
  → docker stop skillhub-sandbox-a1b2c3d4
  → logger: "Destroyed idle warm-pool sandbox a1b2c3d4"
  │
  ▼
进程退出
  → atexit 注册 + SIGTERM/SIGINT 信号处理
  → shutdown() → 销毁所有 active + warm pool 容器
```

##### 容器内挂载结构

每个 thread 的容器挂载以下目录：

| 宿主机路径 | 容器内路径 | 读写 |
|---|---|---|
| `{thread_base_dir}/threads/{thread_id}/workspace` | `/mnt/user-data/workspace` | RW |
| `{thread_base_dir}/threads/{thread_id}/uploads` | `/mnt/user-data/uploads` | RW |
| `{thread_base_dir}/threads/{thread_id}/outputs` | `/mnt/user-data/outputs` | RW |
| `{thread_base_dir}/threads/{thread_id}/acp-workspace` | `/mnt/acp-workspace` | RO |
| `{skills_host_path}` | `/mnt/skills` | RO |

##### Sandbox 在 Agent 循环中的角色

Agent 循环中，sandbox 作为远程 HTTP 服务运行：

```
LLM 决定调用 bash("cat /mnt/user-data/workspace/main.py")
  │
  ▼
bash_tool() → _ensure_sandbox(runtime)
  → 从 runtime.state["sandbox"] 拿到 sandbox_id
  → provider.get(sandbox_id) → 返回 AioSandbox 实例
  → sandbox.execute_command("cat /mnt/user-data/workspace/main.py")
    → HTTP POST http://localhost:{port}/v1/sandbox/command
    → 在 Docker 容器内执行 bash
  → 返回 stdout 给 LLM
```

所有 7 个 sandbox 工具（bash/ls/glob/grep/read_file/write_file/str_replace）都通过 `_ensure_sandbox()` 获取同一容器实例，因此 agent 在对话中 `pip install` 的包、创建的文件，在后续工具调用中全部可见。

##### 并发控制

- **replicas=3**（软限制）：超过时驱逐 warm pool 中最旧的容器，如果 warm pool 为空则仍允许创建
- **per-thread 锁**（进程内）：同一 thread 的并发请求排队等待
- **文件锁**（跨进程）：通过 `{thread_dir}/{sandbox_id}.lock` 文件实现跨进程互斥



---

### 2.2 Subagent（子智能体）

**文件：**
- Middleware: `backend/packages/harness/deerflow/agents/middlewares/subagent_limit_middleware.py`
- Tool: `backend/packages/harness/deerflow/tools/builtins/task_tool.py`

#### Middleware 层 — `SubagentLimitMiddleware`

在 `after_model` 中检查 LLM 输出的 `AIMessage`：

1. 统计 `tool_calls` 中名为 `"task"` 的调用数量
2. 如果超过 `max_concurrent`（默认 3，范围 [2, 4]），截断到前 N 个
3. 替换 `AIMessage` 为截断后的版本

这是一个**纯防护层**：防止 LLM 一次发出过多并行 task 调用。

#### Tool 层 — `task_tool`

LLM 可调用的子智能体代理工具：

1. 解析 `subagent_type`（`"general-purpose"`、`"bash"` 或自定义类型）
2. 构建 `SubagentExecutor`，传入子智能体配置、工具、父上下文
3. 在后台线程中执行子智能体
4. 每 5 秒轮询一次，通过 stream writer 发送 `task_started`、`task_running`、`task_completed` 等事件
5. 子智能体完成后返回结果给主智能体

子智能体本身 `subagent_enabled=False`，防止递归嵌套。

#### 协作关系

Middleware 在 LLM 输出后、工具调度前裁剪 task 调用数量。Tool 负责真正的子智能体创建和执行。两者互不直接调用——Middleware 操作 AIMessage，Tool 操作 SubagentExecutor。

---

### 2.3 MCP（Model Context Protocol）

**文件：**
- `backend/packages/harness/deerflow/mcp/client.py` — 服务器配置构建
- `backend/packages/harness/deerflow/mcp/tools.py` — 工具加载
- `backend/packages/harness/deerflow/mcp/cache.py` — 工具缓存
- `backend/packages/harness/deerflow/mcp/oauth.py` — OAuth 集成

#### MCP 没有 Middleware

MCP 是纯工具提供协议，不参与 agent 生命周期管理。

#### Tool 层

MCP 工具通过以下流程加载：

1. `build_servers_config()` 读取 `ExtensionsConfig`，为每个启用的 MCP 服务器构建参数（支持 stdio、sse、http 传输）
2. `get_mcp_tools()` 通过 `langchain-mcp-adapters` 的 `MultiServerMCPClient` 发现所有工具
3. 工具在启动时缓存，通过文件 mtime 自动失效
4. `get_available_tools()` 将 MCP 工具合并到 agent 工具列表末尾

MCP 工具（如 `github_search_repos`、`slack_send_message`）和内置工具在 LLM 眼里完全一样——都是 `tools` 列表中的一项。

当 `tool_search` 启用时，MCP 工具注册到 `DeferredToolRegistry`，LLM 可以通过 `tool_search` 按描述发现它们。

---

### 2.4 Skills（技能）

**文件：**
- `backend/packages/harness/deerflow/skills/loader.py` — 加载 SKILL.md 文件
- `backend/packages/harness/deerflow/skills/parser.py` — 解析 YAML frontmatter
- `backend/packages/harness/deerflow/skills/manager.py` — 文件系统操作
- `backend/packages/harness/deerflow/skills/security_scanner.py` — 安全扫描
- `backend/packages/harness/deerflow/tools/skill_manage_tool.py` — 运行时管理工具

#### Skills 没有专用 Middleware

Skills 的机制是 prompt 注入 + 文件挂载，不依赖 middleware 模式。但有两个 middleware 是"skills-aware"的：

- `SummarizationMiddleware`：摘要时保留最近的 skill 文件读取
- `SandboxMiddleware`：将 skills 目录挂载到沙箱 `/mnt/skills/`

#### Tool 层

Skills 作为以下形式注入 agent：

1. **Prompt 注入**：`load_skills()` 扫描 `skills/public/` 和 `skills/custom/` 目录，解析 `SKILL.md` 文件（YAML frontmatter + Markdown 内容），注入到 system prompt
2. **文件挂载**：Skills 文件挂载到沙箱的 `/mnt/skills/{category}/{name}/`，沙箱工具（bash、read_file 等）可读取
3. **运行时管理**：`skill_manage_tool`（仅在 `skill_evolution.enabled` 时可用）允许 agent 创建、编辑、删除自定义 skills

`skill_manage_tool` 的所有写入操作经过 `scan_skill_content()` 安全扫描（使用 LLM 分类为 allow/warn/block），每次修改记录到 `HISTORY.jsonl`。

---

### 2.5 Memory（记忆）

**文件：**
- Middleware: `backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py`
- 队列: `backend/packages/harness/deerflow/agents/memory/queue.py`
- 更新器: `backend/packages/harness/deerflow/agents/memory/updater.py`
- 存储: `backend/packages/harness/deerflow/agents/memory/storage.py`
- 消息处理: `backend/packages/harness/deerflow/agents/memory/message_processing.py`

#### Middleware 层 — `MemoryMiddleware`

在 `after_agent` 中触发：

1. 检查 memory 是否启用
2. 从 runtime context 提取 `thread_id`
3. 过滤消息（只保留 user + assistant 对话，排除 tool call 消息）
4. 检测纠正信号和强化信号
5. 捕获当前 `user_id`（重要：队列在另一线程处理，ContextVar 不传播）
6. 入队到 `MemoryUpdateQueue` 做 debounce 处理

#### 没有 Tool 组件

Memory 不暴露任何工具给 LLM。LLM 不知道 memory 的存在，也不能主动调用。

#### 后台处理管道

1. **`MemoryUpdateQueue`**：Debounce 队列。`add()` 替换同一 thread_id 的已有条目，重置 `threading.Timer`。Debounce 期过后触发 `_process_queue()`
2. **`MemoryUpdater`**：使用 LLM 分析对话，提取结构化 JSON 更新。包括 user 信息（workContext、personalContext、topOfMind）、history 信息（recentMonths、earlierContext、longTermBackground）、facts（去重、置信度过滤、最大数量限制）
3. **`FileMemoryStorage`**：JSON 文件持久化，支持 per-user 和 per-agent 作用域，mtime 缓存失效
4. **`memory_flush_hook`**：在摘要中间件删除消息前，将即将被摘要的消息立即刷入 memory 队列（绕过 debounce）

#### 闭环

Memory 数据通过 `format_memory_for_injection()` 注入到 system prompt，在下一次对话中生效。

---

## 三、设计原则

### 什么时候是 Middleware？

```
✓ 管理资源的生命周期（创建/销毁沙箱）
✓ 在 LLM 调用前后做拦截（限制并发、错误处理、安全检查）
✓ 做后台异步工作（记忆更新、摘要）
✓ 不应该是 LLM 能主动控制的
```

### 什么时候是 Tool？

```
✓ 被 LLM 显式调用（"帮我搜一下这个文件"）
✓ 是 LLM 的"手和脚"（执行命令、读文件、发消息、代理任务）
✓ 需要 LLM 根据上下文判断何时使用
```

### 为什么有些概念同时有 Middleware 和 Tool？

Sandbox 和 Subagent 都需要"基础设施管理"（middleware）和"LLM 可调用能力"（tool）两层。Middleware 负责生命周期和限制，Tool 负责执行。这是一种**关注点分离**：把"怎么管理"和"怎么使用"拆开。

---

## 四、扩展设计讨论

### 4.1 上下文压缩 —— 多层压缩 Middleware

#### 现状

当前只有单层摘要压缩：`DeerFlowSummarizationMiddleware` 继承自 LangChain 的 `SummarizationMiddleware`，在 `before_model` 中检查 token 数，超阈值后用 LLM 将旧消息压缩为摘要，保留最近 N 条消息。

```python
# 触发条件（OR 逻辑，任一满足即触发）
trigger: 支持 "tokens", "messages", "fraction" 三种阈值

# 保留策略
keep: 保留最近多少消息/token/比例
```

DeerFlow 扩展了 skill 救援机制：摘要时识别并保留最近读取的 skill 文件（受 `preserve_recent_skill_count`、`preserve_recent_skill_tokens`、`preserve_recent_skill_tokens_per_skill` 三个预算控制）。

#### 对比 Claude Code 的三层策略

| 层级 | 策略 | 触发条件 |
|------|------|----------|
| 滑动窗口 | 丢弃最旧的消息，保留最近 N 条 | 消息数超过窗口大小 |
| 摘要压缩 | 用 LLM 将旧消息压缩成摘要 | token 超过阈值 |
| 归档下沉 | 将不常用的上下文写入文件，按需检索 | 长期记忆/冷数据 |

#### 设计方案

Middleware 模式天然适合做多层压缩，可以拆成多个独立 middleware 按序执行：

```
[SlidingWindowMiddleware] → [SummarizationMiddleware] → [ArchiveMiddleware] → [model]
```

```python
class TieredCompressionMiddleware(AgentMiddleware):
    """三层压缩中间件"""

    def before_model(self, state, runtime):
        messages = state["messages"]
        total_tokens = self.token_counter(messages)

        # 第一层：滑动窗口 —— 纯规则，不需要 LLM
        if len(messages) > self.window_size:
            messages = messages[-self.window_size:]

        # 第二层：摘要压缩 —— 调用轻量 LLM
        if total_tokens > self.summarize_threshold:
            old = messages[:self._find_cutoff(messages)]
            summary = self._summarize(old)
            messages = [summary_msg] + messages[self._find_cutoff(messages):]

        # 第三层：归档 —— 写入文件，注入可检索指针
        if total_tokens > self.archive_threshold:
            archived = self._archive_to_file(old_messages)
            messages = [self._make_pointer(archived)] + messages

        return {"messages": messages}
```

**关键挑战：**

- 归档层需要配套的检索机制（tool 或 middleware 注入），让 LLM 知道"我丢了什么、怎么找回来"
- 多层之间的协调——滑动窗口丢弃的消息，摘要层还没处理，会丢信息
- 压缩粒度——消息级别 vs token 级别 vs 语义级别

---

### 4.2 Subagent 间通信

#### 现状

Subagent 之间完全隔离，不能直接通信：

- 每个 subagent 运行在独立线程中，有自己的 event loop
- 各自拿到独立的消息列表，不知道其他 subagent 的存在
- 共享同一个 `sandbox_id`（可以读写同一沙箱文件），但**没有消息通道**
- 禁止 subagent 嵌套（`task` tool 在 subagent 的 `disallowed_tools` 列表中）
- 唯一的"通信"是间接的：A 写文件 → Parent 发现 → Parent 告诉 B

Parent Agent 是唯一协调者，通过 `task_tool` 的轮询机制获取结果，再决定是否把结果传给其他 subagent。

#### 设计方案

Subagent 间通信是**多智能体拓扑**问题，不应通过 middleware 实现，而应在 `SubagentExecutor` 层面增加通信机制。

**方案 A：共享消息总线（推荐）**

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Subagent A  │────▶│  MessageBus      │────▶│ Subagent B  │
│             │     │  (per-thread)    │     │             │
└─────────────┘     └──────────────────┘     └─────────────┘
```

新增 tool 暴露给 subagent：

```python
@tool("send_to_subagent")
def send_to_subagent(target_agent: str, message: str) -> str:
    """向另一个 subagent 发送消息"""
    bus = get_thread_message_bus()
    bus.send(sender=self.agent_name, receiver=target_agent, content=message)
    return f"Message sent to {target_agent}"

@tool("check_subagent_messages")
def check_subagent_messages() -> str:
    """检查是否有来自其他 subagent 的消息"""
    bus = get_thread_message_bus()
    return bus.receive(receiver=self.agent_name)
```

**方案 B：共享 State 扩展**

在 `ThreadState` 中增加 `subagent_messages` 字段，subagent 通过 middleware 的 `after_model` 写入，其他 subagent 在 `before_model` 中读取。但这种方式依赖 LangGraph 的 state reducer，不太适合高频消息。

**方案 C：Parent Agent 路由（现有模式增强）**

不引入 subagent 间直接通信，Parent Agent 更智能地协调：

```
Parent Agent → 启动 A 和 B 并行
  → A 返回中间结果
  → Parent 决定把 A 的结果传给 B
  → 调用 task_tool(prompt="A 发现了 X，基于此继续...")
```

**推荐路径：** 方案 A（消息总线）+ 方案 B（共享 state 中的文件路径）组合。共享沙箱文件系统用于大数据传递（已可用），消息总线用于小消息/状态同步，Parent Agent 保留最终决策权。

---

### 4.3 异步后台任务

#### 现状

`task_tool` 是伪异步——"启动后台线程 + 轮询阻塞等待"：

```python
executor.execute_async(prompt)   # 在后台线程启动 subagent
while True:
    result = get_background_task_result(task_id)
    if result.status == COMPLETED:
        return result.result      # 父 agent 一直阻塞到这里
    await asyncio.sleep(5)        # 每 5 秒轮询
```

父 agent 必须等 subagent 完成才能继续。不能 fire-and-forget，不能启动长期运行的后台任务。

但底层基础设施已经支持真正的异步：

```python
# executor.py — 已存在但未暴露给 LLM
_background_tasks: dict[str, SubagentResult] = {}   # 全局任务注册表
_scheduler_pool = ThreadPoolExecutor(max_workers=3)  # 调度线程池
_execution_pool = ThreadPoolExecutor(max_workers=3)  # 执行线程池

def execute_async(self, task, task_id=None) -> str:
    """在后台启动，立即返回 task_id"""
    _scheduler_pool.submit(run_task)
    return task_id
```

`get_background_task_result(task_id)` 可以随时查询，`request_cancel_background_task(task_id)` 可以取消。这些能力已存在，只是 `task_tool` 没有暴露 fire-and-forget 用法。

#### 设计方案

需要新增两个 tool 和一个 middleware：

**1. 新 Tool：`schedule_task`（fire-and-forget）**

```python
@tool("schedule_task")
async def schedule_task(
    description: str,
    prompt: str,
    subagent_type: str,
) -> str:
    """启动一个后台任务，不等待结果，立即返回 task_id。"""
    executor = SubagentExecutor(...)
    task_id = executor.execute_async(prompt)
    return f"Task scheduled: {task_id}. Use check_task_status to monitor."
```

**2. 新 Tool：`check_task_status`（查询后台任务）**

```python
@tool("check_task_status")
def check_task_status(task_id: str) -> str:
    """查询后台任务的执行状态"""
    result = get_background_task_result(task_id)
    if result is None:
        return f"Task {task_id} not found"
    return f"Status: {result.status.value}, Result: {result.result or 'Pending...'}"
```

**3. 新 Middleware：`BackgroundTaskNotificationMiddleware`（结果通知）**

```python
class BackgroundTaskNotificationMiddleware(AgentMiddleware):
    """在 before_model 中检查已完成的后台任务，注入通知消息"""

    def before_model(self, state, runtime):
        completed = self._check_completed_tasks(state)
        if completed:
            notification = HumanMessage(
                content=f"[Background task completed] {task_id}: {result}",
                name="system"
            )
            return {"messages": [notification]}
        return None
```

#### 完整流程

```
用户: "帮我做三件事：重构 A 模块、优化 B 查询、写 C 文档"

Agent:
  1. schedule_task("重构 A 模块", ...)  → task_001
  2. schedule_task("优化 B 查询", ...)  → task_002
  3. 自己写 C 文档
  4. check_task_status("task_001")      → "still running"
  5. 继续写 C 文档...
  6. [BackgroundTaskNotification]        → "task_001 completed: ..."
  7. check_task_status("task_002")      → "completed: ..."
  8. 汇总所有结果给用户
```

#### 更进一步的定时任务

如需 Cron 式定时任务，需要额外的调度层（不在 middleware 范围内）：在 Gateway API 层增加调度器，或在 LangGraph Server 层面支持。Middleware 只负责"在 agent 内部感知和管理这些异步任务的状态"。
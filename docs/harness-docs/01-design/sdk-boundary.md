# SDK 边界定义：L1 / L2 / L3

> 关键概念：区分"业务耦合"和"通用特性"，避免抽离时砍掉特性。

## 核心定义

| 层级 | 定义 | 抽离策略 |
|------|------|----------|
| **L1 业务耦合** | 换成别的产品/项目**不会这样写**的具体选择 | 必须可注入，SDK 不硬编码 |
| **L2 特性 + 可配置业务** | 特性通用，但具体实现有 DeerFlow 业务选择 | 特性保留在 SDK，业务通过 Protocol 注入 |
| **L3 纯通用** | 任何 agent runtime 都需要 | 直接抽到 SDK |

## L1：业务耦合（必须可注入）

业务耦合 = DeerFlow 产品特有的具体选择，换成别的项目不会这样写。

### 路径前缀类

| 业务耦合 | 当前值 | 抽离方式 |
|----------|--------|----------|
| 主路径前缀 | `/mnt/user-data` | `PathProvider` Protocol |
| Skills 路径 | `/mnt/skills` | `PathProvider.get_skills_dir()` |
| Workspace 默认 venv | `/mnt/user-data/workspace/.venv` | `PathProvider.get_default_venv()` |
| ACP workspace | `/mnt/acp-workspace` | `PathProvider.get_acp_workspace_dir()` |

### 数据模型类

| 业务耦合 | 当前值 | 抽离方式 |
|----------|--------|----------|
| Memory 数据模型 | `workContext` / `personalContext` / `topOfMind` 三段式 | `MemorySchema` Protocol |
| Memory 存储 | `memory.json` 文件 | `MemoryStorage` ABC（已存在） |
| User profile 字段 | `USER.md` | `UserProfile` Protocol |
| Agent personality | `SOUL.md` | `AgentSoul` Protocol |
| Thread 字段 | 各种 DeerFlow 特有字段 | 业务字段从 BaseState 移出 |

### 工具命名类

| 业务耦合 | 当前值 | 抽离方式 |
|----------|--------|----------|
| 澄清工具 | `ask_clarification` | `ToolName` 参数或 Protocol |
| 文件展示 | `present_files` | 同上 |
| 图片查看 | `view_image` | 同上 |
| Subagent 入口 | `task` | `SubagentToolName` |
| 技能管理 | `skill_manage` | `SkillToolName` |
| 图像处理 | `view_image` | 同上 |

### Prompt 文案类

| 业务耦合 | 当前内容 | 抽离方式 |
|----------|----------|----------|
| 角色定位 | "You are an open-source super agent" | `system_prompt` 参数 |
| 示例 | "Tencent 股价"、"Compare 5 cloud providers" | 由 preset 注入 |
| 引用格式 | `[citation:Title](URL)` | `CitationFormat` Protocol |
| 工作目录说明 | "/mnt/user-data/..." | `PathProvider` 自动生成 |

### Subagent 角色类

| 业务耦合 | 当前值 | 抽离方式 |
|----------|--------|----------|
| 通用 agent | `general-purpose` | `SubagentRegistry` Protocol |
| Bash agent | `bash` | 同上 |
| 角色描述 | "For ANY non-trivial task..." | `SubagentDefinition` Protocol |

### 安全规则类

| 业务耦合 | 当前值 | 抽离方式 |
|----------|--------|----------|
| 高危命令 | `rm -rf /`, `dd if=`, `mkfs` 等 | `AuditRules` Protocol |
| 中危命令 | `chmod 777`, `pip install`, `apt install` | 同上 |
| 路径前缀 | `LD_PRELOAD`, `LD_LIBRARY_PATH` | 同上 |
| Fork bomb | `:(){ :\|:& };:` | 同上 |
| 本地 bash 禁用 | `is_host_bash_allowed()` 返回 False | `PathProvider.is_host_bash_allowed()` |

### CLI 门面类

| 业务耦合 | 当前内容 | 抽离方式 |
|----------|----------|----------|
| Client 类名 | `DeerFlowClient` | 移到 `agent_sdk.presets.deerflow.DeerFlowAgent` |
| Chat API | `client.chat()` | 移到 preset |
| Stream API | `client.stream()` | 移到 preset |
| 文档字符串 | "DeerFlow agent system" | 移到 preset |

## L2：特性 + 可配置业务（特性保留，业务可注入）

特性 = 任何 agent 框架都应该有的能力。业务 = 特性里的具体选择。

### 任务规划（TodoList）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| TodoMiddleware 类 | 特性 | 保留在 SDK |
| `write_todos` 工具定义 | 特性 | 保留在 SDK |
| TodoList 状态管理 | 特性 | 保留在 SDK |
| Todo system_prompt 文案 | 业务 | `TodoSystemPrompt` Protocol |
| Todo tool description 文案 | 业务 | `TodoToolDescription` Protocol |

### 长期记忆（Memory）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| MemoryMiddleware | 特性 | 保留在 SDK |
| MemoryUpdater（LLM 抽取事实） | 特性 | 保留在 SDK |
| MemoryStorage ABC | 特性 | 保留在 SDK |
| FileMemoryStorage 实现 | 业务 | 移到 preset（提供 PathProvider 适配） |
| workContext 三段式数据模型 | 业务 | `MemorySchema` Protocol |
| MEMORY_UPDATE_PROMPT | 业务 | 移到 preset |
| FACT_EXTRACTION_PROMPT | 业务 | 移到 preset |
| MemoryUpdateQueue（debounce 机制） | 特性 | 保留在 SDK |

### 多 Agent 协同（Subagent）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| SubagentExecutor | 特性 | 保留在 SDK |
| SubagentConfig 数据类 | 特性 | 保留在 SDK |
| SubagentRegistry | 特性 | 保留在 SDK |
| 任务轮询机制 | 特性 | 保留在 SDK |
| 三个 ThreadPoolExecutor | 特性 | 保留在 SDK |
| trace_id 关联 | 特性 | 保留在 SDK |
| general-purpose / bash 角色定义 | 业务 | `SubagentRegistry` Protocol 默认实现 |
| max_concurrent=3 / timeout=900s | 业务 | `SubagentConfig` 默认参数（用户可改） |

### 文件管理（Uploads / Workspace / Outputs）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| UploadsMiddleware | 特性 | 保留在 SDK |
| per-thread workspace 隔离 | 特性 | 保留在 SDK |
| UploadContext 抽象 | 特性 | 保留在 SDK |
| `/mnt/user-data/*` 路径 | 业务 | `PathProvider` |
| `validate_thread_id` 等校验 | 业务 | 移到 preset（或参数化） |
| uploads/manager.py CRUD | 业务 | 移到 preset（提供抽象） |

### 沙箱（Sandbox）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| Sandbox ABC | 特性 | 保留在 SDK |
| SandboxProvider ABC | 特性 | 保留在 SDK |
| SandboxMiddleware | 特性 | 保留在 SDK |
| LocalSandbox | 业务实现 | 移到 `community/` 可选包 |
| RemoteSandbox | 业务实现 | 移到 `community/aio_sandbox` |
| `sandbox/tools.py` 1582 行（bash/grep/glob/ls 等） | 业务 | 保留为 preset 默认实现 |

### 安全审计（Sandbox Audit）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| SandboxAuditMiddleware | 特性 | 保留在 SDK |
| 审计框架（高/中危分类、模式匹配） | 特性 | 保留在 SDK |
| 默认规则列表（chmod 777 等） | 业务 | `AuditRules` Protocol |
| 拆解复合命令的逻辑 | 特性 | 保留在 SDK |

### Skills（SKILL.md 协议）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| Skill 数据类 | 特性 | 保留在 SDK |
| YAML frontmatter 解析 | 特性 | 保留在 SDK |
| SKILL.md 加载器 | 特性 | 保留在 SDK |
| 安装器（zip bomb 防护等） | 特性 | 保留在 SDK |
| security_scanner（LLM 评估） | 业务 | 移到 preset |
| manager.py CRUD | 业务 | 移到 preset |

### MCP 集成

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| MCP client | 特性 | 保留在 SDK |
| MCP cache（mtime 失效） | 特性 | 保留在 SDK |
| OAuth 拦截器 | 特性 | 保留在 SDK |
| 同步包装 | 特性 | 保留在 SDK |

### Guardrails（OAP 协议）

| 项 | 类型 | 抽离方式 |
|----|------|----------|
| GuardrailProvider Protocol | 特性 | 保留在 SDK |
| GuardrailMiddleware | 特性 | 保留在 SDK |
| AllowlistProvider 实现 | 业务 | 移到 preset |

## L3：纯通用（直接抽到 SDK）

### 通用 middleware（5 个）

| Middleware | 说明 |
|------------|------|
| `DanglingToolCallMiddleware` | 修补缺失的 ToolMessage，避免 LLM 看到悬挂的 tool call |
| `ToolErrorHandlingMiddleware` | 工具异常转 ToolMessage，run 继续 |
| `TokenUsageMiddleware` | 按 token 计费/统计 |
| `LoopDetectionMiddleware` | 哈希滑动窗口检测重复 tool call |
| `DeferredToolFilterMiddleware` | Claude Code 风格延迟工具发现 |

### 抽象 ABC

| ABC | 说明 |
|-----|------|
| `Sandbox` | 沙箱接口（execute_command, read_file, write_file, list_dir, glob, grep, update_file） |
| `SandboxProvider` | 沙箱生命周期（acquire, get, release） |
| `MemoryStorage` | 记忆存储（load, save, reload） |
| `UserContext` | 用户上下文（user_id 隔离） |
| `StreamBridge` | 流式桥（生产-消费解耦） |

### 工具/辅助

| 名称 | 说明 |
|------|------|
| `RuntimeFeatures` 数据类 | 声明式特性开关 |
| `@Next` / `@Prev` 装饰器 | middleware 位置声明 |
| `create_agent()` 函数 | SDK 唯一公开入口 |
| `Reflection` 工具 | 字符串路径 → Python 对象 |
| `Tracing` 工厂 | LangSmith / Langfuse callback |
| `Utils`（文件转换、网络端口分配、HTML 解析） | 通用工具 |

## 抽离判定清单

每个 DeerFlow 模块都用这个清单判断：

1. 这个模块做的事，**换成别的项目会做吗**？
   - 是 → L3 通用
   - 否 → 第 2 步

2. 这个模块的**概念通用**，但 DeerFlow 用了**自己的路径/字段/命名/规则**吗？
   - 是 → L2 特性（保留 + 协议化）
   - 否 → 第 3 步

3. 这个模块是 DeerFlow **产品特有**（品牌、UX、具体业务）吗？
   - 是 → L1 业务（移到 preset）

## 关键修正说明

### 早期错误：把"特性"当"业务"

最初我们提议把 SDK 削成"最小 agent + opt-in 特性"，但实际上：

- 任务规划、长期记忆、多 agent、文件管理、沙箱、审计、Skills、MCP **都是必要的特性**
- 如果 SDK 只是空壳，用户自己用 LangGraph 写就行
- 特性里的**业务选择**才是 L1 业务耦合

### 修正后的核心原则

**保留特性 + 注入业务**：
- 特性逻辑在 SDK
- 业务选择通过 Protocol 在 preset / 用户代码中注入
- SDK 默认不预装任何业务选择，但导入 preset 可一行启用

详见 `architecture.md` 和 `feature-inventory.md`。

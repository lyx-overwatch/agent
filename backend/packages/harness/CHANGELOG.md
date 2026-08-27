# 变更日志

格式参考 [Keep a Changelog](https://keepachangelog.com/)，使用语义化版本。

## [0.1.0] - 2026-07-14

### Added

**SDK 核心**：
- `create_agent()` 主入口，支持 `RuntimeFeatures` 特性开关 + `MiddlewareChainConfig` 注入
- 18 个 middleware 按正确顺序装配（ThreadData → Uploads → Sandbox → ... → Clarification）
- `@Next` / `@Prev` 装饰器声明 middleware 位置

**抽象 ABC**：
- `PathProvider` Protocol — 虚拟路径映射
- `MemorySchema` Protocol — 长期记忆数据模型
- `SubagentRegistry` Protocol — 子代理角色表
- `AuditRules` Protocol — 沙箱安全审计规则
- `Sandbox` / `SandboxProvider` ABC — 沙箱后端
- `StreamBridge` ABC — SSE 流桥接
- `MemoryStreamBridge` — 进程内 asyncio.Queue 参考实现

**沙箱工具**：
- 7 个 `@tool` 装饰工具：bash / ls / glob / grep / read_file / write_file / str_replace
- `SandboxPathResolver` — 虚拟路径 ↔ 物理路径解析 + 校验 + 掩码
- `HostBashPolicy` Protocol — 主机 bash 权限控制
- `SandboxAuditMiddleware` — 命令审计 + 分类（BLOCK / WARN / PASS）
- `SandboxToolsConfig` — 品牌中立配置（virtual_path_prefix、custom_mounts、max_results 等）

**记忆系统**：
- `MemoryMiddleware` — before_agent 加载 + after_agent 持久化
- `MemoryUpdater` — 分段更新（update_section）
- `MemoryStorage` ABC — 可插拔存储后端
- `FileMemoryStorage` — 文件系统参考实现

**子代理**：
- `SubagentExecutor` — ThreadPoolExecutor + 超时 + 取消 + 后台任务管理
- `task` tool — 注册表校验 + executor 集成 + 轮询
- `SubagentLimitMiddleware` — 并发截断

**集成子系统**：
- MCP 客户端 — `build_server_params` / `get_mcp_tools` / `list_mcp_tool_names`
- MCP OAuth — `OAuthTokenManager` (client_credentials + refresh_token)
- Skills — `load_skills` / `parse_skill_file` / `ainstall_skill_from_archive`（.zip ZIP 安装器，含 zip-bomb 防护）

**运行时基础设施**：
- `ModelConfig` + `create_chat_model` 工厂（thinking 切换、stream_usage、tracing）
- `ToolConfig` + `load_tools`（class path 加载 + dedupe + group 过滤）
- `TracingConfig` + `build_tracing_callbacks`（LangSmith / Langfuse 懒加载）
- 3 个 Checkpointer 后端（memory / sqlite / postgres）
- 3 个 Store 后端（async CM）
- `PortAllocator` — 线程安全端口分配
- `resolve_class` / `resolve_variable` — 反射工具

**DeerFlow preset（参考实现）**：
- `DeerFlowAgent` — 便利类，lazy graph build，ainvoke/invoke/astream/stream
- `DeerFlowPathProvider` — `/mnt/user-data` 路径前缀
- `DeerFlowMemorySchema` — 三区段记忆模型（user + history + facts）
- `DeerFlowSubagentRegistry` — general-purpose / bash 内置角色
- `DeerFlowAuditRules` — 15 条 high-risk + 5 条 medium-risk 审计规则
- `DEERFLOW_TODO_PROMPTS` — 品牌化 Todo 提示
- `SYSTEM_PROMPT_TEMPLATE` — ~700 行 DeerFlow 系统提示

**测试**：
- 1258 个单元测试 + 集成测试（1 skip 为 Windows symlink）
- 覆盖：paths / memory / subagents / sandbox / tools / middlewares / runtime / skills / mcp / tracing / reflection / utils / presets

### Notes

- 此版本为从 DeerFlow 后端抽离的初始版本
- `backend/` 全程未触碰（ADR-010 合规）
- SDK 不 import `backend.*` / `deerflow.*` / `app.*`
- Python 3.12+，依赖 langchain>=0.6 / langgraph>=0.6 / pydantic>=2.0

---

## [0.0.0.dev0] - 2026-07-03

### Added
- 目录脚手架
- 规划文档（vision / design / plan / status）
- 空包占位
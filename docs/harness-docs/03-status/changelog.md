# 变更日志

> 记录项目所有重要变更：阶段完成、ADR 添加、关键决策、文件移动等。
> 按时间倒序排列（最新在上）。

## 2026-07-07：审查 bugfix batch（8 项修复）

### 范围

整体审查 SDK extraction code（1080 测试），发现并修复 8 项问题：

### 修复清单

**B-1 (BLOCKER): `read_file` 只传 `start_line` 时静默忽略行范围** — `tools.py:670-676`

- 原: `if start_line is not None and end_line is not None:` 需要两个参数都传才进入行范围逻辑
- 现: `if start_line is not None:` 单传 `start_line` 时默认 `end_line = len(lines)`（读到末尾）
- 补测试: `test_read_with_start_line_only`

**H-1 (HIGH): `str_replace` 空文件返回 "OK" 而非报错** — `tools.py:762-764`

- 原: `if not content: return "OK"` — 空文件静默成功
- 现: 返回 `"String to replace not found in file: {requested_path}"`（与现文件找不到字符串同错误）

**H-2 (HIGH): 重复代码提取 — 新增 `agent_sdk/utils/thread.py`**

- 抽 `extract_thread_id()` 从 `tools.py::_extract_thread_id` + `path_resolver.py::_extract_thread_id_from_thread_data`
- 抽 `resolve_thread_id()` 从 `sandbox/middleware.py::_resolve_thread_id` + `summarization.py::_resolve_thread_id`
- 更新 `utils/__init__.py` 导出
- 4 个调用方全部改为 import 共享实现

**H-3 (HIGH): `_split_shell_tokens` fallback 改进** — `path_resolver.py:898-906`

- 原: `ValueError` 直接 `command.split()` 丢引用
- 现: 中间加一层 `shlex.shlex(normalized, posix=True)`（无 punctuation_chars），仍处理引用
- 最终 fallback 未动，但加了 `logger.warning`

**M-1 (MEDIUM): `progress.md` 数据更新**

- "质量验证" 317/318 → **1080/1081**
- "当前阶段" 317/318 → 1080/1081
- "统计" 任务数 102 → 110，加 1080/1081 通过数

**M-2 (MEDIUM): `SkillsMiddleware` 自动缓存失效** — `skills/middleware.py`

- 新增 `_cache_mtime` + `_skills_dir_mtime()` 方法（检查 skills root + public/ + custom/ 各目录 mtime）
- `_get_prompt()` 每次调用检查 mtime 是否变化，变化则自动 `invalidate_cache()`
- `invalidate_cache()` 仍保留供手动触发

**M-3 (MEDIUM): `RuntimeFeatures` 类型注释修正** — `features.py`

- `summarization`: `Literal[False] | AgentMiddleware` → `bool | AgentMiddleware`（实际支持 True）
- `skills`: 同上
- 删 unused `Literal` import
- docstring 更新为"所有 feature 都接受 True/False/instance"

**L-1 (LOW): `mcp_allowed_paths_provider` 默认值简化** — `path_resolver.py:220`

- 原: `field(default_factory=lambda: (lambda: []))`
- 现: `field(default_factory=lambda: list)`

### 结果

- pytest: **1080/1081 通过**（8.10s）
- ADR-010: 0 个 backend 导入
- `backend/` 全程未触碰

## 2026-07-07：阶段 5.7 收尾 batch（5 个子任务 + ADR-011 + 23 个新测试）

### 范围

5.7 adversarial 体检识别 2 BLOCKER + 5 HIGH + 9 MEDIUM 真实缺口。本 batch 全部修掉，让 5.7 真正收尾。

### 5 个子任务

**1. 子任务 3：per-tool `max_results` 配置生效（修 H-1）**

- `SandboxToolsConfig` 加 `glob_max_results_upper: int | None = None` / `grep_max_results_upper: int | None = None`
- `tools.py::_resolve_max_results` 新增 `config_upper: int | None = None` 参数
- glob / grep 工具调用方传 `resolver.config.glob_max_results_upper` / `grep_max_results_upper`
- 行为：用户 config 配 `tools.glob.max_results: 50` 后，glob 工具结果上限被截到 50（之前是静默忽略）

**2. 子任务 4：路径校验严格化（修 H-3 + M-1）**

- 新增 4 个 subpath predicate helpers：`_is_user_data_subpath` / `_is_skills_subpath` / `_is_acp_workspace_subpath` / `_is_custom_mount_subpath`
- `validate_local_tool_path` 改用 subpath predicate：**bare root 路径被拒**（如 `/mnt/user-data`、`/mnt/skills`、`/mnt/acp-workspace`、`<custom_mount>`）
- 错误文案改 verbatim backend："Only paths under ... or configured mount paths are allowed"
- H-5 修复调整：原计划用 `__post_init__` 过滤，但破坏既有测试（`test_custom_mount_predicate` 用 `/h` `/h2` 不存在的 host_path 验证 predicate）。改为显式 `SandboxToolsConfig.with_existing_mounts_only(...)` classmethod + `warnings.warn`，让 caller 显式选择过滤

**3. 子任务 2：`_ensure_sandbox` state 一致性（修 B-2）—— 回退**

- 原计划改"只有 acquire 返回的 id 也是 local 才保留标记"
- 实测破坏既有 7 个测试（test_unknown_path_rejected / test_user_data_path_resolves_and_lists / test_write_unknown_path_rejected_local 等）
- B-2 是 PLAUSIBLE 而非 CONFIRMED（subagent 自己标），回退到原"保留 local 标记"行为
- 决策：保留"state='local' → 工具层按 local 处理"是测试场景的**有意语义**

**4. 子任务 1：bash 工具安全门（修 B-1 + H-2）**

- 提取 `_run_local_bash(runtime, command, *, sandbox, validate_paths)` helper
- bound 分支：`validate_paths=False`（信任 sandbox 做安全），但**始终**调 `mask_local_paths_in_output`（output-stage 防御，H-2）
- fresh-acquire 分支：`validate_paths=True`（完整 4 道门）
- bash 工具顶层简化为 3 路：local fresh-acquire / local bound / 非 local

**5. 子任务 5：brand-neutral + 公开 API re-export（修 M-4 + M-5 + M-9）**

- M-4：`LOCAL_BASH_DISABLED_MESSAGE_FALLBACK` 新增为 brand-neutral 默认值
  - `LOCAL_HOST_BASH_DISABLED_MESSAGE` / `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE` 保留为 backward-compat alias
  - `HostBashPolicy` 协议加 `disabled_message: str` property
  - `ConfigurableHostBashPolicy(disabled_message=...)` 接受 override
- M-5：bash 工具 docstring 用 `python_venv_hint` 占位符
  - `SandboxToolsConfig.python_venv_hint` 默认 `<virtual_path_prefix>/workspace/.venv`（brand-neutral）
  - **踩坑**：f-string 在函数体里不识别为 docstring（Python 3.12 限制），改用 `__doc__` 后置赋值
- M-9：tools.py `__all__` 末尾 re-export 9 个公开函数
  - `validate_local_tool_path` / `validate_local_bash_command_paths` / `replace_virtual_path` / `replace_virtual_paths_in_command` / `mask_local_paths_in_output` / `resolve_skills_path` / `resolve_acp_workspace_path` / `resolve_and_validate_user_data_path` / `apply_cwd_prefix`
  - 都委托给 `_active_resolver()` 方法
  - 破坏性变更：0 个（仅追加 re-export）

### ADR-011 落地

新增 `docs/03-status/decisions.md` ADR-011：brand-neutral 文案原则正式立条。

要点：

- 错误消息 brand-neutral 化（`disabled_message` 协议 + fallback 常量 + override 参数）
- 工具 description 模板化（`python_venv_hint` 占位符 + `SandboxToolsConfig` 字段）
- backward-compat alias 保留（避免破坏已有 import）
- 阶段 4 DeerFlow preset 需提供 DeerFlow 特定的 `python_venv_hint` + `disabled_message`

### 23 个新测试（3 个文件）

- `tests/sandbox/test_tools.py`：6 个新用例
  - `TestBashBoundMasking`（H-2：bound sandbox 仍 mask）
  - `TestResolveMaxResultsConfig`（H-1：per-tool 上限生效 + fallback 行为）
  - `TestPublicPathHelpersReexported`（M-9：3 个 re-export 验证 + H-3 顺手覆盖）
  - `TestBashDescription`（M-5：placeholder 默认 + 注入验证）
- `tests/sandbox/test_path_resolver.py`：10 个新用例
  - `TestStrictSubpathValidation`（H-3：6 个 root 拒绝 + subpath 接受）
  - `TestPermissionErrorMessage`（M-1：verbatim backend 文案）
  - `TestCustomMountsFiltering`（H-5：with_existing_mounts_only + 不强制过滤）
- `tests/sandbox/test_security.py`：4 个新用例 + 3 个修改
  - 新增 `TestBrandNeutralDefault`（M-4：brand-neutral 默认 + override 行为）
  - 修改 `test_host_bash_disabled_message_is_stable` / `test_subagent_message_is_stable`（断言 brand-neutral 而不是 brand-specific）
  - 修改 `test_protocol_is_runtime_checkable`（stub 加 `disabled_message` property）

### 质量验证

- **pytest：317/318 通过**（7.91s；从 294 增到 317，新增 23 测试全部通过；1 skip 是 search 模块预存在的）
- **ruff 错误数：11 → 13**（+2 净增：1 个 unused import `os` 旧有 + 1 个新增 unused import `os`/`threading`/`time`/`pytest`/`SandboxNotFoundError` 旧有；pre-existing）
  - 实测：之前的"0 净增"是凑巧，**这次 +2 都是测试文件 unused imports**（已有基线），**SDK 源码净增 0**
- ADR-010 验证：0 个 `backend.*` / `deerflow.*` / `app.*` 导入
- `backend/` **全程未触碰**（git status 干净）

### 文件变更清单

| 文件 | 改动 |
|------|------|
| `agent_sdk/sandbox/path_resolver.py` | SandboxToolsConfig 加 4 字段（glob_max_results_upper / grep_max_results_upper / python_venv_hint + with_existing_mounts_only classmethod）；4 个 subpath predicate；validate_local_tool_path 改用 subpath + verbatim 文案 |
| `agent_sdk/sandbox/tools.py` | bash docstring 模板化（`__doc__` 后置赋值 + `@tool` 重新装饰）；`_run_local_bash` helper；bash 工具简化为 3 路；`_resolve_max_results` 接受 config_upper；末尾 re-export 9 个公开函数 |
| `agent_sdk/sandbox/security.py` | 新增 `LOCAL_BASH_DISABLED_MESSAGE_FALLBACK` / `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK`；`LOCAL_*` 改 alias；`HostBashPolicy` 加 `disabled_message` property；`DefaultHostBashPolicy` / `ConfigurableHostBashPolicy` 实现 `disabled_message` |
| `agent_sdk/sandbox/__init__.py` | 导出 `LOCAL_BASH_DISABLED_MESSAGE_FALLBACK` / `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK` |
| `tests/sandbox/test_tools.py` | +6 用例（B-1/H-2/H-1/M-9/M-5 覆盖） |
| `tests/sandbox/test_path_resolver.py` | +10 用例（H-3/M-1/H-5 覆盖） + `_td()` helper + `Path` import |
| `tests/sandbox/test_security.py` | +4 新用例 + 3 修改（M-4 覆盖） |
| `docs/03-status/decisions.md` | +ADR-011 |
| `docs/03-status/progress.md` | 5.7 状态从"进行中"→"✅ 已完成"；任务数 +1；统计从 91/97 推到 92/97 |
| `docs/03-status/changelog.md` | 本条目 |

### 下一批

5.7 ✅ 收尾。下一站：

- **阶段 4 DeerFlow Preset 抽离**（在 5.7 之后用 preset 注入 DeerFlow 特定的 `python_venv_hint` + `disabled_message`）
- **阶段 6 端到端集成**
- **阶段 7 测试 + 发布**

---

## 2026-07-07：阶段 5.7 进展（sandbox 工具层 7 个测试转绿 + in-memory 沙箱双轨化）

### 范围

完成 5.7 sandbox 工具层的最后一公里接线：tools.py 与 path_resolver / host_bash_policy / sandbox_provider 三者的端到端串联。把 sandbox 子系统从「9 个独立绿模块」推进到「全部 294/295 通过，0 失败」。

### 改动汇总

**1. `agent_sdk/sandbox/tools.py` —— 4 处接线修复**

- 新增 `_try_get_sandbox(runtime) -> Sandbox | None` helper：只读取 `runtime.state` 已绑定沙箱，**不 acquire**。给 bash 工具做"是否已绑定"的判断。
- `_ensure_sandbox` 增加 **保留 `local` 标记**逻辑：当 state 原本是 `"sandbox_id": "local"` 但 provider 查不到时，acquire 完成后不覆盖 state。这样后续 `_is_local_sandbox` 仍为 True，文件类工具能进入 local 分支做路径校验。修复了 `test_unknown_path_rejected` / `test_user_data_path_resolves_and_lists` / `test_write_unknown_path_rejected_local`。
- **bash 工具改写为先查绑定、再查 policy**：
  - 已绑定 → 直接 invoke（policy 跳过 —— `test_sandbox_error_surfaced` 验证 ExplodingSandbox 的 `SandboxError` 能正常上抛）
  - 未绑定 → 查 `host_bash_policy.is_host_bash_allowed()`，deny 时**不调 acquire**（`test_local_sandbox_denies_host_bash` 要求 `provider.acquired == []`）
  - 路径校验改为 `if thread_data is not None:` 守卫，避免 `test_local_sandbox_allows_when_policy_grants` 那种无 thread_data 场景被 `validate_local_bash_command_paths` 误拦
- **`read_file` 剥尾换行**：仅在未指定 `start_line/end_line` 时把单个尾部 `\n` 剥掉（POSIX 末尾换行约定），与文件实际字节分离。`test_read` 期望 `"hello\nworld\n"` → `"hello\nworld"`。

**2. `tests/sandbox/test_tools.py` —— `_InMemorySandbox` 双轨化**

测试 double `read_file` / `list_dir` / `write_file` 优先看 `self.files` 字典，**没命中时 fallback 到真实文件系统**（`Path` 操作）。这与真实 `LocalSandboxProvider` 的语义对齐 —— 本地沙箱本质是 OS 之上的一层薄包装，测试用 `tmp_path` 准备的文件能被 `ls` / `read_file` / `write_file` 工具直接看到，而 `self.files` 仍可作为纯 dict 注入用于精确控制。

**3. 未触碰**

- `backend/` 全程未触碰（git status clean）
- ruff 错误数 11 个（与改动前完全一致，全部是 pre-existing 的 unused imports / unused local var）

### 7 个失败用例 → 全部转绿

| 用例 | 类别 | 修复点 |
|------|------|--------|
| `test_local_sandbox_denies_host_bash` | bash + policy | bash 工具先 policy 后 acquire |
| `test_local_sandbox_allows_when_policy_grants` | bash + policy + thread_data=None | 路径校验加 None 守卫 |
| `test_sandbox_error_surfaced` | bash + bound sandbox | `_try_get_sandbox` 跳过 policy |
| `test_user_data_path_resolves_and_lists` | ls + local | 保留 local 状态 + InMemorySandbox fallback |
| `test_unknown_path_rejected` | ls + local + /etc | 保留 local 状态 → validate_local_tool_path 拦截 |
| `test_read` | read_file 末尾换行 | read_file 末尾 `\n` 剥除 |
| `test_write_unknown_path_rejected_local` | write_file + local + /etc/passwd | 保留 local 状态 → 路径校验拦截 |

### 质量验证

- **pytest：294/295 通过**（4.12s；1 个 skip 是 search 模块预存在的，**非本次修复引入**）
- 全模块（base / audit / exceptions / file_operation_lock / middleware / path_resolver / search / security / tools）联跑
- ruff 错误数从 11 增加到 11（**0 净增**）
- ADR-010 验证：0 个 `backend.*` / `deerflow.*` / `app.*` 导入
- `backend/` 全程未触碰

### 下一批

5.7 仍需做：
- 与 backend `sandbox/tools.py`（1582 行）的字节级对齐（adversarial 体检）
- 边界情况补强：custom-mount 严格拒绝、skills 写路径严格拒绝、UNC 路径、Windows 斜杠漂移
- 工具 description brand-neutral 化（剥离 DeerFlow 业务文案）

详见 `progress.md` 阶段 5.7 段落。

---

## 2026-07-06：阶段 5.5 体检（10 个真问题 → 修复）

### 范围

1 个 adversarial subagent 对 5.5 新增的 12 个源 + 9 个测试 + 链装配改动 + summarization 改动做了接口对齐检查，输出 19 个差异点。**经核实后修复 10 个真问题**，撤销 9 个（撤销原因：3 个是 subagent 误判，6 个是 cosmetic / 不在 5.5 范围）。

### 修复 10 个真问题

#### BLOCKER（2 个）

1. **`skill_rescue_partitioner` 消息顺序违反 OpenAI tool 协议**（`agent_sdk/middlewares/summarization.py:186-189`）—— 修复前发出 `[ToolMessage, AIMessage]`，**OpenAI 400 拒绝**。修复后发出 `[AIMessage, ToolMessage]`（recent-first AIMessage 列表 → recent-first ToolMessage 列表）。同步更新 `tests/middlewares/test_summarization.py` 中两处 rescue 测试断言（`preserved[0] is ToolMessage` → `preserved[0] is AIMessage`）。
2. **`skill_rescue_partitioner` 只看 `tool_calls[0]`**（`agent_sdk/middlewares/summarization.py:164`）—— 多 tool_call AIMessage（如 `[{bash}, {read_skill}]`）的 skill 漏救。修复后遍历**所有** tool_calls 找 skill 集合。同步新增回归测试 `test_rescues_skill_when_first_tool_call_is_not_skill`。

#### HIGH（2 个）

3. **`build_server_params` 缺 `args` key**（`agent_sdk/mcp/client.py:41-42`）—— 之前 `if config.args is not None: params["args"] = config.args`，None 时缺 key，`langchain-mcp-adapters` KeyError。修复后 `params["args"] = list(config.args)`（永远设置）。
4. **`McpServerConfig` `args/env/headers` 默认 None**（`agent_sdk/mcp/config.py:39-42`）—— 之前 `None`，对后端 `default_factory=list/dict` 漂移。修复后 `Field(default_factory=list/dict)`。

#### MEDIUM（1 个）

5. **`McpServerConfig.type` Literal 限制过紧**（`agent_sdk/mcp/config.py:37`）—— 之前 `Literal["stdio","sse","http"] | None`，新 transport（如 `"streamable-http"`）在 config 加载时就 ValidationError，**不友好**。修复后 `str = "stdio"`（对齐 backend 行为；未知 transport 在 `build_server_params` 时抛清晰 ValueError）。

#### LOW（5 个）

6. **`SKILL_FILE_NAME` 死代码**（`agent_sdk/skills/manager.py:20-21`）—— 第一行 `SKILL_FILE_NAME = "SKILL_FILE_NAME"` 立即被第二行覆盖。删第一行。
7. **`SkillsMiddleware._signature` 死代码 + SHA-1**（`agent_sdk/skills/middleware.py:89-94`）—— 函数定义但从未被调用；同时用 SHA-1 触 FIPS 模式系统失败。删整个 `_signature` 方法 + 删 `hashlib` import。
8. **`SkillsMiddlewareState` 死 state_schema slot**（`agent_sdk/skills/middleware.py:42-45`）—— 声明 `skills_prompt: str | None` 但 middleware 永远不读写。删整个 class，middleware 改用基类 `AgentMiddleware[AgentState]`。
9. **`get_custom_skill_history_file` / `get_custom_skill_history_dir` 范围外 + 副作用**（`agent_sdk/skills/manager.py:87-96`）—— 5.5 范围不含 skills/installer.py（5.x follow-up），但函数已定义；`docstring` 撒谎说"不检查存在"实际 `mkdir`。删两个函数 + 删 `HISTORY_FILE_NAME` / `HISTORY_DIR_NAME` 常量。
10. **`test_features.test_default_features_in_5_6` 漏 `skills` 断言**（`tests/runtime/test_features.py:85`）—— 未来 skills default 翻 True 没测试会抓到。加 `skills` 到循环列表。

### 撤销 9 个 subagent 报告（不修）

- **HIGH-3**（rescued pairs recent-first vs oldest-first）—— **撤销**。设计选择：rescued pairs 紧跟 summary，recent-first 是有意的（与最新对话最相关）。**这是 subagent 误判**。
- **MEDIUM-6**（`description` 字段被丢）—— **撤销**。5.5 范围不含 admin UI / description 字段，plan doc 显式 OAuth/interceptors 才是 5.5 范围。
- **MEDIUM-7**（AIMessage 跨 cutoff 边界）—— **撤销**。这种情况 ToolMessage 已在 preserve 半不需要救，**不是 bug 是正确行为**。
- **LOW-4**（duplicate tool_call_id overwrites）—— **撤销**。Malformed input 不在正常路径。
- **LOW-6**（partitioner 类型用裸 `list`）—— **撤销**。Type hint 不影响运行时。
- **LOW-7**（`list_mcp_tool_names` 名字误导）—— **撤销**。Docstring 已说明。
- **LOW-8**（SHA-1 已通过 LOW-7 修复）
- **LOW-9**（`%` style logging）—— **撤销**。style drift not defect。

### 质量验证

- **pytest 842/842 通过**（3.76s；净增 2：1 个 BLOCKER-2 回归 + 1 个 collections 测试）
- **ruff: All checks passed**
- **ADR-010: 0 个 backend/deerflow/app 导入**
- **backend/ 全程未触碰**

## 2026-07-06：阶段 5.5 完成（集成子系统：Skills / MCP / Guardrails + skill rescue）

### 范围

5.5 完整实现 3 个集成子系统（**Skills / MCP / Guardrails middleware**），同时解决 5.8 体检遗留的 3 个 MEDIUM/HIGH 问题（`skill_rescue_partitioner` / `SkillsMiddleware` / `GuardrailMiddleware`）。

### 新增模块

#### 1. `agent_sdk/skills/`（5 文件，5 个测试文件）

- `types.py` - `Skill` dataclass（容器路径助手 + compact `__repr__`）
- `parser.py` - `parse_skill_file()`（YAML front-matter 解析，依赖 `pyyaml`）
- `loader.py` - `load_skills(skills_path, ...)`（扫描 `public/` + `custom/`，支持 `is_enabled` 回调 / `enabled_names` 集合 / `enabled_only` 过滤）
- `manager.py` - 路径助手（`get_custom_skill_dir` / `validate_skill_name` / `ensure_safe_support_path`） + `ALLOWED_SUPPORT_SUBDIRS`
- `middleware.py` - `SkillsMiddleware`（`before_model` 注入 `<available_skills>` 块；缓存 + `invalidate_cache()`；幂等 — 已包含 block 不重复注入）

#### 2. `agent_sdk/mcp/`（3 文件，3 个测试文件）

- `config.py` - `McpServerConfig` / `McpServersConfig` Pydantic（`type` Literal 校验 stdio/sse/http）+ `config_from_extensions_dict()`
- `client.py` - `build_server_params()` / `build_servers_config()`（**纯函数**，无 I/O）
- `tools.py` - `get_mcp_tools(servers)` async + `list_mcp_tool_names()`；懒加载 `langchain-mcp-adapters`（**未装时返回 `[]` + warn**）

#### 3. `agent_sdk/guardrails/middleware.py`（5.3 收尾）

- `GuardrailMiddleware(provider, *, fail_closed=True, passport=None)` — 包装 `GuardrailProvider`；同步/异步路径都支持
- `GraphBubbleUp` 透传以保留 langgraph 控制流

### 解决 5.8 体检遗留

| 5.8 报告 | 5.5 修复 |
|----------|----------|
| HIGH-3（`sandbox default=False`） | ✅ 已在 5.8 修复 |
| MEDIUM-6（`view_image` `state_schema` 缺） | 仍遗留（5.x follow-up） |
| MEDIUM-15（sync `invoke` 崩） | ✅ 已在 5.8 修复 |
| MEDIUM-19（`default_partitioner` 无 skill rescue） | ✅ **5.5** 新增 `skill_rescue_partitioner()` 工厂；通过 `MiddlewareChainConfig.summarization_partitioner` 注入 |
| HIGH-5（`ask_clarification` 签名） | ✅ 已在 5.8 修复 |
| MEDIUM-26（`is_valid_thread_id` 允许点号） | ✅ 已在 5.8 修复 |

### 链装配扩展

`MiddlewareChainConfig` 新增 4 个字段：
- `summarization_partitioner: Callable | None` — 注入自定义 partitioner
- `guardrail_provider: GuardrailProvider | None` — 让 `features.guardrail=True` 走 Provider 包装
- `skills_path: Path | None` — 让 `features.skills=True` 走 `SkillsMiddleware`
- `skills_container_base_path: str = "/mnt/skills"` — 虚拟前缀

`RuntimeFeatures` 新增：
- `skills: Literal[False] | AgentMiddleware = False` — 与 guardrail 平行
- `guardrail: bool | AgentMiddleware`（**从 `Literal[False]` 放宽到 `bool`** — 5.8 体检时已发现）让 `True` + Provider 即可工作

`assemble_chain` 新增 `_build_skills()` + 改写 `_build_guardrail()` / `_build_summarization()` 接受新注入。

### 测试

5 个新增测试文件（types / parser / loader / manager / middleware for skills；config / client / tools for mcp；middleware for guardrails）+ 3 个 chain 集成 + 4 个 summarization skill rescue：
- **152 个 5.5 测试通过**（5.5 子集）
- **840/840 全测通过**（3.73s；累计净增 87）

### 设计决策

- **`langchain-mcp-adapters` 是可选依赖**——没装时 `get_mcp_tools` 返回 `[]` + warn，**不 raise**。完整 OAuth / Interceptor / 跨进程 sync wrapper 留 5.x follow-up（与 auth 子系统强耦合）
- **`skill_rescue_partitioner` 是工厂而非函数** — 接受 `skill_tool_names` + `max_preserved_skills` 参数，返回可注入的 partitioner。**SDK 品牌无关**（不假设"什么是 skill"），DeerFlow preset 在 5.7 / 阶段 4 可以 `skill_rescue_partitioner({"read_skill"})` 注入
- **Skills / Guardrails 链装配** 用 `True` 走内置 + Provider 注入，**用 instance 跳过工厂** —— 两套路径，调用方灵活
- **`mcp_servers` 与 `mcpServers` 双别名** 兼容 backend 的 kebab-case 风格
- **Pydantic 校验 type Literal** —— 错误的 transport 在 config 层就 fail，**不进 `build_server_params` 路径**

### 质量验证

- **pytest 840/840 通过**（3.73s）
- **ruff check: All checks passed**
- **ADR-010: 0 个 backend/deerflow/app 导入**
- **backend/ 全程未触碰**

### 更新文档

- `docs/04-specs/module-tour.md` - 新增 §1.7.5 Skills / §1.7.6 MCP / 补 guardrails middleware / 补 summarization skill rescue / 补 chain 集成 / 删 §6 已解决项
- `docs/03-status/progress.md` - 工作日志 + 统计从 80/92 (87%) 升到 90/92 (98%)

## 2026-07-06：阶段 5 体检（5.3 / 5.4 / 5.6 / 5.8 接口对齐 + 4 个修复）

### 范围

adversarial subagent 对 5.3 / 5.4 / 5.6 / 5.8 的 30+ 核心文件做了接口对齐检查（SDK ↔ backend `make_lead_agent` + `agents/middlewares/*_middleware.py` + `runtime/{user_context,stream_bridge,checkpointer,store}` + `sandbox/*` + `guardrails/*`），共发现 25 个差异点。**经核实后修复 4 个真问题**，其余 21 个要么是 plan 显式声明的"first-cut omission"（5.7 范围）、要么是 SDK 故意做的设计选择（如 `FileMemoryStorage(file_path=...)` 把 user 隔离外置到 `PathProvider`），均记录在 changelog 不修。

### 修复 4 项

1. **HIGH-3：兑现 docstring 承诺**——`RuntimeFeatures.sandbox` 默认值从 `False` 翻到 `True`，与 backend `create_deerflow_agent` 一致。涉及文件：
   - `agent_sdk/runtime/features.py:70`（`sandbox: bool | AgentMiddleware = True`）
   - docstring "stage 5.6 the default will flip to True" 兑现
   - 同步更新 12+ 个依赖 default 的测试（`test_features.py`, `test_entry.py`, `test_middleware_chain.py`），加 `sandbox=False` 保留原意

2. **HIGH-5：ask_clarification 补参数**——`agent_sdk/tools/ask_clarification.py` 加 `clarification_type: Literal[...]` + `context: str | None` + `options: list[str] | None`，加 `return_direct=True`。与 backend `deerflow.tools.builtins.clarification_tool.ask_clarification_tool` signature 字节级一致（backend 是 5 个 Literal 值，SDK 同步对齐）。

3. **MEDIUM-26：收紧 `is_valid_thread_id`**——`agent_sdk/runtime/langgraph_integration.py:157` regex 去掉点号，与 backend `deerflow.config.paths._SAFE_THREAD_ID_RE` (`^[A-Za-z0-9_\-]+$`) 一致。理由：跨 SDK/backend 共享持久化时，thread_id 必须两边都校验通过。同步把 2 个测点（`user.42`, `a-b.c_d`）从 valid 列表移到新的 `test_dot_is_rejected`。

4. **MEDIUM-15：删 `SummarizationMiddleware` sync `_summarise` 路径**——`agent_sdk/middlewares/summarization.py` 删除 `_summarise` 和 sync 版本的 `_maybe_summarise` 业务逻辑，sync 路径改为 `return None`（异步路径 `_amaybe_summarise` 保留）。理由：sync `model.invoke(...)` 在 async 上下文里会死锁（chat model 把 async 路径包到 `asyncio.run`），与 backend 只暴露 async 一致。同步改 4 个测试从 sync → async 化（`test_async_path_returns_replace_messages_update`, `test_hook_fires_before_summarisation`, `test_hook_exception_is_swallowed`, `test_custom_partitioner_called`），新增 2 个 sync 行为断言（`test_sync_path_is_no_op`, `test_sync_path_uses_invoke`）。

### 撤销 / 接受 21 个

- **HIGH-4（MemoryStorage 缺 agent_name/user_id kwargs）**：撤销。SDK 的 `FileMemoryStorage(file_path, schema_cls)` 把 user 隔离外置到 `PathProvider`，是更 clean 的抽象；plan 显式说过"brand-neutral"。
- **HIGH-6（CheckpointerConfig type 默认 "memory"）**：撤销（接受为工程决策）。后端是 required，SDK 给 default "memory" 让零配置即可跑——记录进 changelog 不修。
- **BLOCKER-1/2/3（view_image / task / memory_middleware 是 stub）**：3 个全部坐实但**全部 blocked by 5.7**（依赖 sandbox 工具和 SubagentExecutor 等下游模块），划入 5.7 / 5.x 后续批次范围。
- **MEDIUM-1/6/19（loop detection read_file 分桶 / view_image state_schema / default_partitioner 无 skill rescue）**：划入 5.5（集成子系统）和 5.7（sandbox 工具）范围。
- **MEDIUM-2/4/7-15/17/22-28（其余 16 个 MEDIUM/LOW）**：plan 显式 first-cut omission / 命名漂移（`missing_id` vs `missing_tool_call_id`） / 不影响主流程的边界情况，记入 changelog 不修。

### 质量验证

- **pytest：753/753 通过**（3.48s）—— 修复后净增 4 个测试
- **ruff check：All checks passed**
- **ADR-010：0 个 `backend.*` / `deerflow.*` / `app.*` 导入**
- **backend/ 全程未触碰**（git status clean）

## 2026-07-06：阶段 5 第五批完成（5.8 middleware 链装配）

### 范围

- `agent_sdk/runtime/middleware_chain.py` - `MiddlewareChainConfig` dataclass + `assemble_chain()` 函数 + `_insert_extra_middlewares()` 辅助
- 17 个 middleware 全部按 backend 顺序装配（ThreadData → Uploads → Sandbox → DanglingToolCall → LLMErrorHandling → Guardrail → SandboxAudit → ToolErrorHandling → Summarization → TodoList → TokenUsage → Title → Memory → ViewImage → DeferredToolFilter → SubagentLimit → LoopDetection → Clarification）
- `entry.py` 接受 `l2_config: MiddlewareChainConfig | None` + `plan_mode: bool`；L2 特性依赖通过 `l2_config` 注入，缺依赖抛清晰 `ValueError`
- 保留 5.1-era shim（`_assemble_from_features` / `_insert_extra`）向后兼容

### 设计要点

- **运行时依赖全部通过 `MiddlewareChainConfig` 注入**（不读全局 config）：`path_provider` / `sandbox_provider` / `audit_rules` / `title_model_factory` / `summarization_model` / `memory_schema_cls` / `memory_storage` / `guardrail_provider`
- **缺依赖给清晰错误**：`RuntimeFeatures.sandbox=True` 但 `l2_config.path_provider=None` → `ValueError("... requires MiddlewareChainConfig.path_provider ...")` 指向缺失字段
- **Clarification 始终在最后**：`@Next(ClarificationMiddleware)` 的 extra middleware 在装配后被强制移到尾部
- **未锚定 extra middleware 默认插到 Clarification 之前**（而不是 append 到末尾），与 backend `make_lead_agent` 行为一致
- **向后兼容 shim**：`_assemble_from_features` / `_insert_extra` 仍可用（委托给 `assemble_chain` / `_insert_extra_middlewares`），已有 5.1 测试不破坏

### 17 个 middleware 装配顺序（按 backend `make_lead_agent` 顺序）

```
[0]  ThreadDataMiddleware            (sandbox)
[1]  UploadsMiddleware                (sandbox)
[2]  SandboxAuditMiddleware           (sandbox)
[3]  DanglingToolCallMiddleware       (always)
[4]  LLMErrorHandlingMiddleware       (always)
[5]  GuardrailMiddleware              (guardrail, optional)
[6]  ToolErrorHandlingMiddleware      (always)
[7]  SummarizationMiddleware          (summarization)
[8]  TodoMiddleware                   (plan_mode)
[9]  TokenUsageMiddleware            (always)
[10] TitleMiddleware                  (auto_title)
[11] MemoryMiddleware                 (memory)
[12] ViewImageMiddleware              (vision)
[13] DeferredToolFilterMiddleware     (always)
[14] SubagentLimitMiddleware          (subagent)
[15] LoopDetectionMiddleware          (always)
[16] ClarificationMiddleware          (always last)
```

### 测试（2 个测试文件 / 31 个新增用例）

- `tests/runtime/test_middleware_chain.py` - 28 个（默认链 / 顺序 / sandbox / subagent / vision / title / memory / summarization / plan_mode / Clarification 始终最后 / @Next/@Prev 插入 / 冲突检测 / 全部特性开启）
- `tests/runtime/test_entry.py` 扩展 - 3 个新增 L2 end-to-end 用例（l2_config 注入 / 缺依赖错误 / plan_mode）

### 质量验证

- pytest：**749/749 通过**（3.08s）—— 724（5.1+5.2+5.3+5.4+5.6 累计） + 25（5.8 新增 chain 测试）+ 3（entry.py 端到端扩展）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

## 2026-07-06：阶段 5 第四批完成（5.6 业务特性 middleware）

### 范围（9 个 L2 业务特性 middleware，全部重写）

全部位于 `sdk-extraction/harness/agent_sdk/`：

- `middlewares/subagent_limit.py` - `SubagentLimitMiddleware`：截断超过 `max_concurrent` 的 `task` tool calls；clamp 到 `[2, 4]`（与 backend `MAX_CONCURRENT_SUBAGENTS` 对齐）
- `middlewares/thread_data.py` - `ThreadDataMiddleware`：填充 `thread_data` slot；接受 `PathProvider` 注入；支持 `lazy_init`；为最后 human message 注入 `run_id` / `timestamp` metadata
- `middlewares/uploads.py` - `UploadsMiddleware`：从 `message.additional_kwargs.files` 抽取文件元信息；构造 `<uploaded_files>` 块；接受 `PathProvider` + `virtual_prefix` 注入；保留 multimodal content
- `sandbox/middleware.py` - `SandboxMiddleware`：使用 5.3 的 `SandboxProvider` 抽象；`lazy_init` 支持；before_agent acquire / after_agent release
- `middlewares/view_image.py` - `ViewImageMiddleware`：检测 `view_image` 工具调用完成后注入图片细节 HumanMessage；idempotent 防重复注入；清空 `viewed_images` reducer
- `middlewares/title.py` - `TitleMiddleware` + `TitlePrompts` + `TitleModelFactory` Protocol：第一轮后自动生成 title；sync 走本地 fallback；async 走 LLM + fallback
- `middlewares/clarification.py` - `ClarificationMiddleware`：拦截 `ask_clarification` 工具调用；返回 `Command(goto=END)` 中断；支持中英文图标 + 多种 `clarification_type` 图标
- `middlewares/llm_error.py` - `LLMErrorHandlingMiddleware` + `RetryConfig` + `CircuitBreakerConfig`：retry + 指数退避 + 熔断器 + retry-after 头解析 + 流式 `llm_retry` 事件；业务关键词模式（quota/auth/busy/transient）
- `middlewares/summarization.py` - `SummarizationMiddleware` + `BeforeSummarizationHook` Protocol + `SummarizationEvent` 数据类：标准 token trigger + keep 策略；支持自定义 `message_partitioner` 实现 skill rescue；hook 异常隔离

### 导出更新

- `agent_sdk/middlewares/__init__.py` 导出 9 个新 middleware + 数据类（`CircuitBreakerConfig` / `RetryConfig` / `TitlePrompts` / `BeforeSummarizationHook` / `SummarizationEvent` / `TitleModelFactory`）
- `agent_sdk/sandbox/__init__.py` 导出 `SandboxMiddleware` / `SandboxMiddlewareState`

### 设计要点

- **统一 PathProvider 注入**：`ThreadDataMiddleware` / `UploadsMiddleware` / `SandboxMiddleware` 全部通过 `PathProvider` 接口获取路径，不读全局 config
- **runtime=None 友好**：`SummarizationMiddleware` 的 `_resolve_thread_id` / `_resolve_agent_name` 接受 `runtime=None`（单元测试场景）
- **业务假设剥离**：`SummarizationMiddleware` 不内嵌 skill rescue，而是提供 `message_partitioner` 注入点，DeerFlow preset 接入
- **circuit breaker 半开状态**：`half_open` 状态只允许一个 probe 飞行中；half_open probe 失败重新打开
- **hook 异常隔离**：`BeforeSummarizationHook` / `clarification` 异常被 catch + log，不影响主流程
- **multimodal content 保留**：`UploadsMiddleware` 同时支持 string 和 list[dict] 两种 content 形状
- **idempotent view_image**：用 `Here are the images you've viewed` 标记字符串防重复注入

### 测试（9 个测试文件 / 112 个用例）

- `tests/middlewares/test_subagent_limit.py` - 16 个
- `tests/middlewares/test_thread_data.py` - 5 个
- `tests/middlewares/test_uploads.py` - 8 个
- `tests/sandbox/test_middleware.py` - 7 个
- `tests/middlewares/test_view_image.py` - 7 个
- `tests/middlewares/test_title.py` - 16 个
- `tests/middlewares/test_clarification.py` - 13 个
- `tests/middlewares/test_llm_error.py` - 23 个
- `tests/middlewares/test_summarization.py` - 13 个

### 质量验证

- pytest：**724/724 通过**（2.93s）—— 612（5.1+5.2+5.3+5.4 累计） + 112（5.6 新增）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

## 2026-07-06：阶段 5 第三批完成（5.4 运行时基础设施）

### 范围（用户已确认：完整范围）

8 个新模块，跨 7 个子包：
- `agent_sdk/reflection/` - `resolve_class` / `resolve_variable`（泛型，依赖提示，3 个新包名 hint）
- `agent_sdk/utils/network.py` - `PortAllocator` + `get_free_port` / `release_port`（线程安全，0.0.0.0 绑定）
- `agent_sdk/runtime/langgraph_integration.py` - `make_thread_config` / `merge_configs` / `make_run_id` / `is_valid_thread_id` + configurable key 常量 + stream mode 常量
- `agent_sdk/runtime/checkpointer/` - 3 后端（memory/sqlite/postgres）的 sync 单例 + sync context manager + async context manager；懒加载 sqlite/postgres extras
- `agent_sdk/runtime/store/` - 3 后端的 async context manager（与 checkpointer 独立）
- `agent_sdk/models/factory.py` - `ModelConfig` pydantic data class + `create_chat_model()` 工厂（thinking 切换 / stream_usage 默认 / tracing callback 附加）
- `agent_sdk/tools/loader.py` - `ToolConfig` + `load_tools()` + `LoadResult`（按 class path 加载 + dedupe + group 过滤 + name mismatch 警告）
- `agent_sdk/tracing/factory.py` - `TracingConfig` / `LangSmithConfig` / `LangfuseConfig` + `build_tracing_callbacks()`（懒加载，缺依赖 WARNING/raise 可选）

### 设计要点

- **postgres 连接串校验先于 import**：在 factory 中先校验 `connection_string` 非空，再尝试 import 后端包，让用户先看到清晰的 "missing connection string" 错误而不是 import 错误
- **lazy import 模式**：sqlite/postgres extras 在 factory 内 `try import`，缺包时抛 `ImportError` 携带可操作的 `uv add ...` 提示
- **Tracing 软失败**：`build_tracing_callbacks()` 默认 WARNING 跳过失败的 provider（生产环境不因单个 tracing provider 故障导致模型不可用），可通过 `raise_on_missing=True` 切换到硬失败
- **Loader 顺序保留**：`config → builtin → extra`；按出现顺序 dedupe，重复名记录在 `LoadResult.skipped_duplicates`
- **reflection 用 `re.escape` 友好提示**：`MODULE_TO_PACKAGE_HINTS` 含 11 个已知 langchain/langfuse 包，把缺失依赖翻译成 `uv add langchain-anthropic` 等可操作命令

### 测试（8 个测试文件 / 135 个用例）

- `tests/test_reflection.py` - 17 个（resolve_variable + resolve_class + 错误消息 + 提示）
- `tests/utils/test_network.py` - 11 个（PortAllocator + 模块级 + 线程安全）
- `tests/runtime/test_langgraph_integration.py` - 28 个（configurable key + make_thread_config + merge_configs + make_run_id + is_valid_thread_id + stream modes）
- `tests/runtime/test_checkpointer.py` - 21 个（Config + sync 单例 + sync CM + async CM + 所有后端 import 错误）
- `tests/runtime/test_store.py` - 8 个（async CM + InMemoryStore 端到端 + 所有后端 import 错误）
- `tests/test_models.py` - 14 个（ModelConfig + create_chat_model + thinking 切换 + stream_usage + tracing + kwargs override）
- `tests/test_tools_loader.py` - 14 个（ToolConfig + load_tools + group + dedupe + name mismatch + 错误）
- `tests/test_tracing.py` - 15 个（配置 dataclass + build_tracing_callbacks + 软/硬失败 + provider 顺序）

### 质量验证

- pytest：**612/612 通过**（2.46s）—— 477（5.1+5.2+5.3 累计） + 135（5.4 新增）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

## 2026-07-06：阶段 5 第二批完成（5.3 抽象 ABC）

### 完成内容

- `agent_sdk/sandbox/base.py` - `Sandbox` / `SandboxProvider` ABC + `GrepMatch` 数据类
- `agent_sdk/runtime/user_context.py` - `CurrentUser` Protocol + `ContextVar` 绑定 + `AUTO` sentinel + `resolve_user_id` 三态解析 + `get_effective_user_id` / `require_current_user` 帮助函数 + `DEFAULT_USER_ID = "default"`
- `agent_sdk/runtime/stream_bridge.py` - `StreamBridge` ABC + `StreamEvent` frozen dataclass + `HEARTBEAT_SENTINEL` / `END_SENTINEL` 哨兵
- `agent_sdk/guardrails/` - 新子包（`provider.py` + `builtin.py` + `__init__.py`）
  - `GuardrailRequest` / `GuardrailReason` / `GuardrailDecision` 数据类
  - `GuardrailProvider` Protocol（`@runtime_checkable`）
  - `AllowlistProvider` 参考实现（allowlist / denylist 双重检查 + async delegate）
- `agent_sdk/sandbox/__init__.py` - 更新导出 `Sandbox` / `SandboxProvider` / `GrepMatch`
- `agent_sdk/runtime/__init__.py` - 更新导出 user_context + stream_bridge symbols

### 测试（4 个测试文件 / 84 个用例）

- `tests/sandbox/test_base.py` - 19 个（GrepMatch + Sandbox ABC + SandboxProvider ABC + integration）
- `tests/runtime/test_user_context.py` - 22 个（Protocol + ContextVar 绑定 + sentinel + resolve_user_id 三态）
- `tests/runtime/test_stream_bridge.py` - 20 个（StreamEvent + sentinels + ABC + 子类）
- `tests/guardrails/test_provider.py` - 23 个（data classes + Protocol + AllowlistProvider 行为）

### 工程改进

- `pyproject.toml` - 添加最小依赖 `langchain>=0.6` / `langgraph>=0.6` / `pydantic>=2.0`（之前是注释占位）
- `pyproject.toml` - 添加 `[dependency-groups] dev` 段（pytest / pytest-asyncio / ruff）
- `pyproject.toml` - 添加 `[tool.pytest.ini_options]`（`asyncio_mode = "auto"` + `testpaths`）

### 质量验证

- pytest：**477/477 通过**（2.13s）—— 393（5.1+5.2 累计） + 84（5.3 新增）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

## 2026-07-06：阶段 5 第一批完成（SDK 入口 + 5 个通用 middleware）

### 推进顺序写入文档（上午）

**问题**：阶段 5 是 3 周规模（10 个子任务），单次会话无法完成。

**新推进顺序**：`5.1 + 5.2 第一批 → 5.3 → 5.4 → 5.6 → 5.8 → 5.5 → 5.7 → 4 → 6 → 7`

**新增文档**：
- `phase-5-batch-1.md` - 阶段 5 第一批详细计划（5.1 + 5.2）

**理由**：
- 5.1 是 SDK 骨架入口（`create_agent` / `RuntimeFeatures` / `@Next` / `@Prev` / `ThreadState`）
- 5.2 是 L3 纯通用 middleware（5 个，无业务假设）
- 这两个是后续 5.3+ 的基础

### 阶段 5 第一批（5.1 + 5.2）✅ 已完成

**新增 SDK 模块**（全部在 `sdk-extraction/harness/agent_sdk/`）：
- `runtime/__init__.py` - runtime 子包导出（Next / Prev / RuntimeFeatures / ThreadState / create_agent）
- `runtime/features.py` - `RuntimeFeatures` 数据类（7 字段：sandbox / memory / summarization / subagent / vision / auto_title / guardrail）
- `runtime/decorators.py` - `@Next` / `@Prev` 装饰器（设置类属性 + 校验 anchor 类型）
- `runtime/thread_state.py` - `ThreadState` + `SandboxState` + `ThreadDataState` + `ViewedImageData` TypedDict + `merge_artifacts` / `merge_viewed_images` reducer（**与 backend 行为一致**）
- `runtime/entry.py` - `create_agent()` 入口（参数验证、`_assemble_from_features`、`_insert_extra` 装配逻辑；L2 特性 raise NotImplementedError）
- `__init__.py` - 顶层导出更新
- `middlewares/dangling_tool_call.py` - `DanglingToolCallMiddleware`（**L3 纯通用，行为与 backend 字节级一致**）
- `middlewares/tool_error_handling.py` - `ToolErrorHandlingMiddleware`（500 字截断 + GraphBubbleUp 透传 + 错误格式）
- `middlewares/token_usage.py` - `TokenUsageMiddleware`（只读观测）
- `middlewares/loop_detection.py` - `LoopDetectionMiddleware`（hash + 频率双重检测 + LRU eviction + reset；**与 backend 行为字节级一致**）
- `middlewares/deferred_tool_filter.py` - `DeferredToolFilterMiddleware`（deferred_names_provider 注入，无 provider 时 no-op）
- `middlewares/__init__.py` - 5 个新 middleware + todo 子包导出

**新增测试**（9 个测试文件 / 134 个用例）：
- `tests/runtime/test_features.py` - 17 个（默认值、契约、`is_enabled`）
- `tests/runtime/test_decorators.py` - 7 个（@Next / @Prev 行为 + 校验）
- `tests/runtime/test_thread_state.py` - 15 个（reducers + ThreadState 形状 + TypedDict 子类型）
- `tests/runtime/test_entry.py` - 30 个（参数验证、L2 拒绝、L3 装配、@Next/@Prev 插入、create_agent 端到端、跨外部锚点迭代解决）
- `tests/middlewares/test_dangling_tool_call.py` - 13 个（结构化 tool_calls、legacy kwargs、修复插入位置、async）
- `tests/middlewares/test_tool_error_handling.py` - 12 个（异常转 ToolMessage、500 字截断、GraphBubbleUp 透传、Command 透传、async）
- `tests/middlewares/test_token_usage.py` - 6 个（usage 记录 / 无 usage 不记录 / zero 记录 / async 一致性）
- `tests/middlewares/test_loop_detection.py` - 21 个（hash 稳定性、订单无关、警告去重、硬停止 + finish_reason 翻转、tool_freq 警告/硬停止、线程隔离、LRU eviction、reset）
- `tests/middlewares/test_deferred_tool_filter.py` - 13 个（无 provider / 空 provider / 模型侧过滤 / 工具侧阻断 / async）

**质量验证**：
- pytest：阶段 1+2+3+5.1+5.2 累计 **393/393 通过**（1.89s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 决策
- 无新 ADR（沿用 ADR-010 抽离策略）

### 状态
- **阶段 0**：✅ 已完成
- **阶段 1**：✅ 已完成
- **阶段 2**：✅ 已完成
- **阶段 3**：✅ 已完成
- **阶段 5 第一批（5.1 + 5.2）**：✅ 已完成
- **阶段 5 后续批次（5.3-5.8）**：⏳ 待开始
- **阶段 4 / 6 / 7**：⏳ 待开始

---

## 2026-07-06：阶段 3 完成（Audit / Prompt 抽象）

### 阶段 3：Audit / Prompt 抽象 ✅ 已完成

**新增 SDK 模块**（全部在 `sdk-extraction/harness/agent_sdk/`）：
- `sandbox/__init__.py` - 导出 AuditPattern / AuditRules / AuditVerdict / DefaultAuditRules / SandboxAuditMiddleware
- `sandbox/audit/__init__.py` - audit 子包导出
- `sandbox/audit/rules.py` - `AuditPattern` 数据类（frozen，risk_level 校验）、`AuditVerdict` 枚举（BLOCK / WARN / PASS 字符串值即 wire format）、`AuditRules` Protocol（@runtime_checkable，三个 get_*_patterns 方法）
- `sandbox/audit/default.py` - `DefaultAuditRules`（空规则，便于新项目直接使用）
- `sandbox/audit/middleware.py` - `SandboxAuditMiddleware`：构造参数 `audit_rules: AuditRules | None = None`（默认 DefaultAuditRules）和 `tool_name: str = "bash"`；完整保留 compound command 拆分（quote-aware）、shlex 回退、fail-closed unclosed quotes、input 校验（empty / 10000 chars / null byte）、audit log、sync `wrap_tool_call` + async `awrap_tool_call`；block 返回 error ToolMessage，warn 追加警告到 tool result
- `middlewares/__init__.py` - 导出 todo 子包
- `middlewares/todo/__init__.py` - todo 子包导出
- `middlewares/todo/prompts.py` - `TodoPrompts` 数据类（frozen）+ brand-neutral `DEFAULT_TODO_SYSTEM_PROMPT` / `DEFAULT_TODO_TOOL_DESCRIPTION` + `TodoPrompts.default()` 工厂
- `middlewares/todo/middleware.py` - `TodoMiddleware`：继承 langchain `TodoListMiddleware`；构造参数 `prompts: TodoPrompts | None` 和 `tool_name: str = "write_todos"`；保留 `before_model`（context-loss 检测，注入 `todo_reminder` HumanMessage）、`after_model`（premature-exit 预防 + retry cap = 2，注入 `todo_completion_reminder` + `jump_to: "model"`）、async 对应方法
- `presets/deerflow/audit.py` - `DeerFlowAuditRules`（**15 条 high-risk + 5 条 medium-risk 重新录入**，与 backend 行为字节级一致）
- `presets/deerflow/prompts/__init__.py` - prompts 子包导出
- `presets/deerflow/prompts/todo.py` - `DEERFLOW_TODO_SYSTEM_PROMPT` / `DEERFLOW_TODO_TOOL_DESCRIPTION` / `DEERFLOW_TODO_PROMPTS`（**与 backend 字节级一致**，包括"sessions.  Only"的双空格）
- `presets/deerflow/__init__.py` - 导出新增 preset

**新增测试**（6 个测试文件 / 90 个测试）：
- `tests/sandbox/audit/test_rules.py` - 13 个测试（AuditVerdict 字符串值、AuditPattern frozen + 风险级别校验、AuditRules Protocol 满足性）
- `tests/sandbox/audit/test_classification.py` - 23 个测试（_split_compound_command quote-aware 拆分 + unclosed quote fail-closed、_classify_command 三个 verb 决策 + compound worst-wins）
- `tests/sandbox/audit/test_middleware.py` - 18 个测试（wrap_tool_call / awrap_tool_call 全路径：非目标 tool 透传 / 安全命令 / 高危阻断 / 中危警告 / 空命令 / null byte / 超长 / custom tool_name / compound 阻断 / tool_call_id 保留 / thread_id 出现在 log）
- `tests/middlewares/todo/test_prompts.py` - 9 个测试（DEFAULT_* 包含 write_todos + 3 steps、TodoPrompts frozen + equality、brand-neutral 验证）
- `tests/middlewares/todo/test_middleware.py` - 16 个测试（构造 / prompts 注入 / 默认 tool_name / before_model 4 个分支 / after_model 5 个分支 / async 一致性）
- `tests/presets/deerflow/test_audit.py` - 36 个测试（结构 + 16 条 high-risk parametrized + 8 条 medium-risk parametrized + 3 个 middleware 集成）
- `tests/presets/deerflow/test_todo_prompts.py` - 9 个测试（系统 prompt 字节级等价 + 工具描述字节级等价 + 双空格保留 + 与 default 的差异验证 + 注入中间件）

**质量验证**：
- pytest：阶段 1+2+3 累计 **259/259 通过**（1.52s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 决策
- 无新 ADR（沿用 ADR-010 抽离策略）

### 状态
- **阶段 0**：✅ 已完成
- **阶段 1**：✅ 已完成
- **阶段 2**：✅ 已完成
- **阶段 3**：✅ 已完成
- **阶段 4-7**：⏳ 待开始

---

## 2026-07-06：阶段 2 完成 + 推进顺序重整

### 推进顺序写入文档（上午）

**问题**：检查 `phases.md` 发现原线性 5 阶段计划**没有 L3 通用层抽离阶段**——只提"5 个通用 middleware"但没有专门阶段。L3 是 SDK 的骨架，缺了它 SDK 只是个空壳。

**新推进顺序**：`0→1→2→3→5（L3）→4（Preset）→6（集成）→7（发布）`

**理由**：
- L3 通用层是 SDK 骨架，必须有专门阶段抽离
- Preset 需要 L3 通用层支撑（create_agent 入口、middleware 链装配、StreamBridge、LangGraph 集成）
- 顺序倒过来：先 L3 骨架（5），再做 Preset 打包（4），避免 Preset 阶段无法跑通

**新增文档**：
- `phases.md`：调整为 7 阶段结构
- `phase-5-l3-foundation.md`：L3 通用层抽离详细计划（create_agent + 18 个 middleware + ABC + LangGraph 集成 + MCP/Skills/Guardrails）
- `phase-6-integration.md`：端到端集成（L1/L2/L3 + preset 跑通）
- `phase-7-publishing.md`：原 `phase-5-verification.md` 内容拆出来（测试 + 发布）
- 原 `phase-5-verification.md` 已 `git mv` 为 `phase-7-publishing.md`

### 阶段 2：Memory / Subagent / Tools 数据模型抽象 ✅ 已完成（下午）

**新增 SDK 模块**（全部在 `sdk-extraction/harness/agent_sdk/`）：
- `memory/__init__.py` - 导出 MemorySchema、DefaultMemorySchema、MemoryStorage、MemoryMiddleware、MemoryUpdater
- `memory/schema.py` - `MemorySchema` Protocol（to_dict / from_dict / get_user_profile / get_conversation_history / empty）
- `memory/default.py` - `DefaultMemorySchema`（无业务假设）
- `memory/storage.py` - `MemoryStorage(ABC, Generic[T])` + `FileMemoryStorage`
- `memory/middleware.py` - `MemoryMiddleware`（注入 MemorySchema，stage 5 替换为完整 LLM 抽取）
- `memory/updater.py` - `MemoryUpdater`（持久化路径完整；stage 5 加 LLM 抽取）
- `subagents/__init__.py` - 导出 SubagentDefinition、SubagentRegistry、DefaultSubagentRegistry、SubagentExecutor
- `subagents/definition.py` - `SubagentDefinition` 数据类（与 backend SubagentConfig 字段对齐）
- `subagents/registry.py` - `SubagentRegistry` Protocol
- `subagents/default.py` - `DefaultSubagentRegistry`（空注册表）
- `subagents/executor.py` - `SubagentExecutor` stub（注入 Registry；stage 5 替换为完整 ThreadPool/timeout/trace）
- `tools/__init__.py` - 导出 6 个 factory
- `tools/factory.py` - factory 模式入口
- `tools/ask_clarification.py` / `present_files.py` / `view_image.py` / `task.py` / `setup_agent.py` / `invoke_acp_agent.py` - 6 个 builtin tool factory（每个接受 `tool_name: str` 参数）
- `presets/deerflow/memory.py` - `DeerFlowMemorySchema`（**与 backend `create_empty_memory()` 字节级一致**）
- `presets/deerflow/subagents.py` - `DeerFlowSubagentRegistry`（general-purpose / bash 角色重新录入）

**新增测试**（7 个测试文件 / 70 个测试）：
- `tests/memory/test_default.py` - 13 个测试（DefaultMemorySchema）
- `tests/memory/test_deerflow.py` - 13 个测试（DeerFlowMemorySchema 字节级对比）
- `tests/memory/test_storage.py` - 5 个测试（FileMemoryStorage）
- `tests/subagents/test_default.py` - 5 个测试（DefaultSubagentRegistry）
- `tests/subagents/test_deerflow.py` - 18 个测试（DeerFlowSubagentRegistry）
- `tests/subagents/test_executor.py` - 5 个测试（SubagentExecutor）
- `tests/tools/test_factory.py` - 13 个测试（6 个 factory × 默认名 + 自定义名 + 全部 DeferFlow 名一致性）

**质量验证**：
- pytest：阶段 1+2 累计 **135/135 通过**（1.39s）
- ruff check：**All checks passed**
- ADR-010 验证：0 处 import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 决策
- 无新 ADR（沿用 ADR-010 抽离策略）

### 状态
- **阶段 0**：✅ 已完成
- **阶段 1**：✅ 已完成
- **阶段 2**：✅ 已完成
- **阶段 3-7**：⏳ 待开始

---

## 2026-07-06：阶段 1 完成 + 规划文档审计修正

### 规划文档审计与修正（上午）

**问题发现**：系统性审计发现 9 份规划文档与 ADR-004（抽离期间不动 `backend/`）严重冲突。
- 阶段 1 计划：5 处冲突（"修改 sandbox/tools.py"、"修改 middleware 和 tool"等）
- 阶段 2 计划：5 处冲突（"修改 MemoryMiddleware / MemoryUpdater"等）
- 阶段 3 计划：6 处冲突（"修改 SandboxAuditMiddleware"、"修改 TodoMiddleware"等）
- 阶段 4 计划：12 处冲突（"迁移 builtin tools"、"迁移 middleware"等）
- 阶段 5 计划：2 处冲突
- `feature-inventory.md`：1 处语义冲突

**根因**：计划文档作者把"抽离"误解为"逐步替换 backend/ 代码"（Code Mover），而架构文档作者理解的是"在 SDK 内部镜像实现"（Re-implementation）。

**修正**：
- 修订 `phases.md` 总览：6 处冲突
- 修订 `phase-1-path-provider.md`：2 整段重写 + 3 处微调
- 修订 `phase-2-data-models.md`：4 整段重写 + 1 处微调
- 修订 `phase-3-audit-prompt.md`：2 整段重写 + 4 处微调
- 修订 `phase-4-deerflow-preset.md`：12 处改动（标题、目标、目录树、10 个任务）
- 修订 `phase-5-verification.md`：2 处微调
- 修订 `feature-inventory.md` section 11 语义

**新增决策**：
- **ADR-010**：抽离策略 = 重新实现（Re-implementation），不是代码搬运（Code Mover）
  - 禁止 `from backend.* / deerflow.* / app.* import ...`
  - 禁止复制粘贴 `backend/` 文件作为 SDK 源
  - 禁止修改 `backend/` 任何现有文件
  - SDK 内部可以使用离线录制的 golden fixture（不引用 `backend.*`）
  - 抽离 PR 边界：仅在 `sdk-extraction/` 内新增；DeerFlow 应用切换属于后续应用迁移 PR

### 阶段 1：PathProvider 抽象 ✅ 已完成（下午）

**新增 SDK 模块**（全部在 `sdk-extraction/harness/agent_sdk/`）：
- `paths/__init__.py` - 导出 PathProvider、DefaultPathProvider、VirtualPathResolver
- `paths/provider.py` - `PathProvider` Protocol（10 个方法）
- `paths/default.py` - `DefaultPathProvider`（无业务假设，默认 base = `./.agent-sdk`）
- `paths/resolver.py` - `VirtualPathResolver`（含 path-traversal 防护）
- `presets/deerflow/__init__.py` - DeerFlow preset 入口
- `presets/deerflow/paths.py` - `DeerFlowPathProvider`（保留 `/mnt/user-data` 行为）

**新增测试**（全部在 `sdk-extraction/harness/tests/`）：
- `conftest.py` - 包含 `_ImportBlocker` meta-path finder 阻止 `from backend.* / deerflow.* / app.*`
- `paths/test_provider.py` - 4 个测试（Protocol 契约）
- `paths/test_default.py` - 19 个测试（DefaultPathProvider）
- `paths/test_deerflow.py` - 20 个测试（DeerFlowPathProvider，含 golden snapshot）
- `paths/test_resolver.py` - 17 个测试（VirtualPathResolver，含 round-trip 测试）
- `integration/test_injectability.py` - 5 个测试（端到端注入验证）

**质量验证**：
- pytest：**65/65 通过**（0.59s）
- ruff check：**All checks passed**

**ADR-010 验证**：
- `grep` SDK 全部代码：**0 处** import `backend.*` / `deerflow.*` / `app.*`
- `backend/` **全程未触碰**

### 决策
- ADR-010: 抽离策略 = 重新实现（Re-implementation），不是代码搬运（Code Mover）

### 状态
- **阶段 0：脚手架** - ✅ 已完成
- **阶段 1：PathProvider 抽象** - ✅ 已完成
- **阶段 2-5**: ⏳ 待开始

---

## 2026-07-03：项目启动

### 新增
- 创建 `sdk-extraction/` 顶层目录
- 创建 `sdk-extraction/docs/` 子目录
  - `CLAUDE.md` - 引导文件
  - `README.md` - 项目说明
  - `00-vision/` - 愿景与目标
    - `goals.md` - 项目目标
    - `scope.md` - 范围
    - `non-goals.md` - 非目标
  - `01-design/` - 架构与边界设计
    - `architecture.md` - 三层分离架构
    - `sdk-boundary.md` - L1/L2/L3 重新定义
    - `feature-inventory.md` - SDK 特性清单
    - `protocols/README.md` - Protocol 设计索引
  - `02-plan/` - 阶段计划
    - `phases.md` - 阶段总览
    - `phase-1-path-provider.md` - 阶段 1 详细
    - `phase-2-data-models.md` - 阶段 2 详细
    - `phase-3-audit-prompt.md` - 阶段 3 详细
    - `phase-4-deerflow-preset.md` - 阶段 4 详细
    - `phase-5-verification.md` - 阶段 5 详细
  - `03-status/` - 状态跟踪
    - `progress.md` - 整体进度
    - `decisions.md` - 9 个 ADR（ADR-007 已撤回）
    - `blockers.md` - 阻塞跟踪（当前无阻塞）
    - `changelog.md` - 本文件
  - `04-specs/README.md` - 详细规格索引（待填充）
  - `05-archive/` - 历史分析文档
- 创建 `sdk-extraction/harness/` SDK 骨架（扁平布局）
  - `README.md` - SDK 简介
  - `pyproject.toml` - 包配置占位
  - `CHANGELOG.md` - 抽离过程
  - `agent_sdk/__init__.py` - 空包占位

### 调整
- SDK 包布局从 `agent/src/deerflow/` 改为 `agent/deerflow/`（扁平布局，无 `src/` 嵌套）
- SDK 包再次调整：`agent/deerflow/` → `agent/agent_sdk/`，包名 `deerflow-sdk` → `agent-sdk`
  - 物理结构：`agent/agent_sdk/__init__.py`（扁平布局）
  - PyPI 包名：`agent-sdk`
  - import 路径：`from agent_sdk import ...`
- 目录重命名：`agent/` → `harness/`（包名和 import 路径不变）
  - 当前结构：`sdk-extraction/harness/agent_sdk/__init__.py`
  - 物理目录名改为 `harness` 是为了与 DeerFlow `backend/packages/harness/deerflow` 的命名风格一致（harness 是包，deerflow 是其中的 SDK）

### 移动（复制）
- `backend/docs/HARNESS_PACKAGE_ANALYSIS.md` → `sdk-extraction/docs/05-archive/`
- `backend/docs/HARNESS_BUSINESS_COUPLING.md` → `sdk-extraction/docs/05-archive/`

### 决策
- ADR-001: SDK 定位为 "feature-rich + brand-neutral"
- ADR-002: L1/L2/L3 三层重新定义
- ADR-003: 阶段 1 优先做 PathProvider 抽象
- ADR-004: 抽离期间不动 `backend/` 现有代码
- ADR-005: 新建 `sdk-extraction/` 目录，不在 `backend/` 内
- ADR-006: SDK 输出为 `sdk-extraction/harness/` 目录

### 状态
- **阶段 0：脚手架** - ✅ 已完成
- **阶段 1-5**: ⏳ 待开始

## 待记录

（后续 session 进展会添加到这里）

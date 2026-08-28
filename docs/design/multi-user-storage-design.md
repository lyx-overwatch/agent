# 多用户隔离与生产存储架构设计

> 状态: **待实施** | 创建: 2026-07-27

## 1. 背景

当前 Heyu Agent 的文件系统层缺少显式的多用户隔离。虽然 `thread_id = "{user_id}-{conversation_id}"` 隐式区分了用户，但目录结构本身是扁平的 `threads/{tid}/...`，而且 SDK 版的 `PathProvider` Protocol 根本没有 `user_id` 参数——尽管 DeerFlow 原版 `Paths` 类早已实现了 `users/{uid}/threads/{tid}/user-data/...` 的层级结构。

此外，生产存储（S3/OSS）的规划也只存在于早期文档的展望里，没有具体设计。

## 2. 现状差距分析

| 层 | 有多用户隔离？ | 说明 |
|---|---|---|
| Auth (JWT) | ✅ | `login_user_key` 验证，`get_current_user` 依赖注入 |
| DB (runs, messages) | ✅ | `user_id` FK 列 |
| LangGraph thread_id | ✅ 隐式 | `"{user_id}-{conversation_id}"` 格式 |
| **Sandbox 文件系统** | **❌** | 扁平 `threads/{tid}/...` 无 user 层级 |
| **PathProvider Protocol** | **❌** | 所有 per-thread 方法只有 `thread_id`，没有 `user_id` |
| **DeerFlowPathProvider** | **❌** | preset 只实现了旧版扁平布局 |
| **DefaultPathProvider** | **❌** | 同上 |
| **AioSandboxProvider (SDK)** | **❌** | `_get_thread_mounts()` 只用 `thread_id` 构造路径 |
| **user_context.py** | **❌ 未使用** | ContextVar + Protocol 已定义，但 Heyu Agent auth 未调用 `set_current_user()` |
| **DeerFlow origin `Paths` 类** | ✅ | **参考实现**，下文详述 |

### 当前目录结构

```
agent-test/                          # 或 .skillhub/（生产）
└── threads/
    ├── userA-conv1/
    │   └── workspace/  uploads/  outputs/
    ├── userA-conv2/
    │   └── workspace/  uploads/  outputs/
    └── userB-conv3/
        └── workspace/  uploads/  outputs/
```

所有用户的线程数据混在同一层级，无法按用户做配额、清理、审计。

### DeerFlow 原版参考结构（`deerflow_origin/.../config/paths.py`）

```
{base}/
└── users/
    └── {user_id}/
        ├── memory.json
        └── threads/
            └── {thread_id}/
                ├── user-data/          # → 容器内 /mnt/user-data
                │   ├── workspace/      # rw
                │   ├── uploads/        # rw
                │   └── outputs/        # rw
                └── acp-workspace/      # → 容器内 /mnt/acp-workspace (ro)
```

原版 `AioSandboxProvider` 在每个请求中调用 `get_effective_user_id()` 并传给 `Paths.ensure_thread_dirs(thread_id, user_id=user_id)`。SDK 抽离时这一层被遗漏了。

## 3. 现有基础设施

SDK 已有 `user_context.py`，提供了完整的多用户基础：

```python
# agent_sdk/runtime/user_context.py
set_current_user(user)       # 绑定当前用户到 ContextVar
get_effective_user_id()      # 返回 user_id 字符串，未绑定时 fallback "default"
require_current_user()       # 未绑定抛 RuntimeError
resolve_user_id(AUTO/str/None)  # 三态解析（auto / 显式 / 旁路）
```

但 Heyu Agent 的 auth 中间件（`app/core/dependencies.py:get_current_user`）**从未调用 `set_current_user()`**，导致 ContextVar 始终为空，`get_effective_user_id()` 永远返回 `"default"`。

## 4. 设计方案

### 4.1 短期（Phase 1）：文件系统层用户隔离

**目标**：对齐 DeerFlow origin 的多用户目录结构，改动最小。

#### 4.1.1 PathProvider Protocol — 方法签名加 `user_id`

**文件**: `backend/packages/harness/agent_sdk/paths/provider.py`

```python
class PathProvider(Protocol):
    # 所有 per-thread 方法加 user_id 参数，None = 兼容无用户场景
    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path: ...
    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path: ...
    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path: ...
    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path: ...
    def get_acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path: ...
    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None) -> Path: ...
    # 不区分用户的方法不变
    def get_base_dir(self) -> Path: ...
    def get_skills_dir(self) -> Path: ...
    def get_virtual_prefix(self) -> str: ...
    def is_host_bash_allowed(self) -> bool: ...
```

设计要点：
- `user_id` 放在 `*` 之后（keyword-only），不影响现有按位置传参的调用方
- `None` = 兼容无用户场景（CLI / migration / 测试），内部 fallback 到 `"default"`

#### 4.1.2 DefaultPathProvider — 加 `users/{user_id}/` 层级

**文件**: `backend/packages/harness/agent_sdk/paths/default.py`

```python
class DefaultPathProvider:
    VIRTUAL_PREFIX = "/agent-data"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir else Path("./.agent-sdk").resolve()

    def _uid(self, user_id: str | None) -> str:
        return user_id or "default"

    def _thread_dir(self, thread_id: str, user_id: str | None) -> Path:
        return self._base_dir / "users" / self._uid(user_id) / "threads" / thread_id

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "workspace"

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "uploads"

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "outputs"

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id)

    def get_acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "acp-workspace"

    # get_base_dir / get_skills_dir / get_virtual_prefix / is_host_bash_allowed 不变
```

新结构：
```
{base}/
└── users/
    ├── default/          # user_id=None 时的 fallback
    │   └── threads/{tid}/workspace/ uploads/ outputs/
    ├── userA/
    │   └── threads/{tid}/workspace/ uploads/ outputs/
    └── userB/
        └── threads/{tid}/workspace/ uploads/ outputs/
```

#### 4.1.3 DeerFlowPathProvider — 同步加 user 层级

**文件**: `backend/packages/harness/agent_sdk/presets/deerflow/paths.py`

```python
class DeerFlowPathProvider:
    VIRTUAL_PREFIX = "/mnt/user-data"

    def _uid(self, user_id: str | None) -> str:
        return user_id or "default"

    def _thread_dir(self, thread_id: str, user_id: str | None) -> Path:
        return self._base_dir / "users" / self._uid(user_id) / "threads" / thread_id

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "user-data" / "workspace"

    # 同样模式处理 uploads / outputs / acp-workspace / default-venv
```

保留 DeerFlow 的 `user-data/` 子目录，在它之上加 `users/{uid}/threads/{tid}/`。

#### 4.1.4 ThreadDataMiddleware — 从 ContextVar 传 user_id

**文件**: `backend/packages/harness/agent_sdk/middlewares/thread_data.py`

当前代码已经调用了 `get_effective_user_id()`（第 102 行），但没有传给 `PathProvider`。需要改为：

```python
def _get_thread_paths(self, thread_id: str, user_id: str | None = None) -> dict[str, str]:
    return {
        "workspace_path": str(self._paths.get_workspace_dir(thread_id, user_id=user_id)),
        "uploads_path": str(self._paths.get_uploads_dir(thread_id, user_id=user_id)),
        "outputs_path": str(self._paths.get_outputs_dir(thread_id, user_id=user_id)),
    }
```

#### 4.1.5 AioSandboxProvider — mount 路径加 user 层级

**文件**: `backend/packages/harness/agent_sdk/community/aio_sandbox/provider.py`

```python
def _get_thread_mounts(self, thread_id: str) -> list[tuple[str, str, bool]]:
    from agent_sdk.runtime.user_context import get_effective_user_id
    user_id = get_effective_user_id()

    base = self._thread_base_dir
    thread_dir = base / "users" / (user_id or "default") / "threads" / thread_id
    workspace = thread_dir / "workspace"
    uploads = thread_dir / "uploads"
    outputs = thread_dir / "outputs"
    # ... 创建目录 + 返回 mount 列表
```

⚠️ 这里有一个 **DooD 路径翻译**问题：网关容器内的 `SKILLHUB_HOME` 路径和 Docker daemon（宿主机）看到的路径不同。需要通过 `SKILLHUB_HOST_BASE_DIR` 环境变量翻译。当前已有这个机制（`sandbox_mount_skills_host_path`），需要确认 `thread_base_dir` 也走同样的翻译。

#### 4.1.6 Heyu Agent Auth — 调用 `set_current_user()`

**文件**: `backend/app/core/dependencies.py`

在 `get_current_user` 依赖中设置 ContextVar：

```python
from agent_sdk.runtime.user_context import set_current_user, reset_current_user

async def get_current_user(...) -> str:
    user_id = ...  # 现有逻辑
    token = set_current_user(SimpleUser(id=user_id))
    try:
        yield user_id
    finally:
        reset_current_user(token)
```

需要一个简单的 `SimpleUser` 实现（满足 `CurrentUser` Protocol，有 `.id: str` 属性）。

#### 4.1.7 LocalSandboxProvider — 路径对齐

**文件**: `backend/packages/harness/agent_sdk/sandbox/local/provider.py`

`config_loader.py` 创建 `LocalSandboxProvider(workspace=Path("../agent-test") / "threads")` 时，路径也需要加 user 层级。但 LocalSandbox 的 `acquire()` 现在是 `_workspace / thread_id`，而 ThreadDataMiddleware 会给出 `_workspace / "users" / user_id / "threads" / thread_id / "workspace"`。

**最简单的方案**：`config_loader.py` 不再传 `workspace / "threads"`，改为传 `workspace`（即 `../agent-test`），和 `DefaultPathProvider` 的 `base_dir` 一致。然后 `LocalSandboxProvider.acquire()` 内部用 `user_id` 构造和 `DefaultPathProvider` 一致的路径。

或者更简单的方案：**让 `LocalSandboxProvider` 接受一个 `PathProvider` 而不是裸 `Path`**，直接从 `PathProvider` 取路径，彻底消除两套路径系统。这和之前做的 `acquire()` 对齐修复是同一个方向。

### 4.2 中期（Phase 2）：存储后端抽象

**目标**：让 uploads/outputs 可以走 S3/OSS，workspace 保持本地。

```
PathProvider           → 决定"路径应该长什么样"（目录结构）
StorageBackend         → 决定"IO 怎么执行"（本地 fs / S3 / OSS）
```

```python
class StorageBackend(Protocol):
    async def write(self, path: str, content: bytes) -> None: ...
    async def read(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
    async def list(self, prefix: str) -> list[str]: ...
    async def exists(self, path: str) -> bool: ...
```

分路线：
| 数据类型 | 存储位置 | 原因 |
|---|---|---|
| workspace | 本地磁盘 | 沙箱容器需要直接 mount |
| uploads | S3/OSS（可选） | 用户上传文件，可通过 presigned URL 下载 |
| outputs | S3/OSS（可选） | 工件文件，前端通过 presigned URL 下载 |
| skills | 本地磁盘 | 容器只读 mount |
| checkpoints | PostgreSQL | 已在用 |

### 4.3 长期（Phase 3）：数据生命周期 + 配额

- 按 `users/{uid}/` 做磁盘配额（`du` 或 filesystem quota）
- 自动清理过期线程数据（定时任务扫 `created_at`）
- 用户注销时一键清理 `users/{uid}/`

## 5. 实施计划

### Phase 1（短期，~5 个文件，1-2 天）

| 序号 | 文件 | 改动 |
|---|---|---|
| 1 | `agent_sdk/paths/provider.py` | Protocol 方法加 `*, user_id: str \| None = None` |
| 2 | `agent_sdk/paths/default.py` | 路径加 `users/{uid}/threads/{tid}/` |
| 3 | `agent_sdk/presets/deerflow/paths.py` | 同上，保留 `user-data/` 子目录 |
| 4 | `agent_sdk/middlewares/thread_data.py` | 把已有的 `get_effective_user_id()` 传给 PathProvider |
| 5 | `agent_sdk/community/aio_sandbox/provider.py` | `_get_thread_mounts()` 加 user 层级 |
| 6 | `app/core/dependencies.py` | `get_current_user` 调用 `set_current_user()` |
| 7 | `agent_sdk/sandbox/local/provider.py` | `acquire()` 路径对齐（可能需要接 PathProvider） |
| 8 | `app/core/config_loader.py` | 必要时调整 PathProvider/SandboxProvider 构造参数 |

### Phase 2（中期，后续规划）

- 引入 `agent_sdk/storage/` 子包
- `LocalStorageBackend`（当前行为的封装）
- `S3StorageBackend`（boto3 可选依赖）
- `CompositeStorageBackend`（分路线代理）
- 输出文件下载链路改为 presigned URL

### Phase 3（长期）

- 配额管理
- 数据生命周期
- 用户数据清理

## 6. 风险与注意点

1. **DooD 路径翻译**：网关容器内路径和 Docker daemon 宿主机路径不同，`AioSandboxProvider._get_thread_mounts()` 的 mount source 需要翻译（类似已有的 `sandbox_mount_skills_host_path` 机制）
2. **向后兼容**：`user_id=None` 走 `users/default/` fallback，不影响测试/CLI 场景
3. **迁移**：旧数据在 `threads/{tid}/` 下，新数据在 `users/{uid}/threads/{tid}/` 下，旧线程会自然过期
4. **Windows 路径**：`LocalSandbox` 的 `_guard()` 需要适配新路径结构
5. **`extract_thread_id` 函数**（`utils/thread.py`）：从 `workspace_path` 反推 thread_id 的逻辑依赖路径格式，改了目录结构后需要同步更新

## 7. 参考

- DeerFlow origin 参考实现: `backend/deerflow_origin/packages/harness/deerflow/config/paths.py`
- DeerFlow origin AioSandboxProvider: `backend/deerflow_origin/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`
- SDK user_context: `backend/packages/harness/agent_sdk/runtime/user_context.py`
- 当前 PathProvider: `backend/packages/harness/agent_sdk/paths/provider.py`
- 前期 LocalSandbox 路径修复: `backend/packages/harness/agent_sdk/sandbox/local/provider.py`（本次会话已修改）

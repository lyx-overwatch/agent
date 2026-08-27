# 阶段 1：PathProvider 抽象（2 周）

> 解开所有 `/mnt/user-data` 硬编码，建立 SDK 第一个 Protocol。

## 目标

把所有对 `/mnt/user-data`、`/mnt/skills` 等硬编码路径的引用，改为通过 `PathProvider` Protocol 注入。

## 关键交付物

1. **`PathProvider` Protocol**（SDK 内部）
2. **`DeerFlowPathProvider` 实现**（保留 `/mnt/user-data` 行为）
3. **`DefaultPathProvider` 实现**（无业务假设的基路径）
4. **`VirtualPathResolver`**（虚拟路径 ↔ 物理路径转换）
5. **修改 9+ 个文件**用 `PathProvider`

## 任务清单

### 1.1 设计 `PathProvider` Protocol（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/paths/provider.py`

**设计**：
```python
from pathlib import Path
from typing import Protocol


class PathProvider(Protocol):
    """Provides filesystem path resolution for a runtime.

    All paths returned MUST be absolute physical paths.
    Virtual-to-physical translation is handled by VirtualPathResolver.
    """

    def get_base_dir(self) -> Path:
        """Return the base directory for all runtime data."""
        ...

    def get_workspace_dir(self, thread_id: str) -> Path:
        """Return the per-thread workspace directory."""
        ...

    def get_uploads_dir(self, thread_id: str) -> Path:
        """Return the per-thread uploads directory."""
        ...

    def get_outputs_dir(self, thread_id: str) -> Path:
        """Return the per-thread outputs directory."""
        ...

    def get_skills_dir(self) -> Path:
        """Return the skills directory (global, not per-thread)."""
        ...

    def get_acp_workspace_dir(self, thread_id: str) -> Path:
        """Return the per-thread ACP workspace directory."""
        ...
```

**评审检查**：
- [ ] Protocol 完整覆盖所有当前硬编码路径
- [ ] 不强制继承（用 `Protocol`）
- [ ] 默认参数缺失时如何 fallback
- [ ] 路径校验的责任归属

### 1.2 创建 `DeerFlowPathProvider` 实现（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/presets/deerflow/paths.py`

**设计**：
```python
class DeerFlowPathProvider:
    """/mnt/user-data style path provider (DeerFlow compatible)."""

    VIRTUAL_PREFIX = "/mnt/user-data"

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or Path("./.deer-flow")

    def get_base_dir(self) -> Path:
        return self._base_dir

    def get_workspace_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id / "user-data" / "workspace"

    def get_uploads_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id / "user-data" / "uploads"

    def get_outputs_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id / "user-data" / "outputs"

    def get_skills_dir(self) -> Path:
        return self._base_dir / "skills"

    def get_acp_workspace_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id / "acp-workspace"
```

### 1.3 创建 `DefaultPathProvider` 实现（半天）

**文件**：`sdk-extraction/harness/agent_sdk/paths/default.py`

**设计**：
```python
class DefaultPathProvider:
    """Base-relative path provider with no /mnt/user-data assumption."""

    def __init__(self, base_dir: Path = Path("./.deerflow")):
        self._base_dir = base_dir

    # ... 同样的方法，但用 .deerflow 目录
```

**注意**：默认不预装，用户需显式传入。

### 1.4 创建 `VirtualPathResolver`（1 天）

**文件**：`sdk-extraction/harness/agent_sdk/paths/resolver.py`

**设计**：
```python
class VirtualPathResolver:
    """Translates between virtual paths and physical paths."""

    def __init__(self, path_provider: PathProvider, virtual_prefix: str = "/mnt/user-data"):
        self._provider = path_provider
        self._virtual_prefix = virtual_prefix

    def virtualize(self, physical: Path, thread_id: str) -> str:
        """Convert a physical path to a virtual path string."""
        workspace = self._provider.get_workspace_dir(thread_id)
        uploads = self._provider.get_uploads_dir(thread_id)
        outputs = self._provider.get_outputs_dir(thread_id)

        for prefix_dir, virtual_subpath in [
            (workspace, "workspace"),
            (uploads, "uploads"),
            (outputs, "outputs"),
        ]:
            try:
                rel = physical.relative_to(prefix_dir)
                return f"{self._virtual_prefix}/{virtual_subpath}/{rel}"
            except ValueError:
                continue
        return str(physical)

    def resolve(self, virtual: str, thread_id: str) -> Path:
        """Convert a virtual path to a physical path."""
        if not virtual.startswith(self._virtual_prefix):
            return Path(virtual)

        rel = virtual[len(self._virtual_prefix):].lstrip("/")
        if rel.startswith("workspace/"):
            return self._provider.get_workspace_dir(thread_id) / rel[len("workspace/"):]
        elif rel.startswith("uploads/"):
            return self._provider.get_uploads_dir(thread_id) / rel[len("uploads/"):]
        elif rel.startswith("outputs/"):
            return self._provider.get_outputs_dir(thread_id) / rel[len("outputs/"):]
        return Path(virtual)
```

### 1.5 在 SDK 中实现 sandbox 工具（3 天）

**位置**：`sdk-extraction/harness/agent_sdk/sandbox/tools.py`

**任务**：以新代码实现 1582 行等价 sandbox 工具（mask_local_paths_in_output、replace_virtual_paths_in_command、validate_local_tool_path、validate_local_bash_command_paths 等），所有硬编码路径通过 `PathProvider` 注入，函数签名接受 `path_provider: PathProvider` 和 `thread_id: str` 参数。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/sandbox/tools.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`
- ❌ 复制粘贴 `backend/sandbox/tools.py` 文件作为 SDK 源文件

**做法**：
- 读 `backend/sandbox/tools.py` 作为行为参考
- 在 SDK 内部**重新写**等价实现
- 用 SDK 自身的单元测试与 `backend/` 原版行为字节级对齐（golden fixture 模式，fixture 放在 `sdk-extraction/harness/tests/fixtures/sandbox/`）
- 全局常量 `VIRTUAL_PATH_PREFIX = "/mnt/user-data"` 移到 `DeerFlowPathProvider` 的常量
- 全局常量 `_DEFAULT_SKILLS_CONTAINER_PATH`、`_ACP_WORKSPACE_VIRTUAL_PATH` 移到 SDK 配置参数

**评审检查**：
- [ ] SDK 版 1582 行工具与 `backend/packages/harness/deerflow/sandbox/tools.py` 行为字节级一致
- [ ] 路径解析在边界情况（symlink、相对路径）正确
- [ ] 性能不退化

### 1.6 在 SDK 中实现 ThreadData / Uploads / 文件工具（2 天）

**待新建文件**（全部在 SDK 内部）：
- `agent_sdk/middlewares/thread_data.py` - SDK 版 ThreadDataMiddleware
- `agent_sdk/middlewares/uploads.py` - SDK 版 UploadsMiddleware
- `agent_sdk/tools/present_file.py` - SDK 版 present_file tool
- `agent_sdk/tools/view_image.py` - SDK 版 view_image tool
- `agent_sdk/tools/invoke_acp.py` - SDK 版 invoke_acp_agent tool
- `agent_sdk/paths/config.py` - SDK 版 Paths 配置类（与 `backend/config/paths.py` 平级但不引用）

**任务**：以新代码实现所有上述模块，所有硬编码路径通过 `PathProvider` 注入。

**绝对禁止**：
- ❌ 修改 `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py`
- ❌ 修改 `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`
- ❌ 修改 `backend/packages/harness/deerflow/tools/builtins/present_file_tool.py`
- ❌ 修改 `backend/packages/harness/deerflow/tools/builtins/view_image_tool.py`
- ❌ 修改 `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py`
- ❌ 修改 `backend/packages/harness/deerflow/config/paths.py`
- ❌ `from backend.* import ...` 或 `from deerflow.* import ...`

**做法**：
- SDK 版 middleware 从 `create_agent` 注入的 `PathProvider` 读取路径
- 默认无注入时使用 `DefaultPathProvider`（行为中性，可独立使用）
- 用 SDK 自身的单元测试与 `backend/` 原版行为字节级对齐

### 1.7 写单元测试（2 天）

**测试文件**：`sdk-extraction/harness/tests/paths/`

**测试用例**：
- [ ] `DefaultPathProvider` 返回正确路径
- [ ] `DeerFlowPathProvider` 返回 `/mnt/user-data` 风格路径
- [ ] `VirtualPathResolver.virtualize()` 正确转换
- [ ] `VirtualPathResolver.resolve()` 正确转换
- [ ] 自定义 `PathProvider` 正常工作
- [ ] 边界情况（线程 ID 为空、含特殊字符等）
- [ ] `DeerFlowPathProvider` 与 `backend/config/paths.py` 输出**字节级一致**（golden fixture 对比，fixture 放在 `sdk-extraction/harness/tests/fixtures/paths/`）

**绝对禁止**：
- ❌ 测试代码 `from backend.* import ...`
- ❌ 测试代码 import `backend.config.paths` 进行运行时对比
- ❌ 测试代码引用 `backend.tests.*` 的 fixture

### 1.8 验证 SDK 与 backend 行为字节级一致（1 天）

**测试方式**：
- 在 `sdk-extraction/harness/tests/fixtures/paths/` 维护**离线录制的 golden fixture**（来自 `backend/config/paths.py` 真实输出的快照，**不引用** `backend.*`）
- 单元测试对比 `DeerFlowPathProvider` 输出与 golden fixture
- 验证所有 sandbox 工具输出与 golden fixture 一致
- **可选地**只跑 `backend/tests/`（不修改其中任何代码）确认 DeerFlow 行为基线

**成功标准**：
- SDK 内部单元测试 100% 通过
- 所有 golden fixture 字节级匹配
- `backend/tests/` 基线回归通过（仅跑，不修改）

### 1.9 验证可注入新路径（半天）

**测试方式**：
- 在 SDK 内部 `tests/integration/` 写一个最小化示例，使用 `DefaultPathProvider`
- 验证 SDK 抽象工作正常
- 验证路径不出现 `/mnt/user-data`

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| 1582 行 `sandbox/tools.py` 重新实现引入 bug | 高 | 保持原逻辑不变，只替换路径来源；分小批重新实现；golden fixture 字节级对齐 |
| 路径边界情况（symlink、相对路径、UNC） | 中 | 单元测试覆盖；保持 `PureWindowsPath` 行为 |
| `backend/tests/` 基线回归不充分 | 中 | 在开始前先跑一次基线测试；不修改 `backend/tests/` 任何代码 |
| 路径注入带来的性能开销 | 低 | 缓存 `PathProvider` 实例；避免每次调用都构造 |

## 依赖

- 无前置依赖
- 为阶段 2-3 提供 `PathProvider` 基础

## 产出

- `sdk-extraction/harness/agent_sdk/paths/`
  - `__init__.py`
  - `provider.py` - Protocol
  - `default.py` - DefaultPathProvider
  - `resolver.py` - VirtualPathResolver
- `sdk-extraction/harness/agent_sdk/presets/deerflow/`
  - `paths.py` - DeerFlowPathProvider
- `sdk-extraction/harness/tests/paths/`
  - `test_provider.py`
  - `test_resolver.py`
  - `test_default.py`
  - `test_deerflow.py`

## 完成标准

- [ ] 1.1-1.9 全部完成
- [ ] SDK 单元测试 100% 通过
- [ ] DeerFlow 回归测试 100% 通过
- [ ] 文档更新（progress.md / changelog.md / decisions.md）

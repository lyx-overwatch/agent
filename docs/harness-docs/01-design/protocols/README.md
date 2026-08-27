# Protocol 设计

> 本目录包含 SDK 中所有 Protocol 的详细设计。每个 Protocol 是一个"业务选择注入点"。

## 待设计的 Protocol

| Protocol | 阶段 | 状态 | 详细规格 |
|----------|------|------|----------|
| `PathProvider` | 阶段 1 | 待设计 | `path-provider.md`（待写） |
| `MemorySchema` | 阶段 2 | 待设计 | `memory-schema.md`（待写） |
| `SubagentRegistry` | 阶段 2 | 待设计 | `subagent-registry.md`（待写） |
| `AuditRules` | 阶段 3 | 待设计 | `audit-rules.md`（待写） |
| `TodoSystemPrompt` | 阶段 2 | 待评估 | 是否需要 Protocol 化 |
| `ToolName` | 阶段 2 | 待评估 | 是否需要 Protocol 化 |

## Protocol 设计原则

### 1. Protocol 而非 ABC

优先使用 `typing.Protocol` 而非 `abc.ABC`：
- 鸭子类型友好
- 不强制继承
- 易测试

### 2. 最小接口

每个 Protocol 只暴露核心方法，细节可扩展：
```python
class PathProvider(Protocol):
    def get_workspace_dir(self, thread_id: str) -> Path: ...
    def get_uploads_dir(self, thread_id: str) -> Path: ...
    def get_outputs_dir(self, thread_id: str) -> Path: ...
    def get_base_dir(self) -> Path: ...
```

### 3. 默认实现

SDK 应提供"无业务假设"的默认实现：
```python
class DefaultPathProvider:
    """Base-relative path provider (no /mnt/user-data assumption)."""
    def __init__(self, base_dir: Path = Path("./.deerflow")):
        self._base_dir = base_dir

    def get_workspace_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id / "workspace"
    # ...
```

### 4. Preset 实现

DeerFlow preset 提供 DeerFlow 风格实现：
```python
class DeerFlowPathProvider:
    """/mnt/user-data style path provider (DeerFlow compatible)."""
    def get_workspace_dir(self, thread_id: str) -> Path:
        return Path(f"/mnt/user-data/workspace/{thread_id}")
    # ...
```

### 5. 用户实现

用户可自由实现 Protocol，注入到 `create_agent`：
```python
class MyPathProvider:
    def get_workspace_dir(self, thread_id: str) -> Path:
        return Path(f"/workspace/{thread_id}")

agent = create_agent(
    model=model,
    system_prompt=...,
    path_provider=MyPathProvider(),
)
```

## 协议清单（计划）

| Protocol | 业务耦合 | 抽离位置 | 优先级 |
|----------|----------|----------|--------|
| `PathProvider` | 路径前缀 | SDK 内部 | 高（阶段 1） |
| `MemorySchema` | 记忆数据模型 | SDK 内部 | 高（阶段 2） |
| `SubagentRegistry` | subagent 角色 | SDK 内部 | 中（阶段 2） |
| `AuditRules` | 安全规则 | SDK 内部 | 中（阶段 3） |
| `TodoSystemPrompt` | Todo prompt | SDK 内部 | 低（评估） |
| `ToolName` | 工具命名 | SDK 内部 | 低（评估） |
| `UserProfile` | USER.md | SDK 内部 | 低（评估） |
| `AgentSoul` | SOUL.md | SDK 内部 | 低（评估） |
| `CitationFormat` | 引用格式 | SDK 内部 | 低（评估） |
| `UserContext` | 用户上下文 | SDK 内部 | 中（runtime） |

## 设计流程

每个 Protocol 的详细设计文档应包含：

1. **背景**：为什么需要这个 Protocol
2. **接口定义**：完整的 Protocol 代码
3. **默认实现**：SDK 内置的"无业务"实现
4. **Preset 实现**：DeerFlow 风格的实现
5. **使用示例**：用户如何注入
6. **边界情况**：测试覆盖的边界
7. **迁移路径**：如何从现有硬编码迁移

## 状态

| Protocol | 设计完成 | 默认实现 | Preset 实现 | 迁移完成 |
|----------|----------|----------|-------------|----------|
| `PathProvider` | ⏳ 阶段 1 | ⏳ | ⏳ | ⏳ |
| `MemorySchema` | ⏳ 阶段 2 | ⏳ | ⏳ | ⏳ |
| `SubagentRegistry` | ⏳ 阶段 2 | ⏳ | ⏳ | ⏳ |
| `AuditRules` | ⏳ 阶段 3 | ⏳ | ⏳ | ⏳ |

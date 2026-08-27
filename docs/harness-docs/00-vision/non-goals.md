# 非目标（Non-Goals）

> 防止 Scope Creep。明确不做的事情，遇到时**直接拒绝**。

## 明确不做

### 1. 不重写 LangGraph 集成
- ❌ 直接复用 LangChain/LangGraph 0.6+ API
- ❌ 不重新设计 middleware 系统
- ❌ 不重写 state schema 机制

### 2. 不修改 `backend/` 现有代码
- ❌ 抽离期间 `backend/` 任何代码**完全不动**
- ❌ 不"顺手"修 bug
- ❌ 不"顺便"优化
- ❌ 不"重写一下更优雅"（除非现有代码是抽离的障碍）

### 3. 不优化性能
- ❌ 不做 token 使用优化
- ❌ 不做并发优化
- ❌ 不做缓存优化
- ❌ 不做内存优化

### 4. 不做跨语言 SDK
- ❌ 不做 TypeScript binding
- ❌ 不做 Rust/Go 绑定
- ❌ 只做 Python SDK

### 5. 不做新功能
- ❌ 不加新 middleware
- ❌ 不加新工具
- ❌ 不加新模型 provider
- ❌ 不加新 sandbox 后端

### 6. 不做 UX 改进
- ❌ 不改 CLI 体验
- ❌ 不改 API 设计
- ❌ 不改前端
- ❌ 不改 DeerFlowClient

### 7. 不重写业务逻辑
- ❌ 不重写 sandbox 工具实现
- ❌ 不重写 memory 数据模型
- ❌ 不重写 subagent executor
- ❌ 只做"协议化"和"打包"

### 8. 不抽离 LangGraph Platform 兼容层
- ❌ `runtime/runs/`（RunManager / RunRecord / worker.py）保留在 backend
- ❌ `runtime/events/store/` 保留在 backend
- ❌ 这部分与 LangGraph Platform 强耦合，不属于通用 SDK

### 9. 不抽离持久化 SQL 实现
- ❌ `persistence/*`（SQLAlchemy ORM）保留在 backend
- ❌ 只抽象 ABC（如 `RunStore` / `ThreadMetaStore`）
- ❌ 业务表（runs/threads_meta/feedback/users）保留

### 10. 不抽离 ACP / IM 集成
- ❌ `config/acp_config.py` 保留在 backend
- ❌ `tools/builtins/invoke_acp_agent_tool.py` 保留在 backend

## 防止的诱惑

| 诱惑 | 应对 |
|------|------|
| "这个 middleware 实现得不够好" | → 不动。它是 DeerFlow 的业务实现，不在抽离范围 |
| "这个 prompt 写得太死板" | → 不动。prompt 文案是 L1 业务耦合，由 preset 管理 |
| "这个工具的命名很奇怪" | → 不动。命名是 L1 业务耦合，由 preset 包装 |
| "这段代码可以更简洁" | → 不动。重构不是抽离的目标 |
| "测试覆盖率不够" | → 抽离期间只保证新增代码有测试 |
| "性能有瓶颈" | → 记录到 `03-status/blockers.md`，留作后续 |
| "这里可以加个新特性" | → 拒绝。文档会说明哪些不在范围 |
| "顺便修一下这个 bug" | → 拒绝。bug fix 不在抽离 PR 范围 |

## 例外

以下情况**可以**超出非目标范围：

1. **抽离的物理障碍**：如果现有代码结构导致无法抽离，可以做最小修改（如重命名、调整 import 顺序）
2. **协议设计的必要重构**：设计 Protocol 时如果现有代码结构不清晰，可以重构接口（不动实现）
3. **测试基础设施**：可以搭建新的测试工具以支持 SDK 测试

但所有超出范围的工作必须：
- 在 PR 描述中明确说明
- 在 `03-status/decisions.md` 记录 ADR
- 在 `03-status/changelog.md` 记录变更

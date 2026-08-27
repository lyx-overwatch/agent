# 项目范围

## In Scope（做）

### 抽离范围
- 把 `backend/packages/harness/deerflow` 的**通用 agent 逻辑**抽离到 `sdk-extraction/harness/`
- 引入 `PathProvider` / `MemorySchema` / `SubagentRegistry` / `AuditRules` 等 Protocol
- 把 DeerFlow 业务选择打包成 `agent_sdk.presets.deerflow`（在 SDK 内部）
- 编写单元测试验证 SDK 可独立运行
- 编写集成测试验证 DeerFlow 行为不变

### 设计范围
- 设计 SDK 公开 API（`create_agent` / `RuntimeFeatures` / 各 Protocol）
- 设计 DeerFlow preset 的导入方式
- 设计 `pyproject.toml` 包配置
- 设计测试策略

### 文档范围
- 维护 `docs/` 下所有规划与状态文档
- 维护 `sdk-extraction/harness/CHANGELOG.md` 抽离过程
- 维护 ADR（架构决策记录）

## Out of Scope（不做）

### 不修改 DeerFlow 应用
- ❌ 不修改 `backend/` 任何现有代码（除非要同步新增 SDK 的 import 路径）
- ❌ 不修改 `backend/app/` 任何业务路由
- ❌ 不修改现有测试套件
- ❌ 不修改 `config.yaml` / `extensions_config.json` 格式

### 不重写
- ❌ 不重写 LangGraph 集成（直接复用 LangChain/LangGraph 0.6+ API）
- ❌ 不重写 LangChain middleware 系统
- ❌ 不重写 sandbox 实现（只做协议化）
- ❌ 不重写 memory 抽象（保留 ABC）

### 不优化
- ❌ 不做性能优化（先保证功能正确）
- ❌ 不做并发优化
- ❌ 不做内存优化

### 不扩展
- ❌ 不做跨语言 SDK（TypeScript、Rust、Go）
- ❌ 不做新特性（只搬现有特性）
- ❌ 不做 UX 改进
- ❌ 不做新工具

### 不抽离（保留在 `backend/packages/harness/deerflow`）
- ❌ `agents/lead_agent/*`（DeerFlow 业务）
- ❌ `agents/memory/storage.py` 的业务实现（ABC 抽离）
- ❌ `agents/lead_agent/prompt.py`（DeerFlow 业务 prompt）
- ❌ `tools/builtins/*` 的业务实现
- ❌ `subagents/builtins/*`
- ❌ `client.py` DeerFlowClient
- ❌ `persistence/*`（SQLAlchemy 业务）
- ❌ `community/*`（第三方集成）
- ❌ `models/credential_loader.py` / `models/*_provider.py`

## 边界规则

### sdk-extraction/harness/ 规则
- **只增不改**：抽离完成后，目录是独立 Python 包，可 `pip install`
- **不依赖 backend/**：SDK 包绝对不能 `import backend.*` 或 `import app.*`
- **协议化优先**：每个 DeerFlow 业务选择都通过 Protocol 注入

### backend/ 规则（抽离期间）
- **完全不动**：抽离期间 `backend/` 任何代码**完全不动**
- **抽离完成后**：可选择性迁移 DeerFlow 应用到使用 SDK（这是另一阶段的事）

### 测试规则
- **SDK 单元测试**：在 `sdk-extraction/harness/tests/` 下，测试 SDK 可独立运行
- **DeerFlow 回归测试**：在 `backend/tests/` 下，原有测试不动
- **集成测试**：验证 DeerFlow 应用通过 preset 使用 SDK 后行为不变

## 抽离完成判定

满足以下条件即认为抽离完成：

1. `sdk-extraction/harness/` 包含完整 Python 包代码
2. SDK 单元测试 100% 通过
3. DeerFlow 应用通过 preset 使用 SDK 时，原有测试套件**100% 通过**
4. SDK 可在干净 Python 环境中 `pip install` 成功
5. 文档完整：`docs/` 全部填充，`sdk-extraction/harness/README.md` 有完整 API 说明

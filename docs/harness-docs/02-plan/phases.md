# 抽离阶段总览

> 总览 7 个阶段的计划、产出、风险、估时。
>
> **推进顺序**（按 ADR-010 + L1/L2/L3 抽离策略）：
> 阶段 1 → 阶段 2 → 阶段 3 → **阶段 5（L3 通用层）** → 阶段 4（Preset，含原阶段 6 集成验证）→ 阶段 6（发布）

## 阶段 0：脚手架（已完成）✅

**目标**：建立项目骨架

**产出**：
- `sdk-extraction/` 目录结构
- `docs/` 完整规划文档（vision / design / plan / status）
- `harness/` SDK 骨架（README / pyproject / CHANGELOG / 空包）
- 2 个历史分析文档移到 `docs/05-archive/`

**风险**：无

**估时**：1-2 小时

---

## 阶段 1：PathProvider 抽象（2 周）✅

**目标**：解开所有 `/mnt/user-data` 硬编码

**为什么优先**：路径前缀是耦合最广的硬编码（9+ 个文件），解开后所有特性的"业务注入点"模式都可参照

**详细计划**：[`phase-1-path-provider.md`](phase-1-path-provider.md)

**关键产出**（全部为 SDK 内部新增，`backend/` 不动）：
- `PathProvider` Protocol（`agent_sdk/paths/provider.py`）
- `DeerFlowPathProvider` 实现（`agent_sdk/presets/deerflow/paths.py`）
- `DefaultPathProvider` 实现（`agent_sdk/paths/default.py`，无业务假设）
- `VirtualPathResolver`（`agent_sdk/paths/resolver.py`，虚拟路径 ↔ 物理路径）
- 单元测试（`agent_sdk/tests/paths/`）

**不在阶段 1 范围**：
- 修改 `backend/packages/harness/deerflow/sandbox/tools.py`、`agents/middlewares/*`、`tools/builtins/*` 等现有文件（违反 ADR-004）
- 1582 行 sandbox 工具的 PathProvider 化改造属于阶段 5（SDK 通用层 + sandbox 工具实现）

**风险**：
- 中（涉及 1582 行 sandbox 工具的行为对齐）
- 需要保持 DeerFlow 行为完全不变

**验证**：
- SDK 内部单元测试 100% 通过
- `DeerFlowPathProvider` 与 `backend/config/paths.py` 行为字节级一致（通过离线 golden fixture 对比，不 import `backend.*`）
- 可注入新路径前缀（如 `/workspace`）
- `backend/tests/` 基线回归通过（仅跑，不修改）

---

## 阶段 2：Memory / Subagent / Tools 数据模型抽象（2 周）

**目标**：解开数据模型和工具命名的硬编码

**详细计划**：[`phase-2-data-models.md`](phase-2-data-models.md)

**关键产出**（全部为 SDK 内部新增，`backend/` 不动）：
- `MemorySchema` Protocol（`agent_sdk/memory/schema.py`）
- `SubagentRegistry` Protocol（`agent_sdk/subagents/registry.py`）
- 工具命名 factory（`agent_sdk/tools/factory.py`）
- SDK 版 `MemoryMiddleware` / `MemoryUpdater`（`agent_sdk/memory/middleware.py`、`updater.py`）
- SDK 版 `SubagentExecutor` / `task tool`（`agent_sdk/subagents/executor.py`、`agent_sdk/tools/task.py`）
- 单元测试 + golden fixture

**不在阶段 2 范围**：
- 修改 `backend/agents/memory/*`、`backend/subagents/builtins/*`、`backend/tools/builtins/*` 等现有文件

**风险**：
- 中-高（涉及 memory 子系统）

**验证**：
- SDK 内部单元测试 100% 通过
- `DeerFlowMemorySchema` / `DeerFlowSubagentRegistry` 与 `backend/` 原版行为字节级一致
- `backend/tests/` 基线回归通过（仅跑，不修改）

---

## 阶段 3：Audit / Prompt 抽象（1 周）

**目标**：解开安全规则和 prompt 文案的硬编码

**详细计划**：[`phase-3-audit-prompt.md`](phase-3-audit-prompt.md)

**关键产出**（全部为 SDK 内部新增，`backend/` 不动）：
- `AuditRules` Protocol（`agent_sdk/sandbox/audit/rules.py`）
- `TodoPrompts` 数据类 + 默认无业务假设的 prompt（`agent_sdk/middlewares/todo/prompts.py`）
- SDK 版 `SandboxAuditMiddleware`（`agent_sdk/sandbox/audit/middleware.py`）
- SDK 版 `TodoMiddleware`（`agent_sdk/middlewares/todo/middleware.py`）
- 单元测试

**不在阶段 3 范围**：
- 修改 `backend/agents/middlewares/sandbox_audit_middleware.py`、`backend/agents/factory.py` 等现有文件

**风险**：
- 低-中

**验证**：
- SDK 内部单元测试 100% 通过
- `DeerFlowAuditRules` 与 `backend/agents/middlewares/sandbox_audit_middleware.py` 现有规则字节级一致
- `backend/tests/` 基线回归通过（仅跑，不修改）

---

## 阶段 5：L3 通用层抽离（3 周）★ 新增

> **注意**：原线性计划中此阶段缺失。L3 通用层是 SDK 的骨架，缺了它 SDK 只是个空壳。

**目标**：把 L3 纯通用能力（无业务假设）抽到 SDK 内部，建立 SDK 骨架

**详细计划**：[`phase-5-l3-foundation.md`](phase-5-l3-foundation.md)

**关键产出**（全部为 SDK 内部新增，`backend/` 不动）：

- **SDK 入口与基础设施**：
  - `create_agent()` 主入口
  - `RuntimeFeatures` 数据类
  - `@Next` / `@Prev` 装饰器（middleware 位置声明）
  - `ThreadState`（基础 `AgentState`）

- **5 个通用 middleware**（直接抽到 SDK）：
  - `DanglingToolCallMiddleware`
  - `ToolErrorHandlingMiddleware`
  - `TokenUsageMiddleware`
  - `LoopDetectionMiddleware`
  - `DeferredToolFilterMiddleware`

- **抽象 ABC**（无业务假设的接口）：
  - `Sandbox` / `SandboxProvider`
  - `MemoryStorage`（泛型化，参考阶段 2 实现）
  - `UserContext`（ContextVar 抽象）
  - `StreamBridge`
  - `GuardrailProvider` Protocol

- **运行时基础设施**：
  - LangGraph 0.6+ 集成
  - `Checkpointer` / `Store`
  - `ModelFactory`
  - `ToolLoader`（装配逻辑）
  - `Reflection` 工具
  - `Tracing` 工厂（LangSmith / Langfuse）
  - `Utils`（文件转换、网络端口分配、HTML 解析）

- **集成子系统**：
  - `MCPClient` + OAuth 拦截器 + 同步包装
  - Skills 加载器 + 安装器 + YAML frontmatter 解析
  - Guardrails OAP 协议实现

- **业务特性 middleware**（使用 Protocol 注入）：
  - `TodoMiddleware`（阶段 3 已经在 L2 实现）
  - `MemoryMiddleware`（阶段 2 已经在 L2 实现）
  - `SubagentLimitMiddleware`
  - `UploadsMiddleware`
  - `ThreadDataMiddleware`
  - `ViewImageMiddleware`
  - `TitleMiddleware`
  - `SummarizationMiddleware`
  - `ClarificationMiddleware`
  - `LLMErrorHandlingMiddleware`
  - `SandboxMiddleware`
  - `SandboxAuditMiddleware`（阶段 3 已经在 L2 实现）
  - `DeferredToolFilterMiddleware`（已在通用层）

- **Sandbox 工具实现**：
  - SDK 版 `sandbox/tools.py`（1582 行等价实现，使用 PathProvider 注入）

**不在阶段 5 范围**：
- 修改 `backend/packages/harness/deerflow/agents/middlewares/*` 等现有文件
- 修改 `backend/packages/harness/deerflow/sandbox/tools.py`

**风险**：
- 高（涉及 SDK 骨架、18 个 middleware 装配、LangGraph 集成）
- 工作量最大的一阶段

**验证**：
- SDK 内部单元测试 100% 通过
- 所有 18 个 middleware 按正确顺序装配（`ThreadData → Uploads → Sandbox → DanglingToolCall → LLMErrorHandling → Guardrail → SandboxAudit → ToolErrorHandling → Summarization → TodoList → TokenUsage → Title → Memory → ViewImage → DeferredToolFilter → SubagentLimit → LoopDetection → Clarification`）
- SDK 版 1582 行 sandbox 工具与 `backend/sandbox/tools.py` 行为字节级一致
- `backend/tests/` 基线回归通过（仅跑，不修改）

---

## 阶段 4：在 SDK 内部新建 DeerFlow Preset 子包（已完成）✅

> **注意**：阶段 4 推迟到阶段 5 之后，因为 preset 需要用到 L3 通用层的基础设施。

**目标**：在 `sdk-extraction/harness/agent_sdk/presets/deerflow/` 内以新代码实现 DeerFlow 业务选择 preset + 端到端集成验证，**不触碰 `backend/`**

**详细计划**：[`phase-4-deerflow-preset.md`](phase-4-deerflow-preset.md)

**实际产出**（阶段 4 吸收了原阶段 6 的集成验证）：
- `agent_sdk.presets.deerflow` 子包：
  - `paths.py` — `DeerFlowPathProvider`（阶段 1）
  - `memory.py` — `DeerFlowMemorySchema`（阶段 2）
  - `subagents.py` — `DeerFlowSubagentRegistry`（阶段 2）
  - `audit.py` — `DeerFlowAuditRules`（阶段 3）
  - `prompts/todo.py` — `DEERFLOW_TODO_PROMPTS`（阶段 3）
  - `prompts/system.py` — ~700 行 system prompt（阶段 4 新增）
  - `agent.py` — `DeerFlowAgent` 便利类 + `DEERFLOW_DEFAULT_FEATURES`（阶段 4 新增）
- 文档：`presets/deerflow/README.md`
- 测试：`tests/presets/deerflow/test_agent.py` 16 个 + `test_system_prompt.py` 22 个

**已整合的原阶段 6 内容**：
- `DeerFlowAgent._build()` + `test_agent.py` 覆盖了端到端流程验证
- 5.8 `test_middleware_chain.py` 覆盖了 middleware 装配顺序
- 各阶段 1187 个测试覆盖了集成测试矩阵

---

## ~~阶段 6：端到端集成~~（已取消，被阶段 4+5 吸收）

> 原计划中阶段 6 是独立的端到端集成验证阶段。实际执行时，阶段 4 的 `DeerFlowAgent` 一步到位完成了 preset 组装 + graph 构建 + 端到端验证，阶段 5 的单元测试覆盖了 middleware 链顺序、Memory round-trip、Subagent 调用等路径。原阶段 6 的 6 项中有 4 项被阶段 4+5 的测试覆盖，剩余缺口（多 thread 隔离等）归入阶段 6（发布）的已知缺口清单。

---

## 阶段 6：测试 + 发布（1-2 周）

> **原阶段 5 内容**，因 L3 通用层抽离而推迟到 7。

**目标**：SDK 可独立发布和验证

**详细计划**：[`phase-6-publishing.md`](phase-6-publishing.md)

**关键产出**：
- SDK 单元测试覆盖率 > 80%
- SDK 集成测试完整覆盖
- SDK 完整 README
- API 文档（sphinx / mkdocs）
- `pyproject.toml` 完善
- `MANIFEST.in`
- 发布脚本
- 干净环境 `pip install -e sdk-extraction/harness/` 验证
- CHANGELOG 0.1.0

**风险**：
- 中（测试覆盖需要时间）

**验证**：
- SDK 单元测试 100% 通过
- 集成测试 100% 通过
- 干净环境 `pip install` 成功
- 非 DeerFlow 项目能成功使用 SDK
- `backend/tests/` 基线回归通过（仅跑，不修改）

---

## 阶段依赖关系（最终推进顺序）

```
阶段 0 (脚手架)         ✅
    ↓
阶段 1 (PathProvider)   ✅
    ↓
阶段 2 (数据模型)       ✅
    ↓
阶段 3 (审计/Prompt)    ✅
    ↓
阶段 5 (L3 通用层)      ✅
    ↓
阶段 4 (Preset)         ✅ —— 实际吸收了原阶段 6 的集成验证
    ↓
阶段 6 (发布)           ⏳
```

**与原计划的差异**：
1. **阶段 5 提前到阶段 4 之前**：preset 需要 L3 骨架
2. **阶段 6（集成）取消**：`DeerFlowAgent` + 阶段 5 单元测试已覆盖原阶段 6 的大部分内容，剩余缺口归入阶段 6（发布）的已知缺口清单
3. **阶段 7→阶段 6**：原阶段 7 重编号为阶段 6

## 抽离 PR 边界（ADR-004 实施细则）

**抽离 PR 范围**（所有 6 个阶段）：
1. 在 `sdk-extraction/harness/` 内新建 Python 包 `agent-sdk`。
2. 包含 4 个 Protocol（PathProvider、MemorySchema、SubagentRegistry、AuditRules）+ 18 个 middleware + 抽象 ABC + DeerFlow preset。
3. SDK 内部 100% 测试通过。

**不在抽离 PR 范围**（后续应用迁移 PR）：
1. 修改 `backend/` 让 DeerFlow 应用 import `agent_sdk.presets.deerflow`。
2. 删除 `backend/packages/harness/deerflow/` 中已被 SDK 替代的代码。
3. 更新 `langgraph.json` / `config.yaml` 让 DeerFlow 使用新 SDK 入口。
4. 真正的"`DeerFlowClient` → `DeerFlowAgent`"切换。
5. 端到端"DeerFlow 应用通过 preset 使用 SDK"测试。

## 总工作量

约 8 周（含脚手架 + 6 个实施阶段 + 发布）。

## 优先级

1. **阶段 0** ✅ 已完成
2. **阶段 1** ✅ 已完成
3. **阶段 2** ✅ 已完成
4. **阶段 3** ✅ 已完成
5. **阶段 5** ✅ 已完成
6. **阶段 4** ✅ 已完成（含原阶段 6 集成验证）
7. **阶段 6** ⏳ 待做（发布）

## 阶段跟踪

每个阶段有自己的 `phase-X-*.md` 详细计划。完成后：
- 更新 `03-status/progress.md`
- 在 `03-status/changelog.md` 记录
- 在 `03-status/decisions.md` 加新 ADR（如有）

## 切换阶段前必做

- [ ] 当前阶段所有任务完成
- [ ] 单元测试通过
- [ ] `backend/tests/` 基线回归通过（**仅运行**，不修改其中任何代码、fixture 或 conftest.py）
- [ ] `03-status/progress.md` 更新
- [ ] 下一阶段的 `phase-X-*.md` 详细计划已写
- [ ] 如发现 `backend/tests/` 失败：先确认 `backend/` 未被改过（理论上不应被改），然后把差异记录到 `03-status/blockers.md`，**不修复** `backend/tests/`

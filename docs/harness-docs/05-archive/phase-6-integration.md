# 阶段 6：端到端集成（1 周）★ 新增

> L1/L2/L3 三层 + DeerFlow preset 端到端跑通，验证 18 个 middleware 按正确顺序协同。
>
> **为什么需要这个阶段**：阶段 5 完成后 L1/L2/L3 三层 + preset 都齐了，但需要专门的集成验证阶段——单模块单元测试通过不等于端到端能跑通。

## 目标

1. 18 个 middleware 按正确顺序协同
2. L1 抽象 + L2 特性 + L3 通用层 + DeerFlow preset 端到端跑通
3. 多 thread 隔离、Memory 持久化、Subagent 调用等关键路径集成验证
4. 集成测试覆盖矩阵

## 关键交付物

### 6.1 端到端 lead agent 流程测试（2 天）

**位置**：`sdk-extraction/harness/tests/integration/`

**测试用例**：
- [ ] `DeerFlowAgent` 创建后能跑通完整 lead agent 流程
- [ ] 18 个 middleware 按 `phases.md` 文档中定义的顺序装配
- [ ] `create_agent` 入口能正确装配所有 L2 特性（PathProvider + MemorySchema + SubagentRegistry + AuditRules）
- [ ] LLM 调用、工具调用、Memory 更新等核心流程可观察

### 6.2 middleware 链顺序验证（1 天）

- [ ] 单元测试验证 18 个 middleware 装配顺序
- [ ] 顺序由 `@Next` / `@Prev` 装饰器驱动
- [ ] 验证 `ThreadData → Uploads → Sandbox → DanglingToolCall → LLMErrorHandling → Guardrail → SandboxAudit → ToolErrorHandling → Summarization → TodoList → TokenUsage → Title → Memory → ViewImage → DeferredToolFilter → SubagentLimit → LoopDetection → Clarification` 正确

### 6.3 多 thread 隔离验证（1 天）

- [ ] 不同 thread_id 的 workspace / uploads / outputs 路径互不干扰
- [ ] PathProvider 正确解析 thread_id
- [ ] VirtualPathResolver 正确转换多 thread 路径

### 6.4 Memory 持久化 round-trip（1 天）

- [ ] Memory 写入后能正确读取
- [ ] DeerFlowMemorySchema 与 FileMemoryStorage 协同工作
- [ ] workContext / personalContext / topOfMind 三段式数据正确序列化/反序列化

### 6.5 Subagent 调用流程（半天）

- [ ] SubagentRegistry 正确注册 general-purpose / bash
- [ ] task tool 正确通过 registry 查找角色
- [ ] SubagentExecutor 正确调度

### 6.6 集成测试覆盖矩阵（1 天）

每层 × 每特性的集成测试覆盖：

| 层级 | 特性 | 测试 |
|------|------|------|
| L1 抽象 | PathProvider | ✅ 阶段 1 |
| L1 抽象 | MemorySchema | 阶段 2 |
| L1 抽象 | SubagentRegistry | 阶段 2 |
| L1 抽象 | AuditRules | 阶段 3 |
| L2 特性 | 任务规划 (Todo) | 阶段 3 |
| L2 特性 | 长期记忆 (Memory) | 阶段 2 |
| L2 特性 | 多 Agent (Subagent) | 阶段 2 |
| L2 特性 | 文件管理 (Uploads) | 阶段 5 |
| L2 特性 | 沙箱 (Sandbox) | 阶段 5 |
| L2 特性 | 安全审计 (Audit) | 阶段 3 |
| L2 特性 | Skills | 阶段 5 |
| L2 特性 | MCP | 阶段 5 |
| L2 特性 | Guardrails | 阶段 5 |
| L3 通用 | 5 个通用 middleware | 阶段 5 |
| L3 通用 | StreamBridge | 阶段 5 |
| L3 通用 | UserContext | 阶段 5 |
| L3 通用 | Checkpointer | 阶段 5 |
| L3 通用 | Store | 阶段 5 |
| L3 通用 | ModelFactory | 阶段 5 |
| L3 通用 | ToolLoader | 阶段 5 |
| Preset | DeerFlowAgent | 阶段 4 |

**关键集成路径**：
- 18 个 middleware 链端到端跑通
- L1 抽象 + L2 特性 + L3 通用层 + Preset 协同
- 与 LangGraph 集成（线程、checkpointer、state）

## 任务清单

- [ ] 6.1 端到端 lead agent 流程测试（2 天）
- [ ] 6.2 middleware 链顺序验证（1 天）
- [ ] 6.3 多 thread 隔离验证（1 天）
- [ ] 6.4 Memory 持久化 round-trip（1 天）
- [ ] 6.5 Subagent 调用流程（半天）
- [ ] 6.6 集成测试覆盖矩阵（1 天）
- [ ] 6.7 验证 `backend/tests/` 基线回归（仅跑，不修改）

## 不在阶段 6 范围

- 修改 `backend/` 让 DeerFlow 应用 import preset
- 端到端"DeerFlow 应用通过 preset 使用 SDK"测试（属于后续应用迁移 PR）

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| middleware 链顺序错误 | 高 | 6.2 单元测试验证；端到端流程可观察 |
| L1/L2/L3 三层协议签名不匹配 | 中 | 集成测试覆盖矩阵；类型注解检查 |
| LangGraph 0.6+ 集成 API 变更 | 中 | 锁定 langgraph 版本；充分测试 |
| Memory 序列化/反序列化丢失字段 | 中 | golden fixture 字节级对比 |
| DeerFlow preset 与 SDK core 不兼容 | 中 | 阶段 4 之后立即跑集成测试 |

## 依赖

- 阶段 1-5 全部完成

## 产出（**全部在 SDK 内部**）

- `sdk-extraction/harness/tests/integration/`
  - `test_lead_agent_flow.py` - 端到端 lead agent 流程
  - `test_middleware_chain.py` - middleware 链顺序
  - `test_thread_isolation.py` - 多 thread 隔离
  - `test_memory_round_trip.py` - Memory 持久化
  - `test_subagent_flow.py` - Subagent 调用
  - `test_coverage_matrix.py` - 集成测试覆盖矩阵

## 完成标准

- [ ] 6.1-6.7 全部完成
- [ ] 集成测试 100% 通过
- [ ] 18 个 middleware 按正确顺序协同
- [ ] `DeerFlowAgent` 跑通完整 lead agent 流程
- [ ] **`backend/` 全程未触碰**
- [ ] `backend/tests/` 基线回归通过（仅跑，不修改）

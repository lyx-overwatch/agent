# 阶段 5 第五批：middleware 链装配

> **范围**：5.8 是 1 周规模（chain assembly 单一任务）。本批完成核心装配 + 后向兼容 shim。
>
> **第五批范围（5.8）**：
> - `agent_sdk/runtime/middleware_chain.py` - `MiddlewareChainConfig` + `assemble_chain()` + `_insert_extra_middlewares()`
> - `entry.py` 接受 `l2_config` + `plan_mode`；L2 特性全部 wire-up
> - 向后兼容 shim（保留 5.1-era 公开 API）
>
> **不在第五批范围（后续批次）**：
> - 5.5 集成子系统（MCP / Skills / Guardrails 完整中间件）
> - 5.7 Sandbox 工具实现（1582 行）

## 任务清单

- [x] 5.8.1 `agent_sdk/runtime/middleware_chain.py` - `MiddlewareChainConfig` + `assemble_chain()` + `_insert_extra_middlewares()`
- [x] 5.8.2 `agent_sdk/runtime/entry.py` 接受 `l2_config` + `plan_mode`；L2 特性 wire-up
- [x] 5.8.3 `agent_sdk/runtime/__init__.py` 导出 `MiddlewareChainConfig` / `assemble_chain`
- [x] 5.8.4 `tests/runtime/test_middleware_chain.py` - 28 个用例
- [x] 5.8.5 `tests/runtime/test_entry.py` 扩展 - 3 个 L2 end-to-end 用例
- [x] 5.8.6 验证：ruff + pytest + ADR-010

## 设计要点

### MiddlewareChainConfig

10 个 L2 特性运行时依赖字段：

| 字段 | 驱动 |
|------|------|
| `path_provider` | ThreadDataMiddleware / UploadsMiddleware |
| `sandbox_provider` | SandboxMiddleware |
| `audit_rules` | SandboxAuditMiddleware |
| `title_model_factory` | TitleMiddleware (async LLM) |
| `title_prompts` | TitleMiddleware |
| `summarization_model` | SummarizationMiddleware |
| `summarization_hooks` | SummarizationMiddleware |
| `memory_schema_cls` | MemoryMiddleware |
| `memory_storage` | MemoryMiddleware |
| `todo_prompts` | TodoMiddleware |
| `guardrail_provider` | GuardrailMiddleware (待 5.5 集成) |

### 装配顺序（17 个 middleware）

与 backend `make_lead_agent` 一致：

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

### Clarification 始终在最后

- 未锚定 extra middleware 默认插到 Clarification 之前
- `@Next(ClarificationMiddleware)` 的 extra 在装配后被强制移到尾部（restore invariant）

### 缺依赖错误

```python
RuntimeFeatures(sandbox=True) + MiddlewareChainConfig()  # 无 path_provider
→ ValueError: "RuntimeFeatures.sandbox=True requires MiddlewareChainConfig.path_provider.
              Construct a PathProvider (e.g. DeerFlowPathProvider) and pass it via l2_config."
```

### 向后兼容 shim

- `_assemble_from_features(features, *, extra_middleware=None)` 委托给 `assemble_chain`
- `_insert_extra(chain, extras)` 委托给 `_insert_extra_middlewares`
- `_L3_CHAIN_ORDER` / `_L2_FEATURE_NAMES` / `_build_l3_defaults` 保留（5.1 测试仍在用）

## 产出

```
agent_sdk/runtime/
├── middleware_chain.py        # 新增（assemble_chain + MiddlewareChainConfig）
├── entry.py                   # 更新（l2_config + plan_mode + 向后兼容 shim）
└── __init__.py                 # 更新（导出 MiddlewareChainConfig / assemble_chain）

tests/runtime/
├── test_middleware_chain.py   # 新增（28 个用例）
└── test_entry.py               # 更新（增加 3 个 L2 end-to-end 用例）
```

## 完成标准

- [x] 5.8 所有任务完成
- [x] ruff check 全部通过
- [x] pytest 100% 通过（累计 749/749）
- [x] 0 处 import `backend.*` / `deerflow.*` / `app.*`
- [x] `backend/` 全程未触碰

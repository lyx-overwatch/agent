# 阶段 5 第四批：9 个 L2 业务特性 middleware

> **范围**：5.6 是 1 周规模（13 个 middleware 任务）。本批完成全部 9 个需要新写的 middleware（todo / memory / sandbox_audit 已在前面阶段完成）。
>
> **第四批范围（5.6）**：
> - 9 个 L2 业务特性 middleware，全部按 ADR-010 重写
> - 业务耦合点（PathProvider / SandboxProvider / 各种 config）通过 Protocol/参数注入
>
> **不在第四批范围（后续批次）**：
> - 5.5 集成子系统（MCP / Skills / Guardrails 完整中间件）
> - 5.7 Sandbox 工具实现（1582 行）
> - 5.8 middleware 链装配（L2 特性 wire-up 到 `RuntimeFeatures` + `create_agent`）

## 任务清单

- [x] 5.6.1 `SubagentLimitMiddleware` - 截断超 `max_concurrent` 的 `task` tool calls
- [x] 5.6.2 `ThreadDataMiddleware` - 填充 `thread_data` slot（PathProvider 注入 + lazy_init）
- [x] 5.6.3 `UploadsMiddleware` - 注入 `<uploaded_files>` 块（PathProvider + virtual_prefix 注入）
- [x] 5.6.4 `SandboxMiddleware` - 使用 5.3 的 `SandboxProvider` 抽象
- [x] 5.6.5 `ViewImageMiddleware` - view_image 工具完成后注入图片细节
- [x] 5.6.6 `TitleMiddleware` - 自动 thread title 生成
- [x] 5.6.7 `ClarificationMiddleware` - 拦截 ask_clarification 工具调用
- [x] 5.6.8 `LLMErrorHandlingMiddleware` - retry + 熔断器
- [x] 5.6.9 `SummarizationMiddleware` - token trigger + 自定义 partitioner（skill rescue 入口）
- [x] 5.6.10 单元测试（9 个测试文件 / 112 个用例）
- [x] 5.6.11 验证：ruff + pytest + ADR-010

## 设计要点

### 1. SubagentLimitMiddleware

- 7 个抽象方法之外；`max_concurrent` clamp 到 `[2, 4]`（与 backend `MAX_CONCURRENT_SUBAGENTS = 3` 对齐）
- 截断策略：保留前 N 个 `task` tool calls（声明顺序），丢弃剩余
- `model_copy(update={"tool_calls": ...})` 保留 id 触发 langgraph 替换而非追加

### 2. ThreadDataMiddleware

- `PathProvider` 注入（不读全局 config）
- `lazy_init=True`（默认）：只计算路径；目录按需创建
- `lazy_init=False`：eager mkdir
- 为最后 HumanMessage 注入 `run_id` / `timestamp` metadata

### 3. UploadsMiddleware

- 接受 `PathProvider` + `virtual_prefix` 注入
- 构造 `<uploaded_files>` 块（包含 size + path + 用法提示）
- 保留 multimodal content（string 和 list[dict] 两种）
- 拒绝 `..` 风格 filename

### 4. SandboxMiddleware

- 使用 5.3 的 `SandboxProvider` ABC
- `lazy_init` 支持（与 ThreadData 对齐）
- before_agent acquire / after_agent release
- 优先 release state 中的 sandbox，回退到 context 中的 sandbox_id

### 5. ViewImageMiddleware

- 检测 `view_image` 工具调用 + ToolMessage 配对
- 构造 multimodal HumanMessage（text + image_url blocks）
- 标记字符串 `Here are the images you've viewed` 防重复注入
- 清空 `viewed_images` reducer（避免下一轮重复）

### 6. TitleMiddleware

- `model_factory` Callable 注入（async 路径）
- sync 路径永远走本地 fallback（`_fallback_title`），不阻塞 agent loop
- async 路径先 LLM，失败 fallback
- `TitlePrompts` 接受 `prompt_template` / `max_words` / `max_chars` / `fallback_max_chars`

### 7. ClarificationMiddleware

- 拦截 `ask_clarification` 工具调用（tool_name 可配置）
- 返回 `Command(goto=END, update={"messages": [ToolMessage]})` 中断
- 稳定 message id（基于 tool_call_id 或内容 hash），retried call 替换而非追加
- 多种 `clarification_type` 映射图标

### 8. LLMErrorHandlingMiddleware

- `RetryConfig` + `CircuitBreakerConfig` dataclass 注入
- 错误分类：quota / auth / busy / transient / generic
- 指数退避（cap=`cap_delay_ms`）
- retry-after 头解析（Retry-After-Ms / Retry-After）
- Circuit breaker：closed → open → half_open（仅允许一个 probe）
- 流式 `llm_retry` 事件发射
- `GraphBubbleUp` 透传（保留 langgraph 控制流）

### 9. SummarizationMiddleware

- **不**继承 langchain `SummarizationMiddleware`（基类是 sealed 的，私有方法不可用）
- 独立实现：`_count_tokens_approx` + `_determine_cutoff_index` + `_maybe_summarise`
- `message_partitioner` Callable 注入（默认 `default_partitioner`）
- `BeforeSummarizationHook` Protocol + `SummarizationEvent` 数据类
- skill rescue 通过 partitioner 实现，DeerFlow preset 接入

## 产出

```
agent_sdk/
├── middlewares/
│   ├── subagent_limit.py        # 新增
│   ├── thread_data.py           # 新增
│   ├── uploads.py               # 新增
│   ├── view_image.py            # 新增
│   ├── title.py                 # 新增
│   ├── clarification.py         # 新增
│   ├── llm_error.py             # 新增
│   ├── summarization.py         # 新增
│   └── __init__.py              # 更新
└── sandbox/
    ├── middleware.py            # 新增
    └── __init__.py              # 更新

tests/
├── middlewares/
│   ├── test_subagent_limit.py   # 新增
│   ├── test_thread_data.py      # 新增
│   ├── test_uploads.py          # 新增
│   ├── test_view_image.py       # 新增
│   ├── test_title.py            # 新增
│   ├── test_clarification.py    # 新增
│   ├── test_llm_error.py        # 新增
│   └── test_summarization.py    # 新增
└── sandbox/
    └── test_middleware.py       # 新增
```

## 完成标准

- [x] 5.6 所有任务完成
- [x] ruff check 全部通过
- [x] pytest 100% 通过（累计 724/724）
- [x] 0 处 import `backend.*` / `deerflow.*` / `app.*`
- [x] `backend/` 全程未触碰

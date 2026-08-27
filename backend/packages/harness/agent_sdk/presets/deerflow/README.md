# DeerFlow Preset

The DeerFlow preset bundles DeerFlow's business choices into a single `DeerFlowAgent` convenience class.

## Quick Start

```python
from agent_sdk.presets.deerflow import DeerFlowAgent

agent = DeerFlowAgent(
    model=my_chat_model,
    plan_mode=True,
)
result = await agent.ainvoke({
    "messages": [{"role": "user", "content": "Hello!"}]
})
```

## What's Included

| Component | Implementation | Description |
|-----------|---------------|-------------|
| Path provider | `DeerFlowPathProvider` | `/mnt/user-data` layout with workspace/uploads/outputs |
| Memory schema | `DeerFlowMemorySchema` | Three-section model (workContext / personalContext / topOfMind) |
| Subagent registry | `DeerFlowSubagentRegistry` | `general-purpose` and `bash` roles |
| Audit rules | `DeerFlowAuditRules` | 15 high-risk + 5 medium-risk sandbox command rules |
| System prompt | `SYSTEM_PROMPT_TEMPLATE` | Full DeerFlow system prompt (~700 lines) |
| Todo prompts | `DEERFLOW_TODO_PROMPTS` | DeerFlow's task-list wording |

## Default Features

```python
DEERFLOW_DEFAULT_FEATURES = RuntimeFeatures(
    sandbox=True,
    subagent=True,
    vision=True,
    auto_title=True,
    skills=True,
    memory=False,        # opt-in
    summarization=False,  # opt-in
)
```

## Configuration

### Minimal (sandbox-only)

```python
agent = DeerFlowAgent(model=model)
```

This enables sandbox + subagent + vision + auto_title + skills with DeerFlow defaults.

### With Memory

```python
agent = DeerFlowAgent(
    model=model,
    memory_storage=my_memory_storage,
    features=RuntimeFeatures(
        sandbox=True,
        memory=True,
        subagent=True,
        vision=True,
        auto_title=True,
        skills=True,
    ),
)
```

### With Custom Sandbox Provider

```python
agent = DeerFlowAgent(
    model=model,
    sandbox_provider=my_docker_sandbox_provider,
)
```

### Custom System Prompt

```python
agent = DeerFlowAgent(
    model=model,
    system_prompt="You are a helpful assistant.",
)
```

### Full Takeover (custom middleware)

```python
agent = DeerFlowAgent(
    model=model,
    middleware=[MyMiddleware1(), MyMiddleware2()],
)
```

## API

### `DeerFlowAgent`

| Method | Description |
|--------|-------------|
| `graph` | Compiled LangGraph agent (built lazily) |
| `ainvoke(input, config)` | Async invocation |
| `invoke(input, config)` | Sync invocation |
| `astream(input, config)` | Async streaming |
| `stream(input, config)` | Sync streaming |

### Key Constructor Args

| Arg | Default | Description |
|-----|---------|-------------|
| `model` | *(required)* | LangChain chat model |
| `tools` | `None` | User-provided tools |
| `features` | `DEERFLOW_DEFAULT_FEATURES` | Feature flags |
| `system_prompt` | DeerFlow default | System prompt |
| `agent_name` | `"DeerFlow 2.0"` | Display name |
| `plan_mode` | `False` | Enable task-list tracking |
| `path_provider` | `DeerFlowPathProvider()` | Path provider |
| `sandbox_provider` | `None` | Sandbox provider |
| `memory_storage` | `None` | Memory storage backend |
| `summarization_model` | `None` | Model for summarization |

## Backward Compatibility

This preset preserves byte-level behavioral equivalence with the original `backend.packages.harness.deerflow` package. It is a re-implementation (per ADR-010) — it does **not** import from `backend.*`, `deerflow.*`, or `app.*`.

## Extending

To create a custom preset, subclass or compose `DeerFlowAgent`:

```python
class MyAgent(DeerFlowAgent):
    def __post_init__(self):
        super().__post_init__()
        self.extra_middleware = [MyCustomMiddleware()]
```

Or use the lower-level `create_agent()` + `MiddlewareChainConfig` API directly (see `agent_sdk.runtime`).

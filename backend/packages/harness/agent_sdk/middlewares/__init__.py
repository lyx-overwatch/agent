"""Built-in middlewares for the agent runtime.

The :mod:`agent_sdk.middlewares` package hosts the
feature-rich middlewares that ship with the SDK. Each middleware
exposes a brand-neutral Protocol/parameter surface so that
project-specific behaviour (audit policy, prompt wording, …) is
injected at construction time.

**Layer split**

* **Always-on** (stage 5.2): middlewares that are
  always on, with no brand-specific assumptions:
  :class:`DanglingToolCallMiddleware`,
  :class:`ToolErrorHandlingMiddleware`,
  :class:`TokenUsageMiddleware`,
  :class:`LoopDetectionMiddleware`,
  :class:`StateSizeMonitorMiddleware`,
  :class:`DeferredToolFilterMiddleware`.
* **Feature middleware** (stage 5.6): middlewares whose
  behaviour is parameterised by a Protocol (e.g.
  :class:`agent_sdk.sandbox.audit.AuditRules`,
  :class:`agent_sdk.memory.schema.MemorySchema`).
  Includes:

  - :class:`SubagentLimitMiddleware`
  - :class:`ThreadDataMiddleware`
  - :class:`UploadsMiddleware`
  - :class:`ViewImageMiddleware`
  - :class:`TitleMiddleware`
  - :class:`SummarizationMiddleware`
  - :class:`ClarificationMiddleware`
  - :class:`LLMErrorHandlingMiddleware`
"""

from agent_sdk.middlewares import todo
from agent_sdk.middlewares.clarification import ClarificationMiddleware
from agent_sdk.middlewares.dangling_tool_call import DanglingToolCallMiddleware
from agent_sdk.middlewares.deferred_tool_filter import DeferredToolFilterMiddleware
from agent_sdk.middlewares.llm_error import (
    CircuitBreakerConfig,
    LLMErrorHandlingMiddleware,
    RetryConfig,
)
from agent_sdk.middlewares.loop_detection import LoopDetectionMiddleware
from agent_sdk.middlewares.model_call_capture import ModelCallCaptureMiddleware
from agent_sdk.middlewares.state_size_monitor import StateSizeMonitorMiddleware
from agent_sdk.middlewares.subagent_limit import SubagentLimitMiddleware
from agent_sdk.middlewares.summarization import (
    BeforeSummarizationHook,
    SummarizationEvent,
    SummarizationMiddleware,
)
from agent_sdk.middlewares.thread_data import ThreadDataMiddleware
from agent_sdk.middlewares.title import (
    TitleMiddleware,
    TitleModelFactory,
    TitlePrompts,
)
from agent_sdk.middlewares.token_usage import TokenUsageMiddleware
from agent_sdk.middlewares.tool_error_handling import ToolErrorHandlingMiddleware
from agent_sdk.middlewares.uploads import UploadsMiddleware
from agent_sdk.middlewares.view_image import ViewImageMiddleware

__all__ = [
    # always-on
    "DanglingToolCallMiddleware",
    "ToolErrorHandlingMiddleware",
    "TokenUsageMiddleware",
    "LoopDetectionMiddleware",
    "StateSizeMonitorMiddleware",
    "DeferredToolFilterMiddleware",
    # feature middleware
    "ClarificationMiddleware",
    "SubagentLimitMiddleware",
    "SummarizationMiddleware",
    "ThreadDataMiddleware",
    "TitleMiddleware",
    "UploadsMiddleware",
    "ViewImageMiddleware",
    "LLMErrorHandlingMiddleware",
    "ModelCallCaptureMiddleware",
    # data classes / protocols
    "CircuitBreakerConfig",
    "RetryConfig",
    "BeforeSummarizationHook",
    "SummarizationEvent",
    "TitleModelFactory",
    "TitlePrompts",
    # Subpackage
    "todo",
]

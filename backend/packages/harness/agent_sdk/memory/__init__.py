"""Memory subsystem for agent runtime.

Defines the :class:`MemorySchema` Protocol — the brand-neutral injection
point for long-term memory data models. The SDK ships with a minimal
:class:`DefaultMemorySchema` (a free-form key/value bag with no
product-specific shape), and the DeerFlow preset provides
:class:`DeerFlowMemorySchema` that preserves the
``workContext / personalContext / topOfMind`` three-section model.
"""

from agent_sdk.memory.default import DefaultMemorySchema
from agent_sdk.memory.middleware import MemoryMiddleware
from agent_sdk.memory.schema import MemorySchema
from agent_sdk.memory.storage import FileMemoryStorage, MemoryStorage
from agent_sdk.memory.updater import MemoryUpdater

__all__ = [
    "MemorySchema",
    "DefaultMemorySchema",
    "MemoryStorage",
    "FileMemoryStorage",
    "MemoryMiddleware",
    "MemoryUpdater",
]

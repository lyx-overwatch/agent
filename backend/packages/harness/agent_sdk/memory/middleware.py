"""MemoryMiddleware — injects the user profile into the system prompt.

This is a re-implementation (per ADR-010) of
``backend.agents.middlewares.memory_middleware.MemoryMiddleware``.

The middleware:
1. **before_agent**: Loads the memory schema from storage and injects
   the user profile + conversation history into the agent state.
2. **after_agent**: Persists the memory state back to storage so that
   any updates made during the agent run (via MemoryUpdater) are saved.
"""

from __future__ import annotations

import logging
from typing import Any, Generic, TypeVar, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from agent_sdk.memory.schema import MemorySchema
from agent_sdk.memory.storage import MemoryStorage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=MemorySchema)


class MemoryMiddlewareState(AgentState):
    """State schema for the memory middleware."""

    memory: dict[str, Any] | None


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState], Generic[T]):
    """Injects the user profile into the system prompt and persists memory.

    Args:
        memory_schema_cls: The :class:`MemorySchema` subclass used
            to load and store memory (e.g. ``DeerFlowMemorySchema``).
        storage: A :class:`MemoryStorage` instance — knows where
            the memory file lives.
    """

    state_schema = MemoryMiddlewareState

    def __init__(
        self,
        memory_schema_cls: type[T],
        storage: MemoryStorage[T],
    ) -> None:
        super().__init__()
        self._schema_cls = memory_schema_cls
        self._storage = storage

    def _load_schema(self) -> T:
        """Load the memory schema, falling back to an empty schema on error."""
        try:
            return self._storage.load()
        except Exception:
            logger.warning("Failed to load memory; using empty schema", exc_info=True)
            return self._schema_cls.empty()

    def before_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Load memory and inject the user profile."""
        schema = self._load_schema()
        profile = schema.get_user_profile()
        return {
            "memory": {
                "user_profile": profile,
                "conversation_history": schema.get_conversation_history(),
            }
        }

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Persist memory state after agent execution.

        If the memory state was modified during the agent run (e.g. by a
        :class:`MemoryUpdater`), this writes the changes back to storage.
        """
        memory_state = state.get("memory") if state else None
        if memory_state is None:
            return None

        try:
            schema = self._load_schema()
            data = schema.to_dict()
            updated = False

            if "user_profile" in memory_state and memory_state["user_profile"]:
                data["userProfile"] = memory_state["user_profile"]
                updated = True
            if "conversation_history" in memory_state and memory_state["conversation_history"]:
                data["conversationHistory"] = memory_state["conversation_history"]
                updated = True

            if updated:
                new_schema = self._schema_cls.from_dict(data)
                if hasattr(new_schema, "touch"):
                    new_schema.touch()  # type: ignore[attr-defined]
                if not self._storage.save(new_schema):
                    logger.warning("Failed to save memory after agent execution")
        except Exception:
            logger.warning("Failed to persist memory after agent", exc_info=True)

        return None

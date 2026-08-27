"""LangGraph checkpointer factory.

This package is a re-implementation (per ADR-010) of
``deerflow.runtime.checkpointer``.  It provides:

* :class:`CheckpointerConfig` — declarative configuration
  for selecting a backend.
* :func:`make_checkpointer` — async context manager that
  yields a configured :class:`langgraph.types.Checkpointer`.
* :func:`checkpointer_context` — sync context manager.
* :func:`get_checkpointer` / :func:`reset_checkpointer` —
  process-wide sync singleton with explicit reset.

Supported backends: ``memory`` (in-process, lost on restart),
``sqlite`` (file-backed, requires ``langgraph-checkpoint-sqlite``),
``postgres`` (DSN-backed, requires ``langgraph-checkpoint-postgres``).

Heavy backends (sqlite, postgres) are imported lazily so the
base install only needs ``langgraph``.  When the optional
package is not installed, the factory raises :class:`ImportError`
with a clear ``uv add`` hint — never a bare
:exc:`ModuleNotFoundError`.
"""

from agent_sdk.runtime.checkpointer.async_factory import make_checkpointer
from agent_sdk.runtime.checkpointer.config import (
    CheckpointerConfig,
    CheckpointerType,
)
from agent_sdk.runtime.checkpointer.factory import (
    checkpointer_context,
    get_checkpointer,
    reset_checkpointer,
)

__all__ = [
    "CheckpointerConfig",
    "CheckpointerType",
    "checkpointer_context",
    "get_checkpointer",
    "make_checkpointer",
    "reset_checkpointer",
]

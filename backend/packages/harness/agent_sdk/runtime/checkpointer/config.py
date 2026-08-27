"""Checkpointer configuration data classes.

This module is brand-neutral — it depends only on
:mod:`pydantic` and the standard library.  The factory
modules consume :class:`CheckpointerConfig` to decide which
backend to construct.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Supported checkpointer backends.
CheckpointerType = Literal["memory", "sqlite", "postgres"]


class CheckpointerConfig(BaseModel):
    """Configuration for a LangGraph state-persistence checkpointer.

    Attributes:
        type: Backend type. ``"memory"`` is in-process only
            (lost on restart). ``"sqlite"`` persists to a
            local file (requires ``langgraph-checkpoint-sqlite``).
            ``"postgres"`` persists to PostgreSQL (requires
            ``langgraph-checkpoint-postgres``).
        connection_string: Connection string for ``sqlite``
            (a file path) or ``postgres`` (a DSN).  Required
            for ``sqlite`` and ``postgres``; ignored for
            ``memory``.  Use ``":memory:"`` for an in-memory
            SQLite database.
    """

    type: CheckpointerType = Field(
        default="memory",
        description="Checkpointer backend type.",
    )
    connection_string: str | None = Field(
        default=None,
        description="Connection string for sqlite (file path) or postgres (DSN).",
    )

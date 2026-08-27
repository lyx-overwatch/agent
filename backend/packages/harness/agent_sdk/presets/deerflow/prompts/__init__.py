"""DeerFlow preset: prompt bundles for SDK middlewares.

The :mod:`agent_sdk.presets.deerflow.prompts` package hosts
project-specific prompt wording for the SDK middlewares that
take a :class:`Prompts` dataclass. Each sub-module re-records
the wording (per ADR-010) rather than importing it from
``backend.*``.
"""

from agent_sdk.presets.deerflow.prompts import system, todo

__all__ = ["system", "todo"]

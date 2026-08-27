"""Path management for agent runtime.

Defines the :class:`PathProvider` Protocol and default implementations for
resolving runtime paths (workspace, uploads, outputs, skills).

The :class:`PathProvider` Protocol is the brand-neutral injection point for
path configuration. The SDK ships with a :class:`DefaultPathProvider` that
makes no business assumptions, and the DeerFlow preset provides
:class:`DeerFlowPathProvider` that preserves the ``/mnt/user-data`` style
paths.
"""

from agent_sdk.paths.default import DefaultPathProvider
from agent_sdk.paths.provider import PathProvider
from agent_sdk.paths.resolver import VirtualPathResolver

__all__ = [
    "PathProvider",
    "DefaultPathProvider",
    "VirtualPathResolver",
]

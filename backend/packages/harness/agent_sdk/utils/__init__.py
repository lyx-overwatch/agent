"""Generic utilities used across the SDK.

This package hosts small, dependency-free helpers that are
re-used by multiple subsystems.  Heavier utilities that pull in
optional third-party packages (PDF/Office conversion, HTML
readability extraction) are intentionally **not** included in
this first cut — they are scheduled for a follow-up batch as
optional extras so the base install stays slim.
"""

from agent_sdk.utils.network import (
    PortAllocator,
    get_free_port,
    release_port,
)
from agent_sdk.utils.thread import extract_thread_id, resolve_thread_id

__all__ = [
    "PortAllocator",
    "extract_thread_id",
    "get_free_port",
    "release_port",
    "resolve_thread_id",
]

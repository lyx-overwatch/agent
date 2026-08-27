"""Community-contributed modules for agent_sdk.

This directory contains optional, community-maintained integrations
that are not part of the core agent_sdk contract.  Each sub-package
may have its own optional dependencies.

Current modules:
* :mod:`agent_sdk.community.aio_sandbox` — Docker-based AIO sandbox provider
* :mod:`agent_sdk.community.skillhub` — SkillHub's built-in subagent roles and runner
"""

# Community modules are loaded lazily — importing this package does not
# trigger any optional-dependency imports.
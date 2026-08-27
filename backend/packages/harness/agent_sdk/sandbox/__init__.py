"""Sandbox subsystem for the agent runtime.

The :mod:`agent_sdk.sandbox` package hosts the security and
audit machinery that runs in front of command-execution
tools (e.g. ``bash``), plus the path / host / file-operation
helpers they depend on. The runtime is brand-neutral: it
consumes an :class:`agent_sdk.sandbox.audit.AuditRules`
Protocol so each product can supply its own rule set, and
:class:`SandboxPathResolver` / :class:`HostBashPolicy`
so each product can wire in its own path policy and host
bash gate.

Layout::

    agent_sdk.sandbox
    ├── base            Sandbox + SandboxProvider ABCs, GrepMatch
    ├── exceptions      SandboxError hierarchy
    ├── search          glob / grep helpers
    ├── file_operation_lock
    ├── security        HostBashPolicy
    ├── path_resolver   SandboxPathResolver + SandboxToolsConfig
    ├── tools           make_sandbox_tools factory + SandboxToolsBundle
    ├── middleware      SandboxMiddleware (lifecycle)
    └── audit           AuditRules + SandboxAuditMiddleware
"""

from agent_sdk.sandbox.audit import (
    AuditPattern,
    AuditRules,
    AuditVerdict,
    DefaultAuditRules,
    SandboxAuditMiddleware,
)
from agent_sdk.sandbox.base import GrepMatch, Sandbox, SandboxProvider
from agent_sdk.sandbox.exceptions import (
    SandboxCommandError,
    SandboxError,
    SandboxFileError,
    SandboxFileNotFoundError,
    SandboxNotFoundError,
    SandboxPermissionError,
    SandboxRuntimeError,
)
from agent_sdk.sandbox.file_operation_lock import (
    get_file_operation_lock,
    get_file_operation_lock_key,
)
from agent_sdk.sandbox.middleware import SandboxMiddleware, SandboxMiddlewareState
from agent_sdk.sandbox.path_resolver import (
    CustomMount,
    SandboxPathResolver,
    SandboxToolsConfig,
    get_path_resolver,
    reset_path_resolver,
    set_path_resolver,
)
from agent_sdk.sandbox.search import (
    DEFAULT_LINE_SUMMARY_LENGTH,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    IGNORE_PATTERNS,
    find_glob_matches,
    find_grep_matches,
    is_binary_file,
    path_matches,
    should_ignore_name,
    should_ignore_path,
    truncate_line,
)
from agent_sdk.sandbox.security import (
    DEFAULT_HOST_BASH_POLICY_FACTORY,
    LOCAL_BASH_DISABLED_MESSAGE_FALLBACK,
    LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE,
    LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK,
    LOCAL_HOST_BASH_DISABLED_MESSAGE,
    ConfigurableHostBashPolicy,
    DefaultHostBashPolicy,
    HostBashPolicy,
    default_host_bash_policy,
)
from agent_sdk.sandbox.tools import SandboxToolsBundle, make_sandbox_tools

__all__ = [
    # audit subsystem
    "AuditPattern",
    "AuditRules",
    "AuditVerdict",
    "DefaultAuditRules",
    "SandboxAuditMiddleware",
    # sandbox base ABCs
    "GrepMatch",
    "Sandbox",
    "SandboxProvider",
    # sandbox lifecycle middleware
    "SandboxMiddleware",
    "SandboxMiddlewareState",
    # exceptions
    "SandboxError",
    "SandboxNotFoundError",
    "SandboxRuntimeError",
    "SandboxCommandError",
    "SandboxFileError",
    "SandboxPermissionError",
    "SandboxFileNotFoundError",
    # file operation locks
    "get_file_operation_lock",
    "get_file_operation_lock_key",
    # path resolver / config
    "CustomMount",
    "SandboxPathResolver",
    "SandboxToolsConfig",
    "get_path_resolver",
    "set_path_resolver",
    "reset_path_resolver",
    # search helpers
    "DEFAULT_LINE_SUMMARY_LENGTH",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "IGNORE_PATTERNS",
    "find_glob_matches",
    "find_grep_matches",
    "is_binary_file",
    "path_matches",
    "should_ignore_name",
    "should_ignore_path",
    "truncate_line",
    # security policy
    "ConfigurableHostBashPolicy",
    "DefaultHostBashPolicy",
    "HostBashPolicy",
    "LOCAL_BASH_DISABLED_MESSAGE_FALLBACK",
    "LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE",
    "LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK",
    "LOCAL_HOST_BASH_DISABLED_MESSAGE",
    "default_host_bash_policy",
    "DEFAULT_HOST_BASH_POLICY_FACTORY",
    # tools factory
    "SandboxToolsBundle",
    "make_sandbox_tools",
]

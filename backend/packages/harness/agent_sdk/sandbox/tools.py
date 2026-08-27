"""Sandbox tools for the agent runtime.

This module is a re-implementation (per ADR-010) of
``deerflow.sandbox.tools``. The seven ``@tool``-decorated
functions (``bash``/``ls``/``glob``/``grep``/``read_file``/
``write_file``/``str_replace``) are bundled behind a
single factory :func:`make_sandbox_tools` that takes a
:class:`SandboxProvider`, a :class:`SandboxPathResolver`,
and an optional :class:`HostBashPolicy`. The factory closes
over all three so the tools stay brand-neutral and free of
global state.

The seven tool names are the canonical backend names — the
factory takes an optional ``name_prefix`` argument so a
product that wants a different namespace (``"df_bash"`` etc.)
can keep its own convention without modifying the SDK.

The on-host ``/mnt/user-data`` virtual prefix and any custom
mount container paths are all configured via
:class:`SandboxToolsConfig` (see
:mod:`agent_sdk.sandbox.path_resolver`).

Skills are NOT accessed through sandbox tools — use the
``read_skill`` tool instead, which reads directly from the
host filesystem.

Wire-up example::

    from agent_sdk.sandbox import (
        LocalSandboxProvider,           # product-specific
        SandboxPathResolver,
        SandboxToolsConfig,
        make_sandbox_tools,
    )

    config = SandboxToolsConfig(
        virtual_path_prefix="/mnt/user-data",
    )
    resolver = SandboxPathResolver(config)
    provider = LocalSandboxProvider()    # product-specific

    tools = make_sandbox_tools(
        sandbox_provider=provider,
        resolver=resolver,
    )
    # tools.bash / tools.ls / ... are langchain BaseTool instances
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from langchain.tools import BaseTool, ToolRuntime, tool

from agent_sdk.sandbox.base import GrepMatch, Sandbox, SandboxProvider
from agent_sdk.sandbox.exceptions import (
    SandboxError,
    SandboxNotFoundError,
    SandboxRuntimeError,
)
from agent_sdk.sandbox.file_operation_lock import get_file_operation_lock
from agent_sdk.sandbox.path_resolver import SandboxPathResolver
from agent_sdk.sandbox.security import (
    DEFAULT_HOST_BASH_POLICY_FACTORY,
    HostBashPolicy,
)
from agent_sdk.utils.thread import extract_thread_id

# ``@tool`` evaluates forward references at decoration time even with
# ``from __future__ import annotations``, and ``ToolRuntime[ContextT, "ThreadState"]``
# cannot resolve ``"ThreadState"`` against the module globals.  Use a plain
# ``ToolRuntime`` annotation at runtime; the type checker's view is unaffected.
_RuntimeType = ToolRuntime  # type: ignore[assignment,misc]


#: Default cap on ``glob`` results. Matches backend.
_DEFAULT_GLOB_MAX_RESULTS = 200

#: Hard ceiling on ``glob`` results after user request + config merge.
_MAX_GLOB_MAX_RESULTS = 1000

#: Default cap on ``grep`` results. Matches backend.
_DEFAULT_GREP_MAX_RESULTS = 100

#: Hard ceiling on ``grep`` results after user request + config merge.
_MAX_GREP_MAX_RESULTS = 500


# ---------------------------------------------------------------------------
# Bundle — returned by :func:`make_sandbox_tools`
# ---------------------------------------------------------------------------


@dataclass
class SandboxToolsBundle:
    """The seven sandbox tool instances, ready to register with an agent.

    Each attribute is a langchain :class:`BaseTool` produced
    by the ``@tool`` decorator. The names match the backend
    defaults (``bash``/``ls``/``glob``/``grep``/``read_file``/
    ``write_file``/``str_replace``) unless the caller passed a
    ``name_prefix``.
    """

    bash: BaseTool
    ls: BaseTool
    glob: BaseTool
    grep: BaseTool
    read_file: BaseTool
    write_file: BaseTool
    str_replace: BaseTool


# ---------------------------------------------------------------------------
# Output truncation helpers (verbatim from backend)
# ---------------------------------------------------------------------------


def _truncate_bash_output(output: str, max_chars: int) -> str:
    """Middle-truncate bash output, preserving head and tail (50/50 split)."""
    if max_chars == 0:
        return output
    if len(output) <= max_chars:
        return output
    total_len = len(output)
    marker_max_len = len(f"\n... [middle truncated: {total_len} chars skipped] ...\n")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return output[:max_chars]
    head_len = kept // 2
    tail_len = kept - head_len
    skipped = total_len - kept
    marker = f"\n... [middle truncated: {skipped} chars skipped] ...\n"
    return f"{output[:head_len]}{marker}{output[-tail_len:] if tail_len > 0 else ''}"


def _truncate_read_file_output(output: str, max_chars: int) -> str:
    """Head-truncate read_file output, preserving the beginning of the file."""
    if max_chars == 0:
        return output
    if len(output) <= max_chars:
        return output
    total = len(output)
    marker_max_len = len(f"\n... [truncated: showing first {total} of {total} chars. Use start_line/end_line to read a specific range] ...")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return output[:max_chars]
    marker = f"\n... [truncated: showing first {kept} of {total} chars. Use start_line/end_line to read a specific range] ..."
    return f"{output[:kept]}{marker}"


def _truncate_ls_output(output: str, max_chars: int) -> str:
    """Head-truncate ls output, preserving the beginning of the listing."""
    if max_chars == 0:
        return output
    if len(output) <= max_chars:
        return output
    total = len(output)
    marker_max_len = len(f"\n... [truncated: showing first {total} of {total} chars. Use a more specific path to see fewer results] ...")
    kept = max(0, max_chars - marker_max_len)
    if kept == 0:
        return output[:max_chars]
    marker = f"\n... [truncated: showing first {kept} of {total} chars. Use a more specific path to see fewer results] ..."
    return f"{output[:kept]}{marker}"


def _format_glob_results(root_path: str, matches: list[str], truncated: bool) -> str:
    if not matches:
        return f"No files matched under {root_path}"

    lines = [f"Found {len(matches)} paths under {root_path}"]
    if truncated:
        lines[0] += f" (showing first {len(matches)})"
    lines.extend(f"{index}. {path}" for index, path in enumerate(matches, start=1))
    if truncated:
        lines.append("Results truncated. Narrow the path or pattern to see fewer matches.")
    return "\n".join(lines)


def _format_grep_results(root_path: str, matches: list[GrepMatch], truncated: bool) -> str:
    if not matches:
        return f"No matches found under {root_path}"

    lines = [f"Found {len(matches)} matches under {root_path}"]
    if truncated:
        lines[0] += f" (showing first {len(matches)})"
    lines.extend(f"{match.path}:{match.line_number}: {match.line}" for match in matches)
    if truncated:
        lines.append("Results truncated. Narrow the path or add a glob filter.")
    return "\n".join(lines)


def _clamp_max_results(value: int, *, default: int, upper_bound: int) -> int:
    if value <= 0:
        return default
    return min(value, upper_bound)


def _resolve_max_results(
    name: str,
    requested: int,
    *,
    default: int,
    upper_bound: int,
    config_upper: int | None = None,
) -> int:
    """Merge the requested cap with the resolver's per-tool default.

    Args:
        name: Tool name (``"glob"`` / ``"grep"``) — kept for
            symmetry with the backend signature and future
            per-tool audit logging.
        requested: The user-requested cap (from the tool call).
        default: The hard-coded SDK default when ``requested <= 0``.
        upper_bound: The hard ceiling (e.g. 1000 for ``glob``).
        config_upper: Optional per-tool upper bound supplied via
            :class:`SandboxToolsConfig` (e.g.
            ``config.glob_max_results_upper``). When set, the
            effective upper bound is ``min(upper_bound, config_upper)``
            — letting a product clamp glob/grep results below the
            hard ceiling.
    """
    requested_max_results = _clamp_max_results(requested, default=default, upper_bound=upper_bound)
    effective_upper = config_upper if config_upper is not None else upper_bound
    return min(requested_max_results, effective_upper)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_sandbox_tools(
    *,
    sandbox_provider: SandboxProvider,
    resolver: SandboxPathResolver,
    host_bash_policy: HostBashPolicy | None = None,
    name_prefix: str = "",
) -> SandboxToolsBundle:
    """Build the seven sandbox tools closed over the given dependencies.

    Args:
        sandbox_provider: Used to acquire / get sandboxes
            per thread. The provider is consulted lazily
            (when the first tool call arrives) and then the
            sandbox id is stashed in ``runtime.state`` for
            subsequent calls.
        resolver: Encapsulates all path policy — virtual
            prefix, skills, custom mounts, per-tool max-char
            defaults, and the MCP allowed paths provider.
        host_bash_policy: Decides whether host-side bash
            execution is allowed. Defaults to the safe
            ``DefaultHostBashPolicy`` (always deny).
        name_prefix: Optional prefix prepended to each tool
            name. ``""`` (default) preserves the backend
            names verbatim; ``"df_"`` would yield
            ``df_bash`` / ``df_ls`` / etc.

    Returns:
        A :class:`SandboxToolsBundle` holding the seven
        ``@tool``-decorated callables.
    """
    if host_bash_policy is None:
        host_bash_policy = DEFAULT_HOST_BASH_POLICY_FACTORY()

    # --- runtime helpers (close over sandbox_provider) ---

    def _is_local_sandbox(runtime: ToolRuntime | None) -> bool:
        """Check whether the sandbox provider is a local (subprocess) provider.

        Uses the closed-over *sandbox_provider* instance rather than
        inspecting the ``sandbox_id`` string, which varies between
        implementations (the re-implemented
        :class:`~agent_sdk.sandbox.local.provider.LocalSandboxProvider`
        uses per-thread UUIDs, not the hardcoded ``"local"`` string).
        """
        from agent_sdk.sandbox.local.provider import LocalSandboxProvider

        return isinstance(sandbox_provider, LocalSandboxProvider)

    def _get_thread_data(runtime: ToolRuntime | None) -> dict | None:
        if runtime is None or runtime.state is None:
            return None
        return runtime.state.get("thread_data")

    def _try_get_sandbox(runtime: ToolRuntime | None) -> Sandbox | None:
        """Return the sandbox currently bound in *runtime* state, or ``None``.

        Does **not** acquire. Used by the bash tool to decide
        whether the policy check applies (no bound sandbox → check
        the policy) or whether to invoke an existing sandbox
        (bound sandbox → skip the policy).
        """
        if runtime is None or runtime.state is None:
            return None
        sandbox_state = runtime.state.get("sandbox")
        if sandbox_state is None:
            return None
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is None:
            return None
        return sandbox_provider.get(sandbox_id)

    def _ensure_sandbox(runtime: ToolRuntime | None) -> Sandbox:
        if runtime is None:
            raise SandboxRuntimeError("Tool runtime not available")
        if runtime.state is None:
            raise SandboxRuntimeError("Tool runtime state not available")

        sandbox_state = runtime.state.get("sandbox")
        if sandbox_state is not None:
            sandbox_id = sandbox_state.get("sandbox_id")
            if sandbox_id is not None:
                sandbox = sandbox_provider.get(sandbox_id)
                if sandbox is not None:
                    if runtime.context is not None:
                        runtime.context["sandbox_id"] = sandbox_id
                    return sandbox
                # Sandbox was released or lost — try to re-acquire it
                # using the known sandbox_id from state. For local
                # providers sandbox_id == thread_id, so acquire() is
                # idempotent. For Docker providers this re-claims the
                # same deterministic container.
                try:
                    reclaimed_id = sandbox_provider.acquire(sandbox_id)
                    runtime.state["sandbox"] = {"sandbox_id": reclaimed_id}
                    sandbox = sandbox_provider.get(reclaimed_id)
                    if sandbox is not None:
                        if runtime.context is not None:
                            runtime.context["sandbox_id"] = reclaimed_id
                        return sandbox
                except Exception:
                    pass
                # Re-acquire failed — fall through to thread_id resolution.

        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            thread_id = runtime.config.get("configurable", {}).get("thread_id") if runtime.config else None
        if thread_id is None:
            # Final fallback: extract thread_id from thread_data.workspace_path.
            # This covers subagent tool calls where runtime.config propagation
            # may be unreliable through langchain's ToolRuntime.
            thread_data = runtime.state.get("thread_data") if runtime.state else None
            if thread_data:
                thread_id = extract_thread_id(thread_data)
        if thread_id is None:
            raise SandboxRuntimeError("Thread ID not available in runtime context")

        sandbox_id = sandbox_provider.acquire(thread_id)

        # Preserve the "local" marker in state. The local tool layer
        # special-cases state["sandbox"]["sandbox_id"] == "local" to
        # decide whether to use the host file system; overwriting it
        # with the acquired id would silently disable that branch.
        # This is what makes tests like ``test_unknown_path_rejected``
        # work: they pre-acquire a "sb-1" sandbox then set
        # state["sandbox"]["sandbox_id"] = "local" to simulate a
        # caller that wants the tool layer to act as if local.
        if not (sandbox_state is not None and sandbox_state.get("sandbox_id") == "local"):
            runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

        sandbox = sandbox_provider.get(sandbox_id)
        if sandbox is None:
            raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

        if runtime.context is not None:
            runtime.context["sandbox_id"] = sandbox_id
        return sandbox

    def _ensure_thread_directories_exist(runtime: ToolRuntime | None) -> None:
        if runtime is None:
            return

        if not _is_local_sandbox(runtime):
            # ── AioSandbox (Docker / K8s) ──────────────────────────────
            # The sandbox Pod mounts an empty emptyDir at the virtual
            # prefix with no pre-created subdirectories.  Create
            # workspace/outputs/uploads eagerly on the first tool call so
            # the agent's writes — especially user deliverables under
            # outputs/ — don't fail with "No such file or directory".
            if runtime.state.get("thread_directories_created"):
                return
            sandbox = _try_get_sandbox(runtime)
            if sandbox is None:
                return
            prefix = resolver.virtual_path_prefix
            sandbox.execute_command(
                f"mkdir -p {prefix}/workspace {prefix}/outputs {prefix}/uploads"
            )
            runtime.state["thread_directories_created"] = True
            return

        thread_data = _get_thread_data(runtime)
        if thread_data is None:
            return

        if runtime.state.get("thread_directories_created"):
            return

        for key in ["workspace_path", "uploads_path", "outputs_path"]:
            path = thread_data.get(key)
            if path:
                os.makedirs(path, exist_ok=True)

        runtime.state["thread_directories_created"] = True

    def _sanitize_error(error: Exception, runtime: ToolRuntime | None = None) -> str:
        msg = f"{type(error).__name__}: {error}"
        if runtime is not None and _is_local_sandbox(runtime):
            thread_data = _get_thread_data(runtime)
            msg = resolver.mask_local_paths_in_output(msg, thread_data)
        return msg

    #: Regex matching bash write redirections: ``>``, ``>>``, ``>&``
    #: (possibly preceded by a file descriptor number like ``2>``).
    _BASH_WRITE_REDIR_RE = re.compile(r"(?:(?:\d)?>>?&?)\s*(\S+)")

    def _run_local_bash(runtime: ToolRuntime, command: str, *, sandbox: Sandbox, validate_paths: bool) -> str:
        """Run a bash command against a local sandbox.

        Args:
            runtime: The tool runtime (used for thread data + state).
            command: The bash command to execute.
            sandbox: A pre-resolved local sandbox (either freshly
                acquired or already bound in state).
            validate_paths: When ``True`` (fresh-acquire path), run
                ``validate_local_bash_command_paths`` (security
                gate). Virtual-path replacement + cwd prefix
                **always** run regardless of this flag — the LLM
                always emits virtual paths and they must be
                translated for the host filesystem.
        """
        _ensure_thread_directories_exist(runtime)
        thread_data = _get_thread_data(runtime)
        if validate_paths and thread_data is not None:
            resolver.validate_local_bash_command_paths(command, thread_data)
        # Virtual→physical path replacement and cwd prefix MUST always
        # run for local sandbox — the LLM uses virtual paths like
        # /mnt/user-data/workspace/ which don't exist on the host.
        if thread_data is not None:
            command = resolver.replace_virtual_paths_in_command(command, thread_data)
            command = resolver.apply_cwd_prefix(command, thread_data)
        output = sandbox.execute_command(command)
        if _is_local_sandbox(runtime):
            output = resolver.mask_local_paths_in_output(output, thread_data)
        return _truncate_bash_output(output, resolver.config.bash_output_max_chars)

    # --- tools ---

    bash_name = f"{name_prefix}bash"
    # Per ADR-011 the python venv hint is brand-neutral by default
    # (``"<virtual_path_prefix>/workspace/.venv"``). The DeerFlow
    # preset overrides this in phase 4 to ``"/mnt/user-data/workspace/.venv"``.
    # We close over the value so the docstring (used as the tool
    # description by the @tool(parse_docstring=True) decorator)
    # embeds the actual path at factory-build time.
    #
    # Note: f-strings in the function body are NOT recognised as
    # docstrings by Python (``__doc__`` stays ``None`` — f-strings
    # are JoinedStr, not a Constant). We therefore build the
    # docstring as a regular string variable and assign it to
    # ``__doc__`` after the @tool decorator runs.
    python_venv_hint = resolver.config.python_venv_hint
    _bash_doc = (
        "Execute a shell command.\n"
        "\n"
        "- Use `python` (NOT `python3`).\n"
        f"- Prefer venv at `{python_venv_hint}`; use `python -m pip` to install packages.\n"
        "- No background processes (`&`); servers timeout after 30s — use one-shot commands.\n"
        "\n"
        "Args:\n"
        "    description: Why you are running this command (short).\n"
        "    command: The shell command. Use absolute paths.\n"
    )

    # Real bash body — defined as a plain function (not via the
    # @tool decorator at the def site) so we can attach the
    # resolved ``_bash_doc`` (which embeds ``python_venv_hint``)
    # BEFORE the @tool decorator runs. f-strings in the function
    # body are NOT recognised as docstrings (Python 3.12 spec
    # limitation: ``__doc__`` is ``None`` for f-string bodies).
    def _bash_tool_impl(
        runtime: _RuntimeType, command: str, description: str = ""
    ) -> str:
        try:
            if _is_local_sandbox(runtime):
                # Always gate local bash behind the policy — even when a
                # sandbox is already bound by a prior non-bash tool call
                # (write_file / ls / …).  The local provider has no
                # isolation boundary; the policy must be consulted on
                # every command execution, not just on first bind.
                if not host_bash_policy.is_host_bash_allowed():
                    return f"Error: {host_bash_policy.disabled_message}"
                bound = _try_get_sandbox(runtime)
                sandbox = _ensure_sandbox(runtime)
                validate_paths = bound is None
                return _run_local_bash(runtime, command, sandbox=sandbox, validate_paths=validate_paths)
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            return _truncate_bash_output(
                sandbox.execute_command(command), resolver.config.bash_output_max_chars
            )
        except SandboxError as e:
            return f"Error: {e}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: Unexpected error executing command: {_sanitize_error(e, runtime)}"

    # Attach the resolved docstring (built above) and decorate.
    # The decorator runs AFTER ``__doc__`` is set, so it parses
    # the plain string correctly.
    _bash_tool_impl.__doc__ = _bash_doc
    bash_tool: BaseTool = tool(bash_name, parse_docstring=True)(_bash_tool_impl)
    del _bash_tool_impl  # namespacing tidy-up

    ls_name = f"{name_prefix}ls"

    @tool(ls_name, parse_docstring=True)
    def ls_tool(runtime: _RuntimeType, path: str, description: str = "") -> str:
        """List directory contents up to 2 levels deep in tree format.

        Args:
            description: Why you are listing this directory (short).
            path: Absolute path to the directory.
        """
        try:
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            requested_path = path
            thread_data = None
            if _is_local_sandbox(runtime):
                thread_data = _get_thread_data(runtime)
                resolver.validate_local_tool_path(path, thread_data, read_only=True)
                if resolver.is_skills_path(path):
                    path = resolver.resolve_skills_path(path)
                elif not resolver.is_custom_mount_path(path):
                    path = resolver.resolve_and_validate_user_data_path(path, thread_data)
                # Custom mount paths are resolved by the underlying sandbox.
            children = sandbox.list_dir(path)
            if not children:
                return "(empty)"
            output = "\n".join(children)
            if thread_data is not None:
                output = resolver.mask_local_paths_in_output(output, thread_data)
            return _truncate_ls_output(output, resolver.config.ls_output_max_chars)
        except SandboxError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return f"Error: Directory not found: {requested_path}"
        except PermissionError:
            return f"Error: Permission denied: {requested_path}"
        except Exception as e:
            return f"Error: Unexpected error listing directory: {_sanitize_error(e, runtime)}"

    glob_name = f"{name_prefix}glob"

    @tool(glob_name, parse_docstring=True)
    def glob_tool(
        runtime: _RuntimeType,
        pattern: str,
        path: str,
        include_dirs: bool = False,
        max_results: int = _DEFAULT_GLOB_MAX_RESULTS,
        description: str = "",
    ) -> str:
        """Find files/dirs matching a glob pattern under a root directory.

        Args:
            description: Why you are searching (short).
            pattern: Glob pattern relative to root, e.g. `**/*.py`.
            path: Absolute root directory to search under.
            include_dirs: Include matching directories. Default False.
            max_results: Max paths to return. Default 200.
        """
        try:
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            requested_path = path
            effective_max_results = _resolve_max_results(
                "glob",
                max_results,
                default=_DEFAULT_GLOB_MAX_RESULTS,
                upper_bound=_MAX_GLOB_MAX_RESULTS,
                config_upper=resolver.config.glob_max_results_upper,
            )
            thread_data = None
            if _is_local_sandbox(runtime):
                thread_data = _get_thread_data(runtime)
                if thread_data is None:
                    raise SandboxRuntimeError("Thread data not available for local sandbox")
                path = resolver.resolve_local_read_path(path, thread_data)
            matches, truncated = sandbox.glob(path, pattern, include_dirs=include_dirs, max_results=effective_max_results)
            if thread_data is not None:
                matches = [resolver.mask_local_paths_in_output(match, thread_data) for match in matches]
            return _format_glob_results(requested_path, matches, truncated)
        except SandboxError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return f"Error: Directory not found: {requested_path}"
        except NotADirectoryError:
            return f"Error: Path is not a directory: {requested_path}"
        except PermissionError:
            return f"Error: Permission denied: {requested_path}"
        except Exception as e:
            return f"Error: Unexpected error searching paths: {_sanitize_error(e, runtime)}"

    grep_name = f"{name_prefix}grep"

    @tool(grep_name, parse_docstring=True)
    def grep_tool(
        runtime: _RuntimeType,
        pattern: str,
        path: str,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = _DEFAULT_GREP_MAX_RESULTS,
        description: str = "",
    ) -> str:
        """Search for matching lines in text files under a directory.

        Args:
            description: Why you are searching (short).
            pattern: String or regex to search for.
            path: Absolute root directory.
            glob: Optional file filter, e.g. `**/*.py`.
            literal: Treat pattern as plain string. Default False.
            case_sensitive: Case-sensitive matching. Default False.
            max_results: Max matching lines. Default 100.
        """
        try:
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            requested_path = path
            effective_max_results = _resolve_max_results(
                "grep",
                max_results,
                default=_DEFAULT_GREP_MAX_RESULTS,
                upper_bound=_MAX_GREP_MAX_RESULTS,
                config_upper=resolver.config.grep_max_results_upper,
            )
            thread_data = None
            if _is_local_sandbox(runtime):
                thread_data = _get_thread_data(runtime)
                if thread_data is None:
                    raise SandboxRuntimeError("Thread data not available for local sandbox")
                path = resolver.resolve_local_read_path(path, thread_data)
            matches, truncated = sandbox.grep(
                path,
                pattern,
                glob=glob,
                literal=literal,
                case_sensitive=case_sensitive,
                max_results=effective_max_results,
            )
            if thread_data is not None:
                matches = [
                    GrepMatch(
                        path=resolver.mask_local_paths_in_output(match.path, thread_data),
                        line_number=match.line_number,
                        line=match.line,
                    )
                    for match in matches
                ]
            return _format_grep_results(requested_path, matches, truncated)
        except SandboxError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return f"Error: Directory not found: {requested_path}"
        except NotADirectoryError:
            return f"Error: Path is not a directory: {requested_path}"
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"
        except PermissionError:
            return f"Error: Permission denied: {requested_path}"
        except Exception as e:
            return f"Error: Unexpected error searching file contents: {_sanitize_error(e, runtime)}"

    read_file_name = f"{name_prefix}read_file"

    @tool(read_file_name, parse_docstring=True)
    def read_file_tool(
        runtime: _RuntimeType,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        description: str = "",
    ) -> str:
        """Read a text file (source code, config, logs, etc.).

        Args:
            description: Why you are reading this file (short).
            path: Absolute path to the file.
            start_line: Start line (1-indexed, inclusive). Use with end_line for a range.
            end_line: End line (1-indexed, inclusive).
        """
        try:
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            requested_path = path
            if _is_local_sandbox(runtime):
                thread_data = _get_thread_data(runtime)
                resolver.validate_local_tool_path(path, thread_data, read_only=True)
                if resolver.is_skills_path(path):
                    path = resolver.resolve_skills_path(path)
                elif not resolver.is_custom_mount_path(path):
                    path = resolver.resolve_and_validate_user_data_path(path, thread_data)
                # Custom mount paths are resolved by the underlying sandbox.
            content = sandbox.read_file(path)
            if not content:
                return "(empty)"
            if start_line is not None:
                lines = content.splitlines()
                end = end_line if end_line is not None else len(lines)
                content = "\n".join(lines[start_line - 1 : end])
            elif content.endswith("\n"):
                # Strip a single trailing newline so callers don't have to
                # post-process; matches the POSIX convention of "the last
                # line of a file ends with \n" without surfacing that byte.
                content = content[:-1]
            return _truncate_read_file_output(content, resolver.config.read_file_output_max_chars)
        except SandboxError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return f"Error: File not found: {requested_path}"
        except PermissionError:
            return f"Error: Permission denied reading file: {requested_path}"
        except IsADirectoryError:
            return f"Error: Path is a directory, not a file: {requested_path}"
        except Exception as e:
            return f"Error: Unexpected error reading file: {_sanitize_error(e, runtime)}"

    write_file_name = f"{name_prefix}write_file"

    @tool(write_file_name, parse_docstring=True)
    def write_file_tool(
        runtime: _RuntimeType,
        path: str,
        content: str,
        append: bool = False,
        description: str = "",
    ) -> str:
        """Write text content to a file.

        Args:
            description: Why you are writing (short).
            path: Absolute path of the file.
            content: The content to write.
        """
        try:
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            requested_path = path
            if _is_local_sandbox(runtime):
                thread_data = _get_thread_data(runtime)
                resolver.validate_local_tool_path(path, thread_data)
                if not resolver.is_custom_mount_path(path):
                    path = resolver.resolve_and_validate_user_data_path(path, thread_data)
                # Custom mount paths are resolved by the underlying sandbox.
            with get_file_operation_lock(sandbox, path):
                sandbox.write_file(path, content, append)
            return "OK"
        except SandboxError as e:
            return f"Error: {e}"
        except PermissionError:
            return f"Error: Permission denied writing to file: {requested_path}"
        except IsADirectoryError:
            return f"Error: Path is a directory, not a file: {requested_path}"
        except OSError as e:
            return f"Error: Failed to write file '{requested_path}': {_sanitize_error(e, runtime)}"
        except Exception as e:
            return f"Error: Unexpected error writing file: {_sanitize_error(e, runtime)}"

    str_replace_name = f"{name_prefix}str_replace"

    @tool(str_replace_name, parse_docstring=True)
    def str_replace_tool(
        runtime: _RuntimeType,
        path: str,
        old_str: str,
        new_str: str,
        replace_all: bool = False,
        description: str = "",
    ) -> str:
        """Replace a substring in a file. If replace_all is False (default), old_str must appear exactly once.

        Args:
            description: Why you are replacing (short).
            path: Absolute path of the file.
            old_str: Substring to replace.
            new_str: Replacement string.
            replace_all: Replace all occurrences. Default False (replace first only).
        """
        try:
            sandbox = _ensure_sandbox(runtime)
            _ensure_thread_directories_exist(runtime)
            requested_path = path
            if _is_local_sandbox(runtime):
                thread_data = _get_thread_data(runtime)
                resolver.validate_local_tool_path(path, thread_data)
                if not resolver.is_custom_mount_path(path):
                    path = resolver.resolve_and_validate_user_data_path(path, thread_data)
                # Custom mount paths are resolved by the underlying sandbox.
            with get_file_operation_lock(sandbox, path):
                content = sandbox.read_file(path)
                if not content:
                    return f"Error: String to replace not found in file: {requested_path}"
                if old_str not in content:
                    return f"Error: String to replace not found in file: {requested_path}"
                if replace_all:
                    content = content.replace(old_str, new_str)
                else:
                    content = content.replace(old_str, new_str, 1)
                sandbox.write_file(path, content)
            return "OK"
        except SandboxError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return f"Error: File not found: {requested_path}"
        except PermissionError:
            return f"Error: Permission denied accessing file: {requested_path}"
        except Exception as e:
            return f"Error: Unexpected error replacing string: {_sanitize_error(e, runtime)}"

    return SandboxToolsBundle(
        bash=bash_tool,
        ls=ls_tool,
        glob=glob_tool,
        grep=grep_tool,
        read_file=read_file_tool,
        write_file=write_file_tool,
        str_replace=str_replace_tool,
    )


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------


# _extract_thread_id is imported from agent_sdk.utils.thread (see below).
# The import is deferred to avoid a top-level cycle: tools → utils.thread
# → (nothing from sandbox) is safe, but we keep it local for consistency
# with the rest of the deferred imports in this module.


# ---------------------------------------------------------------------------
# Re-exports for backward compat
# ---------------------------------------------------------------------------
#
# The backend ``deerflow.sandbox.tools`` module exposed a handful of
# helpers as free functions (``mask_local_paths_in_output`` etc.) so
# other modules / tests could ``from deerflow.sandbox.tools import
# mask_local_paths_in_output``. The SDK puts them on
# :class:`SandboxPathResolver` instead. To keep the same import path
# working for any code that followed the backend pattern (and for
# golden-fixture tests that import these names), we re-export module-
# level shims that delegate to the active resolver.


def _active_resolver() -> SandboxPathResolver:
    """Return the active :class:`SandboxPathResolver` (or default)."""
    from agent_sdk.sandbox.path_resolver import get_path_resolver

    return get_path_resolver()


def validate_local_tool_path(path: str, thread_data, *, read_only: bool = False) -> None:
    return _active_resolver().validate_local_tool_path(path, thread_data, read_only=read_only)


def validate_local_bash_command_paths(command: str, thread_data) -> None:
    return _active_resolver().validate_local_bash_command_paths(command, thread_data)


def replace_virtual_path(path: str, thread_data) -> str:
    return _active_resolver().replace_virtual_path(path, thread_data)


def replace_virtual_paths_in_command(command: str, thread_data) -> str:
    return _active_resolver().replace_virtual_paths_in_command(command, thread_data)


def mask_local_paths_in_output(output: str, thread_data) -> str:
    return _active_resolver().mask_local_paths_in_output(output, thread_data)


def resolve_skills_path(path: str) -> str:
    return _active_resolver().resolve_skills_path(path)


def resolve_and_validate_user_data_path(path: str, thread_data) -> str:
    return _active_resolver().resolve_and_validate_user_data_path(path, thread_data)


def apply_cwd_prefix(command: str, thread_data) -> str:
    return _active_resolver().apply_cwd_prefix(command, thread_data)


__all__ = [
    "SandboxToolsBundle",
    "make_sandbox_tools",
    # Re-exports for backward compat with the backend module
    "validate_local_tool_path",
    "validate_local_bash_command_paths",
    "replace_virtual_path",
    "replace_virtual_paths_in_command",
    "mask_local_paths_in_output",
    "resolve_skills_path",
    "resolve_and_validate_user_data_path",
    "apply_cwd_prefix",
]

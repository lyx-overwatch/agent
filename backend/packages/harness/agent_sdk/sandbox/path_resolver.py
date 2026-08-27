"""Path resolution / validation / masking for sandbox tools.

This module is a re-implementation (per ADR-010) of the path
helpers that used to live in
``deerflow.sandbox.tools``. The class
:class:`SandboxPathResolver` encapsulates the four jobs:

* **validate** a virtual path (e.g. ``/mnt/user-data/x.py``)
  is allowed under the configured policy and stays inside
  the per-thread roots after host-side resolution;
* **resolve** a virtual path to a host filesystem path,
  substituting user-data / skills / custom
  mounts on the way;
* **mask** host-side absolute paths that leak into sandbox
  output (e.g. in error messages) back to their virtual
  equivalents before the LLM sees them;
* **rewrite** absolute paths that appear inside a bash
  command string so that the on-host shell can execute
  them.

All four jobs are driven by a single
:class:`SandboxToolsConfig` instance — no global state, no
``deerflow.config`` reads. The default config disables the
business-specific features (skills / custom mounts) and
keeps the brand-neutral user-data tree.

Typical wiring::

    config = SandboxToolsConfig(
        virtual_path_prefix="/mnt/user-data",
        custom_mounts=[
            CustomMount(
                host_path="/data",
                container_path="/mnt/data",
                read_only=True,
            ),
        ],
    )
    resolver = SandboxPathResolver(config)
    set_path_resolver(resolver)  # binds to the agent's contextvar

Then a tool call sees the resolver via
:func:`get_path_resolver`.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from agent_sdk.sandbox.exceptions import SandboxRuntimeError

#: Default virtual prefix for the per-thread user-data tree
#: (``/mnt/user-data/workspace``, ``/mnt/user-data/uploads``,
#: ``/mnt/user-data/outputs``). Brand-neutral default that
#: matches the most common sandbox layout.
DEFAULT_VIRTUAL_PATH_PREFIX = "/mnt/user-data"

#: Subset of system paths allowed in local-sandbox bash
#: commands (executables, device nodes). The list is
#: brand-neutral and never changes.
_LOCAL_BASH_SYSTEM_PATH_PREFIXES = (
    "/bin/",
    "/usr/bin/",
    "/usr/sbin/",
    "/sbin/",
    "/opt/homebrew/bin/",
    "/dev/",
)

#: Local-bash CWD-changing commands that need their argument
#: checked against the allowed-path list.
_LOCAL_BASH_CWD_COMMANDS = {"cd", "pushd"}

#: Wrappers like ``command cd ...`` / ``builtin cd ...`` —
#: we still need to validate the wrapped call's argument.
_LOCAL_BASH_COMMAND_WRAPPERS = {"command", "builtin"}

#: Reserved shell keywords that mark the start of a control
#: structure (``if``/``for``/``while``/...) — never treated
#: as command names by the bash validator.
_LOCAL_BASH_COMMAND_PREFIX_KEYWORDS = {"!", "{", "case", "do", "elif", "else", "for", "if", "select", "then", "time", "until", "while"}

#: Reserved shell keywords that close a control structure.
_LOCAL_BASH_COMMAND_END_KEYWORDS = {"}", "done", "esac", "fi"}

#: Commands that take absolute file/dir arguments and
#: therefore trigger ``_validate_local_bash_root_path_args``.
_LOCAL_BASH_ROOT_PATH_COMMANDS = {
    "awk",
    "cat",
    "cp",
    "du",
    "find",
    "grep",
    "head",
    "less",
    "ln",
    "ls",
    "more",
    "mv",
    "rm",
    "sed",
    "tail",
    "tar",
}

#: Shell separators (statement / pipeline boundaries).
_SHELL_COMMAND_SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")"}

#: Shell redirection operators.
_SHELL_REDIRECTION_OPERATORS = {
    "<",
    ">",
    "<<",
    ">>",
    "<<<",
    "<>",
    ">&",
    "<&",
    "&>",
    "&>>",
    ">|",
}

#: Regex matching absolute paths inside a command string.
#: Negative lookbehind skips colon-prefixed (``C:\...``) and
#: protocol-prefixed (``/foo:bar``) cases; ``(?!/)`` would
#: over-match. ``[^\s"'`;&|<>()]+`` is the byte class used
#: by the backend — kept verbatim.
_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![:\w])(?<!:/)/(?:[^\s\"'`;&|<>()]+)")

#: ``file://`` URL — blocked because it can bypass the
#: absolute-path regex and leak host data.
_FILE_URL_PATTERN = re.compile(r"\bfile://\S+", re.IGNORECASE)

#: Matches ``<scheme>://...`` URLs whose scheme is a known
#: protocol (e.g. ``https``, ``ssh``). Used to exclude URL
#: tokens from path validators.
_URL_WITH_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

#: Like :data:`_URL_WITH_SCHEME_PATTERN` but applied
#: anywhere in a command string (not just the start).
_URL_IN_COMMAND_PATTERN = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'`;&|<>()]+", re.IGNORECASE)

#: Matches a literal ``..`` path segment.
_DOTDOT_PATH_SEGMENT_PATTERN = re.compile(r"(?:^|[/\\=])\.\.(?:$|[/\\])")


@dataclass
class CustomMount:
    """A user-defined volume mount exposed to the sandbox.

    Mirrors ``deerflow.config.sandbox_config.MountEntry``
    (only the fields the path resolver cares about).

    Attributes:
        host_path: Absolute host filesystem path. Must
            already exist (mounts whose host path is missing
            are filtered out by the caller before the
            resolver sees them).
        container_path: Absolute path inside the sandbox
            where the host directory is mounted. Acts as the
            virtual prefix for read/write operations.
        read_only: When ``True``, the mount only accepts
            read-only tool calls; write attempts raise
            :class:`PermissionError`.
    """

    host_path: str
    container_path: str
    read_only: bool = False


@dataclass
class SandboxToolsConfig:
    """Business configuration consumed by sandbox tools.

    The default values are safe and brand-neutral:

    * ``virtual_path_prefix`` = ``/mnt/user-data``
    * ``custom_mounts`` = ``[]``
    * ``mcp_allowed_paths_provider`` = returns ``[]``
    """

    virtual_path_prefix: str = DEFAULT_VIRTUAL_PATH_PREFIX
    custom_mounts: list[CustomMount] = field(default_factory=list)
    mcp_allowed_paths_provider: Callable[[], list[str]] = field(default_factory=lambda: list)
    bash_output_max_chars: int = 20000
    ls_output_max_chars: int = 20000
    read_file_output_max_chars: int = 50000
    #: Optional per-tool upper bound for ``glob`` result counts. When set,
    #: the glob tool caps results at this value (in addition to the hard
    #: ceiling of 1000). ``None`` falls back to the hard ceiling. Mirrors
    #: backend's per-tool ``tools.<name>.max_results`` config.
    glob_max_results_upper: int | None = None
    #: Optional per-tool upper bound for ``grep`` result counts. Mirrors
    #: backend's ``tools.grep.max_results`` config.
    grep_max_results_upper: int | None = None
    #: Placeholder used in tool descriptions to refer to the thread-local
    #: Python virtual environment path. Substituted at tool-construction
    #: time so the description stays brand-neutral; the DeerFlow preset
    #: in phase 4 sets this to ``"<virtual_path_prefix>/workspace/.venv"``.
    python_venv_hint: str = "<virtual_path_prefix>/workspace/.venv"

    @classmethod
    def with_existing_mounts_only(cls, mounts: list[CustomMount], **kwargs: object) -> SandboxToolsConfig:
        """Build a config with only the ``custom_mounts`` whose host_path exists.

        Mirrors backend ``deerflow.sandbox.local._setup_path_mappings``,
        which only mounts existing directories. Returns a brand-new
        :class:`SandboxToolsConfig` (the resolver itself does **not**
        filter mounts, so callers that want the backend-equivalent
        behaviour should construct the config via this classmethod).

        Example::

            cfg = SandboxToolsConfig.with_existing_mounts_only(
                mounts=config_yaml.mounts,
            )
        """
        from pathlib import Path as _Path

        kept = [m for m in mounts if _Path(m.host_path).exists()]
        dropped = [m for m in mounts if not _Path(m.host_path).exists()]
        if dropped:
            import warnings

            warnings.warn(
                "Dropped custom_mounts with non-existent host_path: "
                + ", ".join(repr(m.host_path) for m in dropped),
                stacklevel=2,
            )
        return cls(custom_mounts=kept, **kwargs)


# ---------------------------------------------------------------------------
# Module-level contextvar so the tools can find the active resolver without
# taking it as an explicit argument. The agent factory (or test setup) calls
# :func:`set_path_resolver` once per graph / per test; tools call
# :func:`get_path_resolver` on every invocation.
# ---------------------------------------------------------------------------

_PATH_RESOLVER: ContextVar[SandboxPathResolver | None] = ContextVar("agent_sdk_sandbox_path_resolver", default=None)


def get_path_resolver() -> SandboxPathResolver:
    """Return the active :class:`SandboxPathResolver`.

    A default resolver is constructed lazily on first access
    so that tools called outside of an agent context (e.g.
    ad-hoc tests) still get sane brand-neutral behaviour.
    """
    resolver = _PATH_RESOLVER.get()
    if resolver is None:
        resolver = SandboxPathResolver(SandboxToolsConfig())
        _PATH_RESOLVER.set(resolver)
    return resolver


def set_path_resolver(resolver: SandboxPathResolver) -> object:
    """Bind *resolver* as the active one. Returns a token for :func:`reset_path_resolver`."""
    return _PATH_RESOLVER.set(resolver)


def reset_path_resolver(token: object) -> None:
    """Restore the previously-bound resolver (use the token returned by :func:`set_path_resolver`)."""
    _PATH_RESOLVER.reset(token)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Lightweight typing aliases. The full ThreadDataState lives in
# agent_sdk.runtime.thread_state but importing it here would cause a cycle
# (thread_state → tools → path_resolver). We describe the contract in prose
# and use a structural type so tools can pass dicts in tests.
# ---------------------------------------------------------------------------

#: Structural alias for ``agent_sdk.runtime.thread_state.ThreadDataState``.
#: Always passed as a dict; the resolver reads the three string keys.
ThreadDataDict = dict


# ---------------------------------------------------------------------------
# Path style helpers (verbatim from backend, kept identical for byte-level
# parity with tests / golden snapshots).
# ---------------------------------------------------------------------------


def _path_variants(path: str) -> set[str]:
    """Return the set of slash / backslash spellings of *path*."""
    return {path, path.replace("\\", "/"), path.replace("/", "\\")}


def _path_separator_for_style(path: str) -> str:
    """Pick the separator that matches the host style encoded in *path*."""
    return "\\" if "\\" in path and "/" not in path else "/"


def _join_path_preserving_style(base: str, relative: str) -> str:
    """Join *relative* onto *base* preserving the slash style of *base*."""
    if not relative:
        return base
    separator = _path_separator_for_style(base)
    normalized_relative = relative.replace("\\" if separator == "/" else "/", separator).lstrip("/\\")
    stripped_base = base.rstrip("/\\")
    return f"{stripped_base}{separator}{normalized_relative}"


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class SandboxPathResolver:
    """Resolve / validate / mask virtual paths for sandbox tools.

    The resolver is pure: it does not call into the sandbox
    and does not read global config. Given the same inputs
    and the same :class:`SandboxToolsConfig` it always
    returns the same output.
    """

    def __init__(self, config: SandboxToolsConfig) -> None:
        self._config = config

    # -- Properties for convenience --------------------------------------

    @property
    def config(self) -> SandboxToolsConfig:
        """Return the underlying :class:`SandboxToolsConfig`."""
        return self._config

    @property
    def virtual_path_prefix(self) -> str:
        """The virtual root of the per-thread user-data tree."""
        return self._config.virtual_path_prefix

    # -- Path family predicates ------------------------------------------

    def is_custom_mount_path(self, path: str) -> bool:
        """``True`` when *path* is under any configured custom mount prefix."""
        for mount in self._config.custom_mounts:
            if path == mount.container_path or path.startswith(f"{mount.container_path}/"):
                return True
        return False

    def is_user_data_path(self, path: str) -> bool:
        """``True`` when *path* is under the virtual user-data prefix."""
        prefix = self.virtual_path_prefix
        return path == prefix or path.startswith(f"{prefix}/")

    def _is_user_data_subpath(self, path: str) -> bool:
        """``True`` when *path* is a *subpath* of user-data (not the root).

        Used by :meth:`validate_local_tool_path` to reject bare
        root paths like ``/mnt/user-data`` (no trailing component)
        — backend ``deerflow.sandbox.tools._validate_local_tool_path``
        requires ``path`` to be inside one of the three sub-trees
        (workspace / uploads / outputs), not the root itself.
        """
        prefix = self.virtual_path_prefix
        return path.startswith(f"{prefix}/") and len(path) > len(prefix) + 1

    def _is_custom_mount_subpath(self, path: str) -> bool:
        for mount in self._config.custom_mounts:
            cp = mount.container_path
            if path == cp or path.startswith(f"{cp}/"):
                # path == container_path is a bare root → reject;
                # path.startswith(...) without further content is also
                # a bare root. Require at least one extra segment.
                if path == cp:
                    return False
                relative = path[len(cp) :].lstrip("/")
                return bool(relative)
        return False

    def is_path_family_known(self, path: str) -> bool:
        """``True`` when *path* belongs to at least one allowed family."""
        return (
            self.is_user_data_path(path)
            or self.is_custom_mount_path(path)
        )

    # -- Path resolution -------------------------------------------------

    def resolve_local_read_path(self, path: str, thread_data: ThreadDataDict) -> str:
        """Resolve a virtual read-only path to a host path.

        Calls :meth:`validate_local_tool_path` first to make
        sure the read is allowed; then dispatches to the
        appropriate sub-resolver.
        """
        self.validate_local_tool_path(path, thread_data, read_only=True)
        return self.resolve_and_validate_user_data_path(path, thread_data)

    # -- Path validation -------------------------------------------------

    @staticmethod
    def _reject_path_traversal(path: str) -> None:
        """Reject ``..`` path segments."""
        normalised = path.replace("\\", "/")
        for segment in normalised.split("/"):
            if segment == "..":
                raise PermissionError("Access denied: path traversal detected")

    def _custom_mount_for_path(self, path: str) -> CustomMount | None:
        """Return the longest-prefix custom mount for *path* (``None`` if none)."""
        best: CustomMount | None = None
        for mount in self._config.custom_mounts:
            if path == mount.container_path or path.startswith(f"{mount.container_path}/"):
                if best is None or len(mount.container_path) > len(best.container_path):
                    best = mount
        return best

    def validate_local_tool_path(self, path: str, thread_data: ThreadDataDict | None, *, read_only: bool = False) -> None:
        """Validate a virtual path against the configured policy.

        Allowed families (each requires a **subpath** under the
        family root — the root itself is rejected, matching
        ``deerflow.sandbox.tools._validate_local_tool_path``):

        * ``/mnt/user-data/<sub>`` — read + write
        * ``<custom_mount>/<sub>`` — respects per-mount ``read_only`` flag

        Skills paths are NOT validated here — skill content is
        accessed via the ``read_skill`` tool instead of through
        the sandbox filesystem.

        Raises:
            SandboxRuntimeError: When *thread_data* is ``None``.
            PermissionError: On traversal, bare root, or out-of-policy access.
        """
        if thread_data is None:
            raise SandboxRuntimeError("Thread data not available for local sandbox")
        self._reject_path_traversal(path)

        if self._is_user_data_subpath(path):
            return

        if self._is_custom_mount_subpath(path):
            mount = self._custom_mount_for_path(path)
            if mount and mount.read_only and not read_only:
                raise PermissionError(f"Write access to read-only mount is not allowed: {path}")
            return

        allowed = [self.virtual_path_prefix + "/"]
        # Match backend error format: "... or configured mount paths are allowed"
        raise PermissionError(
            f"Only paths under {', '.join(allowed)}or configured mount paths are allowed"
        )

    def _validate_resolved_user_data_path(self, resolved: Path, thread_data: ThreadDataDict) -> None:
        """Verify a resolved user-data path stays inside the per-thread roots."""
        allowed_roots = [
            Path(p).resolve()
            for p in (
                thread_data.get("workspace_path"),
                thread_data.get("uploads_path"),
                thread_data.get("outputs_path"),
            )
            if p is not None
        ]

        if not allowed_roots:
            raise SandboxRuntimeError("No allowed local sandbox directories configured")

        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return
            except ValueError:
                continue

        raise PermissionError("Access denied: path traversal detected")

    def resolve_and_validate_user_data_path(self, path: str, thread_data: ThreadDataDict) -> str:
        """Resolve ``/mnt/user-data/...`` to a host path and verify it stays in bounds."""
        resolved_str = self.replace_virtual_path(path, thread_data)
        resolved = Path(resolved_str).resolve()
        self._validate_resolved_user_data_path(resolved, thread_data)
        return str(resolved)

    # -- Virtual → actual mapping ----------------------------------------

    def replace_virtual_path(self, path: str, thread_data: ThreadDataDict | None) -> str:
        """Substitute the per-thread user-data prefix in *path*.

        Mapping::

            /mnt/user-data/workspace/* -> thread_data['workspace_path']/*
            /mnt/user-data/uploads/*   -> thread_data['uploads_path']/*
            /mnt/user-data/outputs/*   -> thread_data['outputs_path']/*

        If the three target directories share a common
        parent, ``/mnt/user-data`` itself is also mapped to
        that parent (longest-prefix-first).
        """
        if thread_data is None:
            return path

        mappings = self._thread_virtual_to_actual_mappings_impl(self._config.virtual_path_prefix, thread_data)
        if not mappings:
            return path

        for virtual_base, actual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
            if path == virtual_base:
                return actual_base
            if path.startswith(f"{virtual_base}/"):
                rest = path[len(virtual_base) :].lstrip("/")
                result = _join_path_preserving_style(actual_base, rest)
                if path.endswith("/") and not result.endswith(("/", "\\")):
                    result += _path_separator_for_style(actual_base)
                return result

        return path

    @staticmethod
    def _thread_virtual_to_actual_mappings_impl(vprefix: str, thread_data: ThreadDataDict) -> dict[str, str]:
        """Build the virtual→actual prefix table for *thread_data*."""
        mappings: dict[str, str] = {}

        workspace = thread_data.get("workspace_path")
        uploads = thread_data.get("uploads_path")
        outputs = thread_data.get("outputs_path")

        if workspace:
            mappings[f"{vprefix}/workspace"] = workspace
        if uploads:
            mappings[f"{vprefix}/uploads"] = uploads
        if outputs:
            mappings[f"{vprefix}/outputs"] = outputs

        # Map the virtual root when all three share a common parent.
        actual_dirs = [Path(p) for p in (workspace, uploads, outputs) if p]
        if actual_dirs:
            common_parent = str(Path(actual_dirs[0]).parent)
            if all(str(path.parent) == common_parent for path in actual_dirs):
                mappings[vprefix] = common_parent

        return mappings

    def _thread_actual_to_virtual_mappings(self, thread_data: ThreadDataDict) -> dict[str, str]:
        """Inverse of :meth:`_thread_virtual_to_actual_mappings` for output masking."""
        return {actual: virtual for virtual, actual in self._thread_virtual_to_actual_mappings_impl(self._config.virtual_path_prefix, thread_data).items()}

    # -- Output masking --------------------------------------------------

    def mask_local_paths_in_output(self, output: str, thread_data: ThreadDataDict | None) -> str:
        """Replace host absolute paths in *output* with their virtual equivalents.

        The masking walks the per-thread user-data prefix
        family and is robust to slash-style drift (raw vs.
        :meth:`Path.resolve`).

        Skills paths are not masked — skill content is accessed
        via the ``read_skill`` tool which reads directly from
        the host filesystem without involving the sandbox.
        """
        result = output

        # User-data host paths
        if thread_data is None:
            return result

        mappings = self._thread_actual_to_virtual_mappings(thread_data)
        if not mappings:
            return result

        for actual_base, virtual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
            raw_base = str(Path(actual_base))
            resolved_base = str(Path(actual_base).resolve())
            for base in _path_variants(raw_base) | _path_variants(resolved_base):
                escaped_actual = re.escape(base).replace(r"\\", r"[/\\]")
                pattern = re.compile(escaped_actual + r"(?:[/\\][^\s\"';&|<>()]*)?")

                def replace_match(match: re.Match, _base: str = base, _virtual: str = virtual_base) -> str:
                    matched_path = match.group(0)
                    if matched_path == _base:
                        return _virtual
                    relative = matched_path[len(_base) :].lstrip("/\\")
                    return f"{_virtual}/{relative}" if relative else _virtual

                result = pattern.sub(replace_match, result)

        return result

    # -- Local-bash command validation -----------------------------------

    def validate_local_bash_command_paths(self, command: str, thread_data: ThreadDataDict | None) -> None:
        """Validate absolute paths in a local-sandbox bash command.

        This is a best-effort guard for the explicit
        ``sandbox.allow_host_bash: true`` opt-in — it is not
        a secure sandbox boundary. See
        :class:`agent_sdk.sandbox.security.HostBashPolicy`
        for the policy switch.

        Raises:
            SandboxRuntimeError: When *thread_data* is ``None``.
            PermissionError: On ``file://`` URL, traversal, or
                disallowed absolute paths.
        """
        if thread_data is None:
            raise SandboxRuntimeError("Thread data not available for local sandbox")

        file_url_match = _FILE_URL_PATTERN.search(command)
        if file_url_match:
            raise PermissionError(f"Unsafe file:// URL in command: {file_url_match.group()}. Use paths under {self.virtual_path_prefix}")

        unsafe_paths: list[str] = []
        allowed_paths = self._config.mcp_allowed_paths_provider()
        self._validate_local_bash_shell_tokens(command, allowed_paths)
        url_spans = _non_file_url_spans(command)

        for match in _ABSOLUTE_PATH_PATTERN.finditer(command):
            if _is_in_spans(match.start(), url_spans):
                continue
            absolute_path = match.group()
            if self._is_allowed_local_bash_absolute_path(absolute_path, allowed_paths, allow_system_paths=True):
                continue
            unsafe_paths.append(absolute_path)

        if unsafe_paths:
            unsafe = ", ".join(sorted(dict.fromkeys(unsafe_paths)))
            raise PermissionError(f"Unsafe absolute paths in command: {unsafe}. Use paths under {self.virtual_path_prefix}")

    def _is_allowed_local_bash_absolute_path(self, path: str, allowed_paths: list[str], *, allow_system_paths: bool) -> bool:
        if any(path.startswith(allowed_path) or path == allowed_path.rstrip("/") for allowed_path in allowed_paths):
            self._reject_path_traversal(path)
            return True
        if path == self.virtual_path_prefix or path.startswith(f"{self.virtual_path_prefix}/"):
            self._reject_path_traversal(path)
            return True
        if self.is_custom_mount_path(path):
            self._reject_path_traversal(path)
            return True
        if allow_system_paths and any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _LOCAL_BASH_SYSTEM_PATH_PREFIXES):
            return True
        return False

    def _validate_local_bash_shell_tokens(self, command: str, allowed_paths: list[str]) -> None:
        """Tokenise *command* and reject relative path escapes and unsafe CWD targets."""
        if re.search(r"\$\([^)]*\b(?:cd|pushd)\b", command):
            raise PermissionError(f"Unsafe working directory change in command substitution. Use paths under {self.virtual_path_prefix}")

        tokens = self._split_shell_tokens(command)

        for token in tokens:
            if _is_shell_command_separator(token) or _is_shell_redirection_operator(token):
                continue
            if _has_dotdot_path_segment(token):
                raise PermissionError("Access denied: path traversal detected")

        at_command_start = True
        index = 0
        while index < len(tokens):
            token = tokens[index]

            if _is_shell_command_separator(token):
                at_command_start = True
                index += 1
                continue

            if _is_shell_redirection_operator(token):
                index += 1
                continue

            if at_command_start and _is_shell_assignment(token):
                index += 1
                continue

            command_name = token.rsplit("/", 1)[-1]
            if at_command_start and command_name in _LOCAL_BASH_COMMAND_PREFIX_KEYWORDS | _LOCAL_BASH_COMMAND_END_KEYWORDS:
                index += 1
                continue

            if not at_command_start:
                index += 1
                continue

            at_command_start = False
            if command_name in _LOCAL_BASH_COMMAND_WRAPPERS and index + 1 < len(tokens):
                wrapped_name = tokens[index + 1].rsplit("/", 1)[-1]
                if wrapped_name in _LOCAL_BASH_CWD_COMMANDS:
                    target, next_index = self._next_cd_target(tokens, index + 2)
                    self._validate_local_bash_cwd_target(wrapped_name, target, allowed_paths)
                    index = next_index
                    continue
                self._validate_local_bash_root_path_args(wrapped_name, tokens, index + 2)

            if command_name not in _LOCAL_BASH_CWD_COMMANDS:
                self._validate_local_bash_root_path_args(command_name, tokens, index + 1)
                index += 1
                continue

            target, next_index = self._next_cd_target(tokens, index + 1)
            self._validate_local_bash_cwd_target(command_name, target, allowed_paths)
            index = next_index

    @staticmethod
    def _split_shell_tokens(command: str) -> list[str]:
        try:
            normalized = command.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ; ")
            lexer = shlex.shlex(normalized, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            return list(lexer)
        except ValueError:
            pass
        # Fallback 1: shlex without punctuation_chars — still
        # handles quoting correctly, just won't split ``;``/``&&``
        # as tokens.  Safer than bare str.split() which destroys
        # quoted arguments.
        try:
            normalized = command.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ; ")
            lexer = shlex.shlex(normalized, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            return list(lexer)
        except ValueError:
            pass
        # Last-resort fallback: bare str.split().  Quoted paths may
        # be mis-tokenised, but the best-effort validation still
        # catches the most common unsafe-pattern cases.
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Could not tokenise bash command with shlex; falling back to str.split(). "
            "Path validation may be less precise for this command."
        )
        return command.split()

    def _next_cd_target(self, tokens: list[str], start_index: int) -> tuple[str | None, int]:
        index = start_index
        while index < len(tokens):
            token = tokens[index]
            if _is_shell_command_separator(token):
                return None, index
            if _is_shell_redirection_operator(token):
                index += 2
                continue
            if token == "--":
                index += 1
                continue
            if token in {"-L", "-P", "-e", "-@"}:
                index += 1
                continue
            if token.startswith("-") and token != "-":
                index += 1
                continue
            return token, index + 1
        return None, index

    def _validate_local_bash_cwd_target(self, command_name: str, target: str | None, allowed_paths: list[str]) -> None:
        if target is None or target == "-":
            raise PermissionError(f"Unsafe working directory change in command: {command_name}. Use paths under {self.virtual_path_prefix}")
        if target.startswith(("$", "`")):
            raise PermissionError(f"Unsafe working directory change in command: {command_name} {target}. Use paths under {self.virtual_path_prefix}")
        if target.startswith("~"):
            raise PermissionError(f"Unsafe working directory change in command: {command_name} {target}. Use paths under {self.virtual_path_prefix}")
        if target.startswith("/"):
            self._reject_path_traversal(target)
            if not self._is_allowed_local_bash_absolute_path(target, allowed_paths, allow_system_paths=False):
                raise PermissionError(f"Unsafe working directory change in command: {command_name} {target}. Use paths under {self.virtual_path_prefix}")

    def _validate_local_bash_root_path_args(self, command_name: str, tokens: list[str], start_index: int) -> None:
        if command_name not in _LOCAL_BASH_ROOT_PATH_COMMANDS:
            return

        index = start_index
        while index < len(tokens):
            token = tokens[index]
            if _is_shell_command_separator(token):
                return
            if _is_shell_redirection_operator(token):
                index += 2
                continue
            if token == "/" and not _is_non_file_url_token(token):
                raise PermissionError(f"Unsafe absolute paths in command: /. Use paths under {self.virtual_path_prefix}")
            index += 1

    # -- Command rewriting -----------------------------------------------

    def replace_virtual_paths_in_command(self, command: str, thread_data: ThreadDataDict | None) -> str:
        """Substitute the user-data virtual prefix in a command string.

        Skills paths are not substituted — skill content is
        accessed via the ``read_skill`` tool, not through
        sandbox file-system operations.
        """
        result = command

        if self.virtual_path_prefix in result and thread_data is not None:
            pattern = re.compile(rf"{re.escape(self.virtual_path_prefix)}(/[^\s\"';&|<>()]*)?")

            def replace_user_data_match(match: re.Match) -> str:
                return self.replace_virtual_path(match.group(0), thread_data)

            result = pattern.sub(replace_user_data_match, result)

        return result

    def apply_cwd_prefix(self, command: str, thread_data: ThreadDataDict | None) -> str:
        """Prepend ``cd <workspace> &&`` so relative paths anchor to the thread workspace."""
        if thread_data and (workspace := thread_data.get("workspace_path")):
            if os.name == "nt":
                # Windows: cmd.exe requires double quotes — POSIX single quotes
                # produced by shlex.quote are not valid string delimiters for cmd.exe.
                return f'cd "{workspace}" && {command}'
            return f"cd {shlex.quote(workspace)} && {command}"
        return command


# ---------------------------------------------------------------------------
# Free-function helpers (kept module-level for backend parity; they delegate
# to the active resolver so tools can use either call style).
# ---------------------------------------------------------------------------


def _is_shell_command_separator(token: str) -> bool:
    return token in _SHELL_COMMAND_SEPARATORS


def _is_shell_redirection_operator(token: str) -> bool:
    return token in _SHELL_REDIRECTION_OPERATORS


def _is_shell_assignment(token: str) -> bool:
    name, separator, _ = token.partition("=")
    if not separator or not name:
        return False
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _is_non_file_url_token(token: str) -> bool:
    """Return True for URL tokens (other than ``file://``) so they are not treated as paths."""
    values = [token]
    if "=" in token:
        values.append(token.split("=", 1)[1])

    for value in values:
        match = _URL_WITH_SCHEME_PATTERN.match(value)
        if match and not value.lower().startswith("file://"):
            return True
    return False


def _non_file_url_spans(command: str) -> list[tuple[int, int]]:
    spans = []
    for match in _URL_IN_COMMAND_PATTERN.finditer(command):
        if not match.group().lower().startswith("file://"):
            spans.append(match.span())
    return spans


def _is_in_spans(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _has_dotdot_path_segment(token: str) -> bool:
    if _is_non_file_url_token(token):
        return False
    return bool(_DOTDOT_PATH_SEGMENT_PATTERN.search(token))


__all__ = [
    "CustomMount",
    "DEFAULT_VIRTUAL_PATH_PREFIX",
    "SandboxPathResolver",
    "SandboxToolsConfig",
    "get_path_resolver",
    "reset_path_resolver",
    "set_path_resolver",
]

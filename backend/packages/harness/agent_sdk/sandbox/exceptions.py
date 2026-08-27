"""Sandbox-related exceptions with structured error information.

This module is a re-implementation (per ADR-010) of
``deerflow.sandbox.exceptions``. The shape mirrors the original
hierarchy so that user code catching the backend exceptions
will catch the SDK versions too — but the SDK is self-contained
(``import``-free of ``deerflow.*`` / ``backend.*`` / ``app.*``).

Hierarchy::

    SandboxError
    ├── SandboxNotFoundError
    ├── SandboxRuntimeError
    ├── SandboxCommandError
    └── SandboxFileError
        ├── SandboxPermissionError
        └── SandboxFileNotFoundError

Each exception carries a ``message`` and an optional ``details``
dict. The :meth:`__str__` form is ``"<message> (k=v, k=v)"``
when details are present and ``"<message>"`` otherwise — this
mirrors the backend's behaviour so that error messages
displayed to the user (e.g. via ``f"Error: {e}"`` in the
tool implementations) remain byte-identical.
"""

from __future__ import annotations

from typing import Any


class SandboxError(Exception):
    """Base exception for all sandbox-related errors.

    Args:
        message: Human-readable error message.
        details: Optional dict of structured error context.
            The default ``str(exception)`` joins these as
            ``k=v, k=v`` so downstream tooling can match on
            the rendered form.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message


class SandboxNotFoundError(SandboxError):
    """Raised when a sandbox cannot be found or is not available.

    Args:
        message: Human-readable error message.
        sandbox_id: The id of the missing sandbox, if known.
            Recorded both in ``details["sandbox_id"]`` and as
            the dedicated ``sandbox_id`` attribute.
    """

    def __init__(self, message: str = "Sandbox not found", sandbox_id: str | None = None) -> None:
        details = {"sandbox_id": sandbox_id} if sandbox_id else None
        super().__init__(message, details)
        self.sandbox_id = sandbox_id


class SandboxRuntimeError(SandboxError):
    """Raised when sandbox runtime is not available or misconfigured.

    Common causes: ``ToolRuntime`` not bound, ``ThreadState``
    not yet populated by :class:`SandboxMiddleware`, or the
    configured provider raised on construction.
    """

    pass


class SandboxCommandError(SandboxError):
    """Raised when a command execution fails in the sandbox.

    Args:
        message: Human-readable error message.
        command: The command that failed (truncated to 100
            characters in the rendered ``str`` form).
        exit_code: The process exit code, if available.
    """

    def __init__(self, message: str, command: str | None = None, exit_code: int | None = None) -> None:
        details: dict[str, Any] = {}
        if command:
            details["command"] = command[:100] + "..." if len(command) > 100 else command
        if exit_code is not None:
            details["exit_code"] = exit_code
        super().__init__(message, details)
        self.command = command
        self.exit_code = exit_code


class SandboxFileError(SandboxError):
    """Raised when a file operation fails in the sandbox.

    Args:
        message: Human-readable error message.
        path: The path that triggered the error.
        operation: The operation name (e.g. ``"read"``,
            ``"write"``, ``"append"``).
    """

    def __init__(self, message: str, path: str | None = None, operation: str | None = None) -> None:
        details: dict[str, Any] = {}
        if path:
            details["path"] = path
        if operation:
            details["operation"] = operation
        super().__init__(message, details)
        self.path = path
        self.operation = operation


class SandboxPermissionError(SandboxFileError):
    """Raised when a permission error occurs during file operations.

    Typically raised by a host-local sandbox when a tool tries
    to access a path outside the configured thread-data roots.
    """

    pass


class SandboxFileNotFoundError(SandboxFileError):
    """Raised when a file or directory is not found."""

    pass


__all__ = [
    "SandboxError",
    "SandboxNotFoundError",
    "SandboxRuntimeError",
    "SandboxCommandError",
    "SandboxFileError",
    "SandboxPermissionError",
    "SandboxFileNotFoundError",
]

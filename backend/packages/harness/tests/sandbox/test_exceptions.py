"""Unit tests for :mod:`agent_sdk.sandbox.exceptions`."""

from __future__ import annotations

import pytest
from agent_sdk.sandbox.exceptions import (
    SandboxCommandError,
    SandboxError,
    SandboxFileError,
    SandboxFileNotFoundError,
    SandboxNotFoundError,
    SandboxPermissionError,
    SandboxRuntimeError,
)

# ---------------------------------------------------------------------------
# SandboxError base
# ---------------------------------------------------------------------------


class TestSandboxError:
    def test_message_only(self) -> None:
        err = SandboxError("something went wrong")
        assert err.message == "something went wrong"
        assert err.details == {}
        assert str(err) == "something went wrong"
        assert isinstance(err, Exception)

    def test_message_with_details(self) -> None:
        err = SandboxError("something went wrong", {"code": 42, "tag": "x"})
        assert err.details == {"code": 42, "tag": "x"}
        # ``__str__`` joins details as ``k=v`` pairs in insertion order.
        assert str(err) == "something went wrong (code=42, tag=x)"

    def test_empty_details_dict(self) -> None:
        err = SandboxError("msg", details={})
        assert str(err) == "msg"


# ---------------------------------------------------------------------------
# SandboxNotFoundError
# ---------------------------------------------------------------------------


class TestSandboxNotFoundError:
    def test_default_message(self) -> None:
        err = SandboxNotFoundError()
        assert err.message == "Sandbox not found"
        assert err.sandbox_id is None
        assert err.details == {}

    def test_with_sandbox_id(self) -> None:
        err = SandboxNotFoundError("missing", sandbox_id="sb-1")
        assert err.message == "missing"
        assert err.sandbox_id == "sb-1"
        assert err.details == {"sandbox_id": "sb-1"}
        assert "sandbox_id=sb-1" in str(err)

    def test_inherits_sandbox_error(self) -> None:
        assert issubclass(SandboxNotFoundError, SandboxError)


# ---------------------------------------------------------------------------
# SandboxRuntimeError
# ---------------------------------------------------------------------------


class TestSandboxRuntimeError:
    def test_construction(self) -> None:
        err = SandboxRuntimeError("no runtime")
        assert err.message == "no runtime"
        assert err.details == {}

    def test_inherits(self) -> None:
        assert issubclass(SandboxRuntimeError, SandboxError)


# ---------------------------------------------------------------------------
# SandboxCommandError
# ---------------------------------------------------------------------------


class TestSandboxCommandError:
    def test_message_only(self) -> None:
        err = SandboxCommandError("command failed")
        assert err.command is None
        assert err.exit_code is None
        assert err.details == {}

    def test_with_command_and_exit_code(self) -> None:
        err = SandboxCommandError("command failed", command="ls /missing", exit_code=2)
        assert err.command == "ls /missing"
        assert err.exit_code == 2
        assert err.details == {"command": "ls /missing", "exit_code": 2}
        s = str(err)
        assert "command=ls /missing" in s
        assert "exit_code=2" in s

    def test_long_command_truncated(self) -> None:
        long_cmd = "x" * 200
        err = SandboxCommandError("failed", command=long_cmd)
        # 100 chars + "..." suffix.
        assert err.details["command"].endswith("...")
        assert len(err.details["command"]) == 103

    def test_inherits(self) -> None:
        assert issubclass(SandboxCommandError, SandboxError)


# ---------------------------------------------------------------------------
# SandboxFileError and friends
# ---------------------------------------------------------------------------


class TestSandboxFileError:
    def test_with_path(self) -> None:
        err = SandboxFileError("bad", path="/x.py")
        assert err.path == "/x.py"
        assert err.operation is None
        assert err.details == {"path": "/x.py"}

    def test_with_path_and_operation(self) -> None:
        err = SandboxFileError("bad", path="/x.py", operation="write")
        assert err.details == {"path": "/x.py", "operation": "write"}
        s = str(err)
        assert "path=/x.py" in s
        assert "operation=write" in s

    def test_inherits(self) -> None:
        assert issubclass(SandboxFileError, SandboxError)


class TestSandboxPermissionError:
    def test_inherits_file_error(self) -> None:
        assert issubclass(SandboxPermissionError, SandboxFileError)
        err = SandboxPermissionError("denied", path="/x", operation="read")
        assert err.path == "/x"
        assert err.operation == "read"


class TestSandboxFileNotFoundError:
    def test_inherits_file_error(self) -> None:
        assert issubclass(SandboxFileNotFoundError, SandboxFileError)
        err = SandboxFileNotFoundError("missing", path="/x")
        assert err.path == "/x"


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


class TestHierarchy:
    def test_can_catch_all_as_base(self) -> None:
        errors = [
            SandboxNotFoundError("x"),
            SandboxRuntimeError("x"),
            SandboxCommandError("x", command="y"),
            SandboxFileError("x", path="/p"),
            SandboxPermissionError("x", path="/p"),
            SandboxFileNotFoundError("x", path="/p"),
        ]
        for err in errors:
            assert isinstance(err, SandboxError)
            # Can be raised and caught as SandboxError.
            with pytest.raises(SandboxError):
                raise err

    def test_raise_subclass_catch_subclass(self) -> None:
        with pytest.raises(SandboxNotFoundError):
            raise SandboxNotFoundError("missing")

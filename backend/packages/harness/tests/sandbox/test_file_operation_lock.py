"""Unit tests for :mod:`agent_sdk.sandbox.file_operation_lock`."""

from __future__ import annotations

import threading
import time

from agent_sdk.sandbox.file_operation_lock import (
    get_file_operation_lock,
    get_file_operation_lock_key,
)


class _StubSandbox:
    """Minimal stand-in for a :class:`Sandbox` instance."""

    def __init__(self, sandbox_id: str | None = None) -> None:
        if sandbox_id is not None:
            self.id = sandbox_id


class TestKeyConstruction:
    def test_uses_sandbox_id_attribute(self) -> None:
        sb = _StubSandbox("sb-1")
        assert get_file_operation_lock_key(sb, "/path") == ("sb-1", "/path")

    def test_falls_back_to_instance_id(self) -> None:
        # No ``id`` attribute -> use ``id(sb)``-based fallback.
        sb = _StubSandbox(sandbox_id=None)
        # Delete the attribute so the fallback path is taken.
        if hasattr(sb, "id"):
            delattr(sb, "id")
        key = get_file_operation_lock_key(sb, "/p")
        assert key[0].startswith("instance:")
        assert key[1] == "/p"

    def test_different_paths_different_keys(self) -> None:
        sb = _StubSandbox("sb-1")
        a = get_file_operation_lock_key(sb, "/a")
        b = get_file_operation_lock_key(sb, "/b")
        assert a != b

    def test_different_sandboxes_different_keys(self) -> None:
        a = get_file_operation_lock_key(_StubSandbox("sb-1"), "/p")
        b = get_file_operation_lock_key(_StubSandbox("sb-2"), "/p")
        assert a != b


class TestLockReuse:
    def test_same_key_returns_same_lock(self) -> None:
        sb = _StubSandbox("sb-1")
        a = get_file_operation_lock(sb, "/p")
        b = get_file_operation_lock(sb, "/p")
        assert a is b

    def test_different_keys_return_different_locks(self) -> None:
        sb = _StubSandbox("sb-1")
        a = get_file_operation_lock(sb, "/a")
        b = get_file_operation_lock(sb, "/b")
        assert a is not b

    def test_different_sandboxes_return_different_locks(self) -> None:
        a = get_file_operation_lock(_StubSandbox("sb-1"), "/p")
        b = get_file_operation_lock(_StubSandbox("sb-2"), "/p")
        assert a is not b


class TestMutualExclusion:
    def test_lock_serialises_writers(self) -> None:
        """Two threads acquiring the same lock must not interleave their critical sections."""
        sb = _StubSandbox("sb-1")
        lock = get_file_operation_lock(sb, "/p")
        order: list[str] = []
        delay = 0.05

        def worker(name: str) -> None:
            with lock:
                order.append(f"{name}:enter")
                time.sleep(delay)
                order.append(f"{name}:exit")

        t1 = threading.Thread(target=worker, args=("A",))
        t2 = threading.Thread(target=worker, args=("B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Either A enters first and exits first, or B does.
        assert order in (
            ["A:enter", "A:exit", "B:enter", "B:exit"],
            ["B:enter", "B:exit", "A:enter", "A:exit"],
        ), f"unexpected interleaving: {order}"

    def test_distinct_keys_do_not_serialise(self) -> None:
        """Locks for different keys must not block each other."""
        sb = _StubSandbox("sb-1")
        lock_a = get_file_operation_lock(sb, "/a")
        lock_b = get_file_operation_lock(sb, "/b")
        order: list[str] = []
        delay = 0.05

        def worker(lock: threading.Lock, name: str) -> None:
            with lock:
                order.append(f"{name}:enter")
                time.sleep(delay)
                order.append(f"{name}:exit")

        ta = threading.Thread(target=worker, args=(lock_a, "A"))
        tb = threading.Thread(target=worker, args=(lock_b, "B"))
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        # Both enter first, then both exit — keys do not block each other.
        enter_indices = [order.index("A:enter"), order.index("B:enter")]
        exit_indices = [order.index("A:exit"), order.index("B:exit")]
        assert max(enter_indices) < min(exit_indices), f"locks serialised unexpectedly: {order}"


class TestFallbackSandbox:
    def test_object_without_id_attribute(self) -> None:
        """Objects with no ``id`` attr must use the ``instance:`` fallback."""
        sentinel = object()
        key = get_file_operation_lock_key(sentinel, "/p")
        assert key[0].startswith("instance:")

        # And the returned lock should be usable.
        lock = get_file_operation_lock(sentinel, "/p")
        with lock:
            pass  # no-op; just verify acquisition

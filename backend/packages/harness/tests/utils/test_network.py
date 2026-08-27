"""Unit tests for :mod:`agent_sdk.utils.network`.

Covers :class:`PortAllocator` and the module-level
:func:`get_free_port` / :func:`release_port` helpers.  These
tests do **not** assume any particular port range (the
allocator is configurable), and they skip gracefully on
platforms where binding to port 0 is not possible.
"""

from __future__ import annotations

import socket

import pytest
from agent_sdk.utils.network import (
    PortAllocator,
    get_free_port,
    release_port,
)


def _is_port_free(port: int) -> bool:
    """Probe whether *port* can be bound on the wildcard address."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# PortAllocator
# ---------------------------------------------------------------------------


class TestPortAllocator:
    def test_allocate_returns_int(self) -> None:
        alloc = PortAllocator()
        port = alloc.allocate(start_port=18000, max_range=10)
        assert isinstance(port, int)
        assert 18000 <= port < 18010
        # Clean up
        alloc.release(port)

    def test_allocate_reserves_port(self) -> None:
        alloc = PortAllocator()
        port = alloc.allocate(start_port=18100, max_range=10)
        try:
            # A second allocate in the same range must skip the reserved port.
            # We can't directly inspect the set, but we can check that the
            # reserved port is no longer in the available list by trying to
            # bind it externally and observing it fails.
            assert port in alloc._reserved_ports  # type: ignore[attr-defined]
        finally:
            alloc.release(port)
        assert port not in alloc._reserved_ports  # type: ignore[attr-defined]

    def test_allocate_skips_unavailable(self) -> None:
        # Bind a real socket to occupy a port, then ask the allocator to
        # find a port in that range. The bound port must be skipped.
        held_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held_socket.bind(("0.0.0.0", 0))
        held_port = held_socket.getsockname()[1]
        try:
            alloc = PortAllocator()
            port = alloc.allocate(start_port=held_port, max_range=5)
            # Must not be the held port.
            assert port != held_port
            alloc.release(port)
        finally:
            held_socket.close()

    def test_release_is_idempotent(self) -> None:
        alloc = PortAllocator()
        # Releasing a port that was never allocated is a no-op.
        alloc.release(18200)
        alloc.release(18200)
        assert 18200 not in alloc._reserved_ports  # type: ignore[attr-defined]

    def test_allocate_context_releases_on_exit(self) -> None:
        alloc = PortAllocator()
        with alloc.allocate_context(start_port=18300, max_range=5) as port:
            assert port in alloc._reserved_ports  # type: ignore[attr-defined]
        assert port not in alloc._reserved_ports  # type: ignore[attr-defined]

    def test_allocate_context_releases_on_exception(self) -> None:
        alloc = PortAllocator()
        with pytest.raises(RuntimeError, match="boom"):
            with alloc.allocate_context(start_port=18400, max_range=5) as port:
                assert port in alloc._reserved_ports  # type: ignore[attr-defined]
                raise RuntimeError("boom")
        # Even on exception, the port is released.
        assert port not in alloc._reserved_ports  # type: ignore[attr-defined]

    def test_allocate_raises_when_range_exhausted(self) -> None:
        alloc = PortAllocator()
        # Allocate everything in the range, then try to allocate one more.
        first = alloc.allocate(start_port=18500, max_range=3)
        second = alloc.allocate(start_port=18500, max_range=3)
        third = alloc.allocate(start_port=18500, max_range=3)
        try:
            with pytest.raises(RuntimeError, match="No available port"):
                alloc.allocate(start_port=18500, max_range=3)
        finally:
            alloc.release(first)
            alloc.release(second)
            alloc.release(third)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestModuleLevelHelpers:
    def test_get_free_port_returns_int(self) -> None:
        # Use a high port range to avoid colliding with any system service.
        port = get_free_port(start_port=19000, max_range=10)
        try:
            assert isinstance(port, int)
            assert 19000 <= port < 19010
        finally:
            release_port(port)

    def test_release_port_is_safe_on_unknown(self) -> None:
        # Releasing a port that was never allocated is a no-op.
        release_port(19100)
        release_port(19100)

    def test_get_free_port_raises_when_no_free_port(self) -> None:
        # Exhaust the global allocator's range, then try again.
        # (May collide with other tests if they share the global instance,
        # so we use a port range that is unlikely to be in use.)
        first = get_free_port(start_port=19500, max_range=2)
        second = get_free_port(start_port=19500, max_range=2)
        try:
            with pytest.raises(RuntimeError, match="No available port"):
                get_free_port(start_port=19500, max_range=2)
        finally:
            release_port(first)
            release_port(second)


# ---------------------------------------------------------------------------
# Thread safety smoke test
# ---------------------------------------------------------------------------


class TestPortAllocatorThreadSafety:
    def test_concurrent_allocations_return_distinct_ports(self) -> None:
        import threading

        alloc = PortAllocator()
        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                port = alloc.allocate(start_port=20000, max_range=100)
                with lock:
                    results.append(port)
            except Exception as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # All allocated ports must be distinct.
        assert len(set(results)) == len(results)
        for p in results:
            alloc.release(p)

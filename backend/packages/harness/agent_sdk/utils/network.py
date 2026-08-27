"""Thread-safe network utilities.

This module is a re-implementation (per ADR-010) of
``deerflow.utils.network``.  It exposes a thread-safe
:class:`PortAllocator` that prevents port conflicts in
concurrent environments, plus module-level helpers that wrap a
process-wide allocator instance.

The class is intentionally tiny and dependency-free: it only
needs :mod:`socket` and :mod:`threading`.  It binds to the
wildcard address ``0.0.0.0`` (rather than ``127.0.0.1``) so
that the check matches what Docker does — Docker binds to
``0.0.0.0:PORT``; checking only the loopback can falsely
report a port as available even when Docker already occupies
it on the wildcard address.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class PortAllocator:
    """Thread-safe port allocator.

    Maintains a set of reserved ports and uses a lock to
    guarantee that :meth:`allocate` is atomic.  Once a port is
    allocated, it remains reserved until explicitly released
    via :meth:`release` or by exiting an
    :meth:`allocate_context` block.

    Example:
        >>> allocator = PortAllocator()
        >>> port = allocator.allocate(start_port=8080)  # doctest: +SKIP
        >>> try:
        ...     # ... use the port ...
        ... finally:
        ...     allocator.release(port)
        >>>
        >>> # Or as a context manager (recommended):
        >>> with allocator.allocate_context(start_port=8080) as port:  # doctest: +SKIP
        ...     # ... use the port ...
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reserved_ports: set[int] = set()

    def _is_port_available(self, port: int) -> bool:
        """Check whether *port* is currently free to bind.

        Returns:
            ``True`` if the port is not reserved and a
            wildcard bind succeeds; ``False`` if the port is
            reserved or already bound by another process.
        """
        if port in self._reserved_ports:
            return False

        # Bind to 0.0.0.0 (wildcard) rather than localhost so
        # that the check mirrors exactly what Docker does.
        # Docker binds to 0.0.0.0:PORT; checking only
        # 127.0.0.1 can falsely report a port as available
        # even when Docker already occupies it on the wildcard
        # address.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    def allocate(self, start_port: int = 8080, max_range: int = 100) -> int:
        """Allocate an available port in a thread-safe manner.

        Args:
            start_port: First port to consider.
            max_range: How many ports to try, starting at
                *start_port*.

        Returns:
            The first port in the range that is free.  The
            port is reserved until :meth:`release` is called.

        Raises:
            RuntimeError: If no port in the range is free.
        """
        with self._lock:
            for port in range(start_port, start_port + max_range):
                if self._is_port_available(port):
                    self._reserved_ports.add(port)
                    return port

            raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_range - 1}")

    def release(self, port: int) -> None:
        """Release a previously allocated port.

        Releasing a port that was never allocated (or that has
        already been released) is a no-op, so this method is
        always safe to call in cleanup paths.
        """
        with self._lock:
            self._reserved_ports.discard(port)

    @contextmanager
    def allocate_context(self, start_port: int = 8080, max_range: int = 100) -> Iterator[int]:
        """Context manager that allocates a port and releases it on exit.

        Example:
            >>> with allocator.allocate_context() as port:  # doctest: +SKIP
            ...     serve(port)
        """
        port = self.allocate(start_port, max_range)
        try:
            yield port
        finally:
            self.release(port)


#: Process-wide default allocator.  Use the module-level
#: helpers below to share a single instance across the
#: application.
_global_port_allocator = PortAllocator()


def get_free_port(start_port: int = 8080, max_range: int = 100) -> int:
    """Get a free port in a thread-safe manner.

    Wraps the global :data:`_global_port_allocator`.  The port
    is marked as reserved until :func:`release_port` is called.

    Args:
        start_port: First port to consider.
        max_range: How many ports to try, starting at
            *start_port*.

    Returns:
        An available port number.

    Raises:
        RuntimeError: If no port in the range is free.
    """
    return _global_port_allocator.allocate(start_port, max_range)


def release_port(port: int) -> None:
    """Release a previously allocated port.

    Args:
        port: The port to release.  Releasing a port that was
            never allocated is a no-op.
    """
    _global_port_allocator.release(port)

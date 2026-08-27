"""Per-(sandbox, path) operation locks.

This module is a re-implementation (per ADR-010) of
``deerflow.sandbox.file_operation_lock``. The lock map is a
:class:`weakref.WeakValueDictionary` so that locks are
garbage-collected when no thread holds a reference — this
prevents unbounded growth in long-running processes.

Locks are addressed by ``(sandbox_id, path)`` so that two
threads writing to *different* paths on the *same* sandbox
do not serialise, and two threads writing to the *same* path
on *different* sandboxes do not interfere.

A sandbox argument must expose an ``id`` attribute (string)
to be used as the first key component; if ``id`` is missing
or empty, the lock falls back to ``f"instance:{id(sandbox)}"``
which is unique per Python object.
"""

from __future__ import annotations

import threading
import weakref

#: Composite key: ``(sandbox_id, path)``.
_LockKey = tuple[str, str]

#: Backing storage. ``WeakValueDictionary`` evicts entries
#: when the value lock is no longer referenced from outside
#: this module (the ``get_file_operation_lock`` helper
#: returns the lock, so the caller holds a strong reference
#: for as long as the surrounding ``with`` block runs).
_FILE_OPERATION_LOCKS: weakref.WeakValueDictionary[_LockKey, threading.Lock] = weakref.WeakValueDictionary()

#: Mutex that serialises lookups / insertions into
#: :data:`_FILE_OPERATION_LOCKS` (its own thread-safe
#: guarantees aside from ``WeakValueDictionary``'s).
_FILE_OPERATION_LOCKS_GUARD = threading.Lock()


def get_file_operation_lock_key(sandbox: object, path: str) -> tuple[str, str]:
    """Build the ``(sandbox_id, path)`` key for *sandbox*.

    Falls back to ``f"instance:{id(sandbox)}"`` if the sandbox
    has no usable ``id`` attribute (i.e. it is not a
    :class:`agent_sdk.sandbox.Sandbox` subclass).
    """
    sandbox_id = getattr(sandbox, "id", None)
    if not sandbox_id:
        sandbox_id = f"instance:{id(sandbox)}"
    return sandbox_id, path


def get_file_operation_lock(sandbox: object, path: str) -> threading.Lock:
    """Return the per-``(sandbox, path)`` :class:`threading.Lock`.

    The returned lock is shared across callers: if two
    requests come in for the same key while the first is
    still in scope, they get the same lock object.
    """
    lock_key = get_file_operation_lock_key(sandbox, path)
    with _FILE_OPERATION_LOCKS_GUARD:
        lock = _FILE_OPERATION_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _FILE_OPERATION_LOCKS[lock_key] = lock
        return lock


__all__ = [
    "get_file_operation_lock",
    "get_file_operation_lock_key",
]

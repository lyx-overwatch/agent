"""CancelRegistry — per-conversation cancel tokens for streaming chat.

Each active SSE stream registers an :class:`asyncio.Event` keyed by
its ``conversation_id``.  The ``POST /chat/stream/stop`` endpoint
sets the event, and the streaming loop polls it cooperatively.

This is cooperative cancellation — the agent loop checks the event
at each iteration and exits cleanly, preserving the LangGraph
checkpoint for partial-content save.

**Thread-safe cancellation**: a :class:`threading.Event` is also
created per conversation so that synchronous code (notably
:class:`~agent_sdk.community.skillhub.subagent_runner.SubagentRunner`) can poll for
cancellation without needing an asyncio event loop.

Usage::

    from app.core.cancel_registry import cancel_registry

    event = cancel_registry.register(conversation_id)
    try:
        async for ...:
            if event.is_set():
                break
    finally:
        cancel_registry.unregister(conversation_id)
"""

from __future__ import annotations

import asyncio
import threading

from loguru import logger


class CancelRegistry:
    """In-process registry of active stream cancel events.

    Thread-safe for use from concurrent asyncio tasks within the same process.
    Maintains both an :class:`asyncio.Event` (for async code) and a
    :class:`threading.Event` (for synchronous code like subagent runners).

    A single pair per conversation — multiple concurrent streams
    for the same conversation are not supported (the second registration
    replaces the first).
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._thread_events: dict[str, threading.Event] = {}

    def register(self, conversation_id: str) -> asyncio.Event:
        """Create and store a cancel event for *conversation_id*.

        Creates both an :class:`asyncio.Event` (returned) and a
        :class:`threading.Event` (available via :meth:`get_thread_event`).

        If an event already exists for this conversation (e.g. a stale
        stream), it is replaced.  The caller MUST call :meth:`unregister`
        when the stream ends.
        """
        event = asyncio.Event()
        self._events[conversation_id] = event
        self._thread_events[conversation_id] = threading.Event()
        logger.debug("CancelRegistry: registered {}", conversation_id)
        return event

    def cancel(self, conversation_id: str) -> bool:
        """Signal cancellation for *conversation_id*.

        Sets both the asyncio and threading events so cancellation
        is visible to async and synchronous code alike.

        Returns:
            ``True`` if a stream was found and cancelled,
            ``False`` if there is no active stream for this conversation.
        """
        event = self._events.get(conversation_id)
        if event is None:
            logger.debug("CancelRegistry: no active stream for {}", conversation_id)
            return False
        if event.is_set():
            logger.debug("CancelRegistry: {} already cancelled", conversation_id)
            return True  # idempotent — already cancelled
        event.set()
        # Also signal the thread-safe event for synchronous code paths
        # (e.g. SubagentRunner polling inside _future.result).
        thread_event = self._thread_events.get(conversation_id)
        if thread_event is not None:
            thread_event.set()
        logger.info("CancelRegistry: cancelled {}", conversation_id)
        return True

    def get_thread_event(self, conversation_id: str) -> threading.Event | None:
        """Return the :class:`threading.Event` for *conversation_id*, if any.

        Returns ``None`` when no stream is registered for this conversation.
        """
        return self._thread_events.get(conversation_id)

    def unregister(self, conversation_id: str) -> None:
        """Remove the cancel events for *conversation_id*."""
        self._events.pop(conversation_id, None)
        self._thread_events.pop(conversation_id, None)
        logger.debug("CancelRegistry: unregistered {}", conversation_id)

    def is_active(self, conversation_id: str) -> bool:
        """Check whether a stream is currently registered for *conversation_id*."""
        return conversation_id in self._events


# Module-level singleton used by routes and services.
cancel_registry = CancelRegistry()

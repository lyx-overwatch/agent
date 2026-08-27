"""Abstract stream bridge for SSE delivery.

This module is a re-implementation (per ADR-010) of the
in-tree ``deerflow.runtime.stream_bridge`` base.  It
decouples agent workers (producers) from SSE endpoints
(consumers), aligning with LangGraph Platform's
*Queue + StreamManager* architecture.

A :class:`StreamBridge` is the brand-neutral contract that
backs the runtime's streaming responses.  Producers (the
agent worker that calls :meth:`StreamBridge.publish` for each
agent event) and consumers (the SSE endpoint that calls
:meth:`StreamBridge.subscribe` to replay buffered events to a
client) need to agree on three things:

* a ``run_id`` namespace (a single agent run produces events
  for one ``run_id``; multiple runs are independent);
* an event id scheme (monotonically increasing per
  ``run_id``, so that ``Last-Event-ID`` reconnection works);
* lifecycle sentinels (heartbeat and end).

The :class:`StreamBridge` ABC exposes the minimum surface
needed to support all of the above; concrete implementations
(in-memory, Redis pub/sub, Postgres listen/notify, etc.) live
outside the SDK and are injected by the caller.

.. autosummary::

   StreamBridge           — abstract base
   MemoryStreamBridge     — in-process (asyncio.Queue) reference implementation
   StreamEvent            — data class
   HEARTBEAT_SENTINEL     — keep-alive
   END_SENTINEL           — stream terminator
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StreamEvent:
    """Single stream event delivered to subscribers.

    Attributes:
        id: Monotonically increasing event id within a run
            (used as the SSE ``id:`` field, which lets
            clients reconnect with ``Last-Event-ID``).
            Implementations are free to pick any
            monotonically-increasing scheme; consumers
            treat the id as an opaque string.
        event: SSE event name — e.g. ``"metadata"``,
            ``"updates"``, ``"events"``, ``"error"``,
            ``"end"``.  Reserved internal names are
            :data:`HEARTBEAT_SENTINEL` (``"__heartbeat__"``)
            and :data:`END_SENTINEL` (``"__end__"``).
        data: JSON-serialisable payload.  ``None`` is
            reserved for the two sentinels.
    """

    id: str
    event: str
    data: Any


#: Sentinel yielded by :meth:`StreamBridge.subscribe` when no
#: event has been produced within the heartbeat interval.
#: Consumers should treat this as a keep-alive and re-emit an
#: SSE comment frame.
HEARTBEAT_SENTINEL: StreamEvent = StreamEvent(id="", event="__heartbeat__", data=None)

#: Sentinel yielded by :meth:`StreamBridge.subscribe` once
#: the producer calls :meth:`StreamBridge.publish_end` for
#: the run.  After this the iterator terminates.
END_SENTINEL: StreamEvent = StreamEvent(id="", event="__end__", data=None)


class StreamBridge(abc.ABC):
    """Abstract base for stream bridges.

    Implementations MUST guarantee that:

    * multiple subscribers for the same ``run_id`` all observe
      the same sequence of events (fan-out is the bridge's
      job, not the producer's);
    * the iterator returned by :meth:`subscribe` always
      terminates — either by yielding :data:`END_SENTINEL`
      (after the producer called :meth:`publish_end`), or by
      raising if the bridge itself is closed;
    * a :meth:`publish` after :meth:`publish_end` for the
      same ``run_id`` is a programming error and may be
      ignored, dropped, or surfaced — the contract does not
      mandate a specific behaviour.
    """

    @abc.abstractmethod
    async def publish(self, run_id: str, event: str, data: Any) -> None:
        """Enqueue a single event for *run_id* (producer side).

        Args:
            run_id: The agent run that produced this event.
            event: SSE event name.
            data: JSON-serialisable payload.  Must not be the
                sentinel event names reserved by the bridge
                (``"__heartbeat__"``, ``"__end__"``).
        """

    @abc.abstractmethod
    async def publish_end(self, run_id: str) -> None:
        """Signal that no more events will be produced for *run_id*.

        After this call, existing :meth:`subscribe` iterators
        for *run_id* will eventually yield :data:`END_SENTINEL`
        and terminate.  New :meth:`subscribe` iterators may
        return an empty stream (no buffered events) followed
        by :data:`END_SENTINEL`.
        """

    @abc.abstractmethod
    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        """Async iterator that yields events for *run_id*.

        Args:
            run_id: The agent run to subscribe to.
            last_event_id: If provided, the iterator will
                resume from the event *after* this id (replay
                the buffered tail).  If the id is unknown
                (older than the bridge's retention window) the
                implementation should log a warning and
                resume from the oldest buffered event.
            heartbeat_interval: Maximum number of seconds the
                iterator will block waiting for the next
                event before yielding
                :data:`HEARTBEAT_SENTINEL`.  Set to a
                non-positive value to disable heartbeats.

        Yields:
            :class:`StreamEvent` instances.  The iterator
            will yield :data:`HEARTBEAT_SENTINEL` when no
            event arrives within *heartbeat_interval*
            seconds, and :data:`END_SENTINEL` once the
            producer calls :meth:`publish_end`.
        """

    @abc.abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Release resources associated with *run_id*.

        Args:
            run_id: The agent run to clean up.
            delay: If positive, the implementation should
                wait this many seconds before releasing
                state, giving late subscribers a chance to
                drain any remaining buffered events.  A
                delay of ``0`` (the default) means "release
                immediately".
        """

    async def close(self) -> None:
        """Release backend-wide resources.  Default is a no-op.

        Override this in implementations that own a process,
        a connection pool, or a long-lived background task.
        """


# Concrete implementation
from agent_sdk.runtime.stream_bridge.memory import MemoryStreamBridge  # noqa: E402, F401
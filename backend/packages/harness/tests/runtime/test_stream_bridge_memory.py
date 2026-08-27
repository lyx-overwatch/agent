"""Tests for :class:`agent_sdk.runtime.stream_bridge.memory.MemoryStreamBridge`."""

from __future__ import annotations

import asyncio

import pytest
from agent_sdk.runtime.stream_bridge import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    MemoryStreamBridge,
    StreamEvent,
)


class TestMemoryStreamBridge:
    """Unit tests for MemoryStreamBridge."""

    # ------------------------------------------------------------------
    # publish / subscribe basic flow
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_publish_and_subscribe_single_event(self) -> None:
        bridge = MemoryStreamBridge()
        await bridge.publish("run-1", "metadata", {"key": "value"})
        await bridge.publish_end("run-1")

        events = []
        async for ev in bridge.subscribe("run-1"):
            events.append(ev)

        assert len(events) == 2  # metadata + END_SENTINEL
        assert events[0].event == "metadata"
        assert events[0].data == {"key": "value"}
        assert events[1] is END_SENTINEL

    @pytest.mark.asyncio
    async def test_subscribe_before_publish(self) -> None:
        bridge = MemoryStreamBridge()

        async def _collect() -> list[StreamEvent]:
            events = []
            async for ev in bridge.subscribe("run-1"):
                events.append(ev)
                if ev is END_SENTINEL:
                    break
            return events

        task = asyncio.create_task(_collect())
        await asyncio.sleep(0.05)  # let subscriber start waiting
        await bridge.publish("run-1", "event", "data")
        await bridge.publish_end("run-1")

        events = await task
        assert len(events) == 2
        assert events[0].event == "event"
        assert events[1] is END_SENTINEL

    # ------------------------------------------------------------------
    # multiple events
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multiple_events_in_order(self) -> None:
        bridge = MemoryStreamBridge()
        for i in range(5):
            await bridge.publish("run-1", f"event-{i}", i)
        await bridge.publish_end("run-1")

        events = []
        async for ev in bridge.subscribe("run-1"):
            events.append(ev)

        assert len(events) == 6
        for i in range(5):
            assert events[i].event == f"event-{i}"
            assert events[i].data == i
        assert events[5] is END_SENTINEL

    # ------------------------------------------------------------------
    # Last-Event-ID replay
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_last_event_id_replay(self) -> None:
        bridge = MemoryStreamBridge()
        for i in range(3):
            await bridge.publish("run-1", f"e{i}", i)
        await bridge.publish_end("run-1")

        # First, read all events to get the id of the first event
        first_id = None
        async for ev in bridge.subscribe("run-1"):
            if first_id is None and ev is not END_SENTINEL:
                first_id = ev.id
            if ev is END_SENTINEL:
                break

        # Replay from after the first event
        assert first_id is not None
        events = []
        async for ev in bridge.subscribe("run-1", last_event_id=first_id):
            events.append(ev)

        assert len(events) == 3  # e1, e2, END
        assert events[0].event == "e1"
        assert events[1].event == "e2"
        assert events[2] is END_SENTINEL

    @pytest.mark.asyncio
    async def test_last_event_id_unknown_falls_back(self) -> None:
        bridge = MemoryStreamBridge()
        await bridge.publish("run-1", "e0", 0)
        await bridge.publish_end("run-1")

        events = []
        async for ev in bridge.subscribe("run-1", last_event_id="nonexistent"):
            events.append(ev)

        assert len(events) == 2  # falls back to oldest + END
        assert events[0].event == "e0"
        assert events[1] is END_SENTINEL

    # ------------------------------------------------------------------
    # heartbeat
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_heartbeat_sentinel(self) -> None:
        bridge = MemoryStreamBridge()

        events = []
        gen = bridge.subscribe("run-1", heartbeat_interval=0.05)

        async def _collect_until_end() -> None:
            async for ev in gen:
                events.append(ev)
                if ev is END_SENTINEL:
                    break

        task = asyncio.create_task(_collect_until_end())
        await asyncio.sleep(0.15)  # wait for at least one heartbeat
        await bridge.publish_end("run-1")
        await task

        # Should have at least one heartbeat + END
        assert len(events) >= 2
        assert any(ev is HEARTBEAT_SENTINEL for ev in events)
        assert events[-1] is END_SENTINEL

    # ------------------------------------------------------------------
    # buffer eviction (queue_maxsize)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_buffer_eviction(self) -> None:
        bridge = MemoryStreamBridge(queue_maxsize=3)
        for i in range(5):
            await bridge.publish("run-1", f"e{i}", i)
        await bridge.publish_end("run-1")

        events = []
        async for ev in bridge.subscribe("run-1"):
            events.append(ev)

        # Only the last 3 events + END are retained
        assert len(events) == 4
        assert events[0].event == "e2"
        assert events[1].event == "e3"
        assert events[2].event == "e4"
        assert events[3] is END_SENTINEL

    # ------------------------------------------------------------------
    # multiple runs — isolation
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_isolation(self) -> None:
        bridge = MemoryStreamBridge()
        await bridge.publish("run-a", "a", 1)
        await bridge.publish("run-b", "b", 2)
        await bridge.publish_end("run-a")
        await bridge.publish_end("run-b")

        events_a = [ev async for ev in bridge.subscribe("run-a")]
        events_b = [ev async for ev in bridge.subscribe("run-b")]

        assert len(events_a) == 2  # a + END
        assert events_a[0].event == "a"
        assert events_a[0].data == 1
        assert events_a[1] is END_SENTINEL

        assert len(events_b) == 2  # b + END
        assert events_b[0].event == "b"
        assert events_b[0].data == 2
        assert events_b[1] is END_SENTINEL

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cleanup_removes_run(self) -> None:
        bridge = MemoryStreamBridge()
        await bridge.publish("run-1", "e", 0)
        await bridge.publish_end("run-1")

        await bridge.cleanup("run-1")
        # A new subscriber for a cleaned-up run gets a fresh stream
        await bridge.publish("run-1", "new", 1)
        await bridge.publish_end("run-1")

        events = []
        async for ev in bridge.subscribe("run-1"):
            events.append(ev)

        assert len(events) == 2
        assert events[0].event == "new"

    # ------------------------------------------------------------------
    # close
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_close_clears_all(self) -> None:
        bridge = MemoryStreamBridge()
        await bridge.publish("run-1", "e", 0)
        await bridge.close()

        # After close, a new run starts fresh
        await bridge.publish("run-2", "f", 1)
        await bridge.publish_end("run-2")

        events = []
        async for ev in bridge.subscribe("run-2"):
            events.append(ev)

        assert len(events) == 2
        assert events[0].event == "f"

    # ------------------------------------------------------------------
    # multiple subscribers (fan-out)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multiple_subscribers_see_same_events(self) -> None:
        bridge = MemoryStreamBridge()

        async def _collect(sub_id: int) -> list[StreamEvent]:
            events = []
            async for ev in bridge.subscribe("run-1"):
                events.append(ev)
                if ev is END_SENTINEL:
                    break
            return events

        tasks = [asyncio.create_task(_collect(i)) for i in range(3)]
        await asyncio.sleep(0.05)
        await bridge.publish("run-1", "shared", "data")
        await bridge.publish_end("run-1")

        results = await asyncio.gather(*tasks)
        for events in results:
            assert len(events) == 2
            assert events[0].event == "shared"
            assert events[0].data == "data"
            assert events[1] is END_SENTINEL

    # ------------------------------------------------------------------
    # StreamEvent dataclass
    # ------------------------------------------------------------------

    def test_stream_event_immutable(self) -> None:
        ev = StreamEvent(id="1", event="test", data={"x": 1})
        with pytest.raises(Exception):
            ev.id = "2"  # type: ignore[misc]

    def test_sentinels_are_stream_events(self) -> None:
        assert isinstance(HEARTBEAT_SENTINEL, StreamEvent)
        assert isinstance(END_SENTINEL, StreamEvent)
        assert HEARTBEAT_SENTINEL.event == "__heartbeat__"
        assert END_SENTINEL.event == "__end__"
        assert HEARTBEAT_SENTINEL.data is None
        assert END_SENTINEL.data is None
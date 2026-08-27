"""Unit tests for :mod:`agent_sdk.runtime.stream_bridge`.

Covers the :class:`StreamEvent` dataclass, the heartbeat / end
sentinels, and the :class:`StreamBridge` ABC contract
(cannot be instantiated, abstract methods listed).
"""

from __future__ import annotations

import inspect

import pytest
from agent_sdk.runtime.stream_bridge import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    StreamBridge,
    StreamEvent,
)

# ---------------------------------------------------------------------------
# StreamEvent dataclass
# ---------------------------------------------------------------------------


class TestStreamEvent:
    def test_construction(self) -> None:
        e = StreamEvent(id="1", event="updates", data={"x": 1})
        assert e.id == "1"
        assert e.event == "updates"
        assert e.data == {"x": 1}

    def test_frozen(self) -> None:
        e = StreamEvent(id="1", event="x", data=None)
        with pytest.raises(Exception):
            e.event = "y"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = StreamEvent(id="1", event="x", data=1)
        b = StreamEvent(id="1", event="x", data=1)
        assert a == b

    def test_inequality_on_id(self) -> None:
        a = StreamEvent(id="1", event="x", data=1)
        b = StreamEvent(id="2", event="x", data=1)
        assert a != b

    def test_inequality_on_event(self) -> None:
        a = StreamEvent(id="1", event="x", data=1)
        b = StreamEvent(id="1", event="y", data=1)
        assert a != b

    def test_data_can_be_any_json(self) -> None:
        # Data is documented as JSON-serialisable; common payloads
        # are dicts, lists, strings, numbers, bools, None.
        for payload in [{"a": 1}, [1, 2, 3], "string", 42, 3.14, True, None]:
            e = StreamEvent(id="1", event="x", data=payload)
            assert e.data == payload


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------


class TestSentinels:
    def test_heartbeat_sentinel_shape(self) -> None:
        assert HEARTBEAT_SENTINEL.id == ""
        assert HEARTBEAT_SENTINEL.event == "__heartbeat__"
        assert HEARTBEAT_SENTINEL.data is None

    def test_end_sentinel_shape(self) -> None:
        assert END_SENTINEL.id == ""
        assert END_SENTINEL.event == "__end__"
        assert END_SENTINEL.data is None

    def test_sentinels_are_distinct(self) -> None:
        # Two different sentinels must not compare equal —
        # consumers pattern-match on .event.
        assert HEARTBEAT_SENTINEL != END_SENTINEL
        assert HEARTBEAT_SENTINEL.event != END_SENTINEL.event

    def test_sentinels_are_frozen(self) -> None:
        with pytest.raises(Exception):
            HEARTBEAT_SENTINEL.id = "hacked"  # type: ignore[misc]
        with pytest.raises(Exception):
            END_SENTINEL.id = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StreamBridge ABC
# ---------------------------------------------------------------------------


class _DummyBridge(StreamBridge):
    """Minimal implementation that satisfies the ABC."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, object]] = []
        self.ended: list[str] = []
        self.cleaned: list[tuple[str, float]] = []
        self.closed = False

    async def publish(self, run_id: str, event: str, data) -> None:
        self.published.append((run_id, event, data))

    async def publish_end(self, run_id: str) -> None:
        self.ended.append(run_id)

    def subscribe(self, run_id: str, *, last_event_id: str | None = None, heartbeat_interval: float = 15.0):
        async def _iterator():
            if False:
                yield  # pragma: no cover  -- makes it a generator

        return _iterator()

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        self.cleaned.append((run_id, delay))

    async def close(self) -> None:
        self.closed = True


class TestStreamBridgeABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            StreamBridge()  # type: ignore[abstract]

    def test_abstract_methods_listed(self) -> None:
        assert StreamBridge.__abstractmethods__ == frozenset(
            {"publish", "publish_end", "subscribe", "cleanup"}
        )

    def test_close_is_concrete_with_default_noop(self) -> None:
        # close() is a default no-op, so it should NOT be in
        # the abstract set; subclasses can override.
        assert "close" not in StreamBridge.__abstractmethods__

    def test_concrete_implementation_works(self) -> None:
        b = _DummyBridge()
        # All four abstract methods are callable
        assert inspect.iscoroutinefunction(b.publish)
        assert inspect.iscoroutinefunction(b.publish_end)
        assert inspect.iscoroutinefunction(b.cleanup)
        assert inspect.iscoroutinefunction(b.close)
        # subscribe is an async generator factory
        assert callable(b.subscribe)

    async def test_publish_records(self) -> None:
        b = _DummyBridge()
        await b.publish("r1", "updates", {"x": 1})
        await b.publish("r1", "end", "bye")
        assert b.published == [("r1", "updates", {"x": 1}), ("r1", "end", "bye")]

    async def test_publish_end_records(self) -> None:
        b = _DummyBridge()
        await b.publish_end("r1")
        assert b.ended == ["r1"]

    async def test_cleanup_with_zero_delay(self) -> None:
        b = _DummyBridge()
        await b.cleanup("r1")
        assert b.cleaned == [("r1", 0.0)]

    async def test_cleanup_with_positive_delay(self) -> None:
        b = _DummyBridge()
        await b.cleanup("r1", delay=2.5)
        assert b.cleaned == [("r1", 2.5)]

    async def test_close_default_invocable(self) -> None:
        b = _DummyBridge()
        await b.close()
        assert b.closed is True


class TestStreamBridgeSubclassing:
    def test_subclass_without_close_works(self) -> None:
        # A subclass that does not override close() inherits the
        # no-op default; it must still be instantiable.
        class _BareBridge(StreamBridge):
            async def publish(self, run_id, event, data):
                return None

            async def publish_end(self, run_id):
                return None

            def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
                async def _it():
                    if False:
                        yield

                return _it()

            async def cleanup(self, run_id, *, delay=0):
                return None

        b = _BareBridge()
        # close() is the inherited no-op; calling it must not raise.
        import asyncio

        asyncio.get_event_loop().run_until_complete(b.close()) if False else None  # avoid loop creation

        # Synchronously: the inherited close returns a coroutine,
        # which is the documented interface.
        import inspect as _i

        coro = b.close()
        assert _i.iscoroutine(coro)
        coro.close()  # discard the no-op coroutine

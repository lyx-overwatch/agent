"""Unit tests for :mod:`agent_sdk.runtime.langgraph_integration`.

Covers the small helpers (:func:`make_thread_config`,
:func:`merge_configs`, :func:`make_run_id`,
:func:`is_valid_thread_id`) and the re-exported stream-mode
constants.
"""

from __future__ import annotations

import pytest
from agent_sdk.runtime.langgraph_integration import (
    CHECKPOINT_NS,
    RUN_ID,
    STREAM_MODE_MESSAGES,
    STREAM_MODE_UPDATES,
    STREAM_MODE_VALUES,
    STREAM_MODE_VALUES_DEFAULT,
    THREAD_ID,
    USER_ID,
    is_valid_thread_id,
    make_run_id,
    make_thread_config,
    merge_configs,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_thread_id_key(self) -> None:
        assert THREAD_ID == "thread_id"

    def test_user_id_key(self) -> None:
        assert USER_ID == "user_id"

    def test_run_id_key(self) -> None:
        assert RUN_ID == "run_id"

    def test_checkpoint_ns_key(self) -> None:
        assert CHECKPOINT_NS == "checkpoint_ns"

    def test_stream_mode_singletons_are_strings(self) -> None:
        # The single-mode convenience constants are strings.
        for mode in (STREAM_MODE_UPDATES, STREAM_MODE_MESSAGES, STREAM_MODE_VALUES_DEFAULT):
            assert isinstance(mode, str)
            assert mode

    def test_stream_mode_values_is_tuple_of_all(self) -> None:
        # The full set of standard LangGraph stream modes is
        # available as a tuple.
        assert isinstance(STREAM_MODE_VALUES, tuple)
        for mode in ("values", "updates", "messages", "events", "custom"):
            assert mode in STREAM_MODE_VALUES

    def test_default_matches_values_constant(self) -> None:
        # STREAM_MODE_VALUES_DEFAULT is just a clearer alias for
        # "values" — the default snapshot mode.
        assert STREAM_MODE_VALUES_DEFAULT == "values"
        assert STREAM_MODE_VALUES_DEFAULT in STREAM_MODE_VALUES


# ---------------------------------------------------------------------------
# make_thread_config
# ---------------------------------------------------------------------------


class TestMakeThreadConfig:
    def test_minimal(self) -> None:
        cfg = make_thread_config("t-1")
        assert cfg == {"configurable": {"thread_id": "t-1", "checkpoint_ns": ""}}

    def test_with_user_id(self) -> None:
        cfg = make_thread_config("t-1", user_id="u-1")
        assert cfg["configurable"]["user_id"] == "u-1"
        assert cfg["configurable"]["thread_id"] == "t-1"

    def test_with_run_id(self) -> None:
        cfg = make_thread_config("t-1", run_id="r-1")
        assert cfg["configurable"]["run_id"] == "r-1"

    def test_with_checkpoint_ns(self) -> None:
        cfg = make_thread_config("t-1", checkpoint_ns="subgraph")
        assert cfg["configurable"]["checkpoint_ns"] == "subgraph"

    def test_all_optional_keys(self) -> None:
        cfg = make_thread_config("t-1", user_id="u-1", run_id="r-1", checkpoint_ns="ns")
        assert cfg["configurable"] == {
            "thread_id": "t-1",
            "user_id": "u-1",
            "run_id": "r-1",
            "checkpoint_ns": "ns",
        }


# ---------------------------------------------------------------------------
# merge_configs
# ---------------------------------------------------------------------------


class TestMergeConfigs:
    def test_no_args_returns_empty(self) -> None:
        assert merge_configs() == {}

    def test_single_config_passthrough(self) -> None:
        cfg = make_thread_config("t-1")
        assert merge_configs(cfg) == cfg

    def test_two_configurable_overrides(self) -> None:
        a = make_thread_config("t-1", user_id="u-1")
        b = make_thread_config("t-2", user_id="u-2")
        merged = merge_configs(a, b)
        assert merged["configurable"]["thread_id"] == "t-2"
        assert merged["configurable"]["user_id"] == "u-2"

    def test_non_configurable_keys_preserved(self) -> None:
        a = {"metadata": {"k": 1}}
        b = make_thread_config("t-1")
        merged = merge_configs(a, b)
        assert merged["metadata"] == {"k": 1}
        assert merged["configurable"]["thread_id"] == "t-1"

    def test_overlapping_non_configurable_keys(self) -> None:
        a = {"metadata": {"k": 1}}
        b = {"metadata": {"k": 2}}
        merged = merge_configs(a, b)
        # Later wins (no deep merge of top-level non-configurable keys).
        assert merged["metadata"] == {"k": 2}

    def test_none_configs_are_skipped(self) -> None:
        a = make_thread_config("t-1")
        # Falsy values should be skipped
        merged = merge_configs(None, a, None, {}, {})  # type: ignore[arg-type]
        assert merged == a


# ---------------------------------------------------------------------------
# make_run_id
# ---------------------------------------------------------------------------


class TestMakeRunId:
    def test_returns_string(self) -> None:
        rid = make_run_id()
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_unique(self) -> None:
        ids = {make_run_id() for _ in range(100)}
        assert len(ids) == 100

    def test_is_hex_safe(self) -> None:
        # UUID4 hex is 32 chars and is a valid path / header value.
        rid = make_run_id()
        assert len(rid) == 32
        assert all(c in "0123456789abcdef" for c in rid)


# ---------------------------------------------------------------------------
# is_valid_thread_id
# ---------------------------------------------------------------------------


class TestIsValidThreadId:
    @pytest.mark.parametrize(
        "tid",
        ["abc", "thread-1", "T_001", "thread_v2", "A-B-c-D-9"],
    )
    def test_valid_ids(self, tid: str) -> None:
        assert is_valid_thread_id(tid) is True

    @pytest.mark.parametrize(
        "tid",
        ["user.42", "a-b.c_d", "thread.v1"],
    )
    def test_dot_is_rejected(self, tid: str) -> None:
        # Dots are rejected to match the backend's
        # ``deerflow.config.paths._validate_thread_id`` regex
        # (``^[A-Za-z0-9_-]+$``) — a thread_id that crosses
        # the SDK/backend persistence boundary must validate
        # on both sides.
        assert is_valid_thread_id(tid) is False

    @pytest.mark.parametrize(
        "tid",
        [
            "",  # empty
            "a" * 129,  # too long
            "with space",  # contains space
            "with/slash",  # contains slash
            "with:colon",  # contains colon
            "with;semicolon",
            "with\nnewline",
        ],
    )
    def test_invalid_ids(self, tid: str) -> None:
        assert is_valid_thread_id(tid) is False

    def test_exactly_128_chars_is_valid(self) -> None:
        assert is_valid_thread_id("a" * 128) is True

    def test_exactly_129_chars_is_invalid(self) -> None:
        assert is_valid_thread_id("a" * 129) is False

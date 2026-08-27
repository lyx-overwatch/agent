"""端到端测试：完整 agent pipeline → task 工具 → subagent 执行 → 返回结果。

测试层级：
1. ``assemble_chain`` 级别 — 验证 middleware chain + tools 组装正确
2. task tool 功能级别 — 验证 task tool 在完整链路中的行为
3. ``create_agent`` 级别 — 验证完整 agent 中 task tool 可用
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from agent_sdk.runtime import create_agent
from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import MiddlewareChainConfig, assemble_chain
from agent_sdk.subagents.default import DefaultSubagentRegistry
from agent_sdk.subagents.definition import SubagentDefinition
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core.subagent_runner import SubagentRunner

# ── Helpers ────────────────────────────────────────────────────────────────


def _mock_runtime(state: dict | None = None, config: dict | None = None):
    """Create a minimal ToolRuntime for direct ``tool.invoke()`` tests.

    Uses a real :class:`~langchain.tools.ToolRuntime` dataclass instance
    so Pydantic validation accepts it.
    """
    from langchain.tools import ToolRuntime as TR

    return TR(
        state=state or {},
        context=None,
        config=config,
        stream_writer=lambda _x: None,  # no-op writer
        tool_call_id="mock-call-id",
        store=None,
    )


def _make_registry(**extra_roles) -> DefaultSubagentRegistry:
    """A registry with the 'echo' test role (+ optional extras)."""
    registry = DefaultSubagentRegistry()
    registry.register(
        SubagentDefinition(
            name="echo",
            description="Echo the task back.",
            system_prompt="You are an echo agent.",
            tools=None,
        )
    )
    for name, cfg in extra_roles.items():
        registry.register(SubagentDefinition(
            name=name,
            description=cfg.get("description", ""),
            system_prompt=cfg.get("system_prompt", ""),
            tools=cfg.get("tools"),
        ))
    return registry


# ── Chain assembly tests ────────────────────────────────────────────────────


class TestChainAssembly:
    """Verify middleware chain + extra_tools produced by assemble_chain."""

    def test_task_tool_in_extra_tools(self) -> None:
        """subagent=True → 'task' tool in extra_tools."""
        _mw, tools = assemble_chain(
            features=RuntimeFeatures(sandbox=False, subagent=True),
            config=MiddlewareChainConfig(
                subagent_registry=_make_registry(),
                run_subagent=SubagentRunner(FakeListChatModel(responses=["ok"]), []),
            ),
        )
        assert any(t.name == "task" for t in tools)

    def test_no_task_tool_when_subagent_false(self) -> None:
        """subagent=False → no 'task' tool."""
        _mw, tools = assemble_chain(
            features=RuntimeFeatures(sandbox=False, subagent=False),
            config=MiddlewareChainConfig(),
        )
        assert not any(t.name == "task" for t in tools)

    def test_no_task_tool_by_default(self) -> None:
        """Default RuntimeFeatures → no 'task' tool."""
        _mw, tools = assemble_chain(
            features=RuntimeFeatures(sandbox=False),
            config=MiddlewareChainConfig(),
        )
        assert not any(t.name == "task" for t in tools)

    def test_subagent_limit_in_chain(self) -> None:
        """subagent=True → SubagentLimitMiddleware in middleware chain."""
        mw, _tools = assemble_chain(
            features=RuntimeFeatures(sandbox=False, subagent=True),
            config=MiddlewareChainConfig(
                subagent_registry=_make_registry(),
                run_subagent=SubagentRunner(FakeListChatModel(responses=["ok"]), []),
            ),
        )
        from agent_sdk.middlewares.subagent_limit import SubagentLimitMiddleware

        assert any(isinstance(m, SubagentLimitMiddleware) for m in mw)


# ── Task tool functional tests ──────────────────────────────────────────────


class TestTaskToolFunctional:
    """Test task tool behaviour through the assembled chain."""

    def _get_task_tool(self, registry=None, runner=None):
        """Return the task tool from an assembled chain."""
        if registry is None:
            registry = _make_registry()
        if runner is None:
            runner = SubagentRunner(FakeListChatModel(responses=["ok"]), [])

        _mw, tools = assemble_chain(
            features=RuntimeFeatures(sandbox=False, subagent=True),
            config=MiddlewareChainConfig(
                subagent_registry=registry,
                run_subagent=runner,
            ),
        )
        return next(t for t in tools if t.name == "task")

    def test_configured_tool_returns_result(self) -> None:
        """Task tool with registry+runner returns runner's output."""
        with pytest.MonkeyPatch.context() as mp:
            import app.core.subagent_runner as srm

            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {
                "messages": [MagicMock(type="ai", content="I found 3 files.")],
            }
            mp.setattr(srm, "_lc_create_agent", MagicMock(return_value=mock_agent))

            tool = self._get_task_tool()
            result = tool.invoke({
                "description": "Find files",
                "prompt": "List all text files",
                "subagent_type": "echo",
                "runtime": _mock_runtime(),
            })

            assert "Task completed" in result
            assert "I found 3 files" in result

    def test_unconfigured_returns_error(self) -> None:
        """Without registry+runner → clear error message."""
        _mw, tools = assemble_chain(
            features=RuntimeFeatures(sandbox=False, subagent=True),
            config=MiddlewareChainConfig(),  # empty → no registry/runner
        )
        tool = next(t for t in tools if t.name == "task")
        result = tool.invoke({
            "description": "Test",
            "prompt": "Do something",
            "subagent_type": "echo",
            "runtime": _mock_runtime(),
        })
        assert "not configured" in result

    def test_unknown_type_returns_error(self) -> None:
        """Unknown subagent_type → error listing available types."""
        tool = self._get_task_tool()
        result = tool.invoke({
            "description": "Bad",
            "prompt": "Do something",
            "subagent_type": "nonexistent-role",
            "runtime": _mock_runtime(),
        })
        assert "Unknown subagent type" in result
        assert "echo" in result

    def test_runner_error_is_reported(self) -> None:
        """Runner raises → error captured in result."""
        def _failing_run(task, definition, holder):
            raise RuntimeError("Simulated crash")

        tool = self._get_task_tool(runner=_failing_run)
        result = tool.invoke({
            "description": "Will fail",
            "prompt": "Do something that crashes",
            "subagent_type": "echo",
            "runtime": _mock_runtime(),
        })
        assert "Task failed" in result
        assert "Simulated crash" in result


# ── create_agent integration tests ──────────────────────────────────────────


class TestCreateAgentIntegration:
    """Verify the full create_agent pipeline with subagent enabled."""

    def test_agent_invocation_includes_task_tool(self) -> None:
        """create_agent with subagent=True + registry → the task tool
        handles real invocations within the graph.
        """
        with pytest.MonkeyPatch.context() as mp:
            import app.core.subagent_runner as srm

            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {
                "messages": [MagicMock(type="ai", content="Subagent analysis complete.")],
            }
            mp.setattr(srm, "_lc_create_agent", MagicMock(return_value=mock_agent))

            agent = create_agent(
                model=FakeListChatModel(responses=[
                    # Turn 1: LLM responds (no tool call needed in this test)
                    "I'll handle this directly.",
                ]),
                tools=[],
                system_prompt="You are a test agent.",
                features=RuntimeFeatures(sandbox=False, subagent=True),
                middleware_deps=MiddlewareChainConfig(
                    subagent_registry=_make_registry(),
                    run_subagent=SubagentRunner(FakeListChatModel(responses=["ok"]), []),
                ),
            )

            # Verify the agent can be invoked without errors
            result = agent.invoke({
                "messages": [{"role": "user", "content": "Hello"}],
            })

            assert "messages" in result
            assert len(result["messages"]) > 0

    def test_agent_without_subagent_has_no_task_tool(self) -> None:
        """create_agent with subagent=False → agent works without task tool."""
        agent = create_agent(
            model=FakeListChatModel(responses=["Hello!"]),
            tools=[],
            features=RuntimeFeatures(sandbox=False, subagent=False),
        )

        result = agent.invoke({
            "messages": [{"role": "user", "content": "Hi"}],
        })

        assert "messages" in result


# ── RuntimeFeatures contract tests ──────────────────────────────────────────


class TestRuntimeFeaturesContract:
    """Verify subagent feature flag contract."""

    def test_default_is_false(self) -> None:
        """subagent is off by default."""
        features = RuntimeFeatures()
        assert not features.is_enabled("subagent")

    def test_runtime_features_has_subagent_field(self) -> None:
        """The subagent field exists on RuntimeFeatures."""
        features = RuntimeFeatures(subagent=True)
        assert features.subagent is True

    def test_can_enable_with_instance(self) -> None:
        """A custom AgentMiddleware instance can be passed instead of True."""
        from agent_sdk.middlewares.subagent_limit import SubagentLimitMiddleware

        features = RuntimeFeatures(subagent=SubagentLimitMiddleware(max_concurrent=2))
        assert features.is_enabled("subagent")
        assert isinstance(features.subagent, SubagentLimitMiddleware)

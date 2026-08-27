"""Unit tests for :mod:`agent_sdk.runtime.middleware_chain`.

Covers the order of the built-in chain, the per-feature
behaviour (sandbox / memory / subagent / vision /
auto_title / summarization), the contract that
:class:`ClarificationMiddleware` is always last, and the
``@Next`` / ``@Prev`` insertion path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agent_sdk.memory.schema import MemorySchema
from agent_sdk.middlewares.clarification import ClarificationMiddleware
from agent_sdk.middlewares.dangling_tool_call import DanglingToolCallMiddleware
from agent_sdk.middlewares.deferred_tool_filter import DeferredToolFilterMiddleware
from agent_sdk.middlewares.llm_error import LLMErrorHandlingMiddleware
from agent_sdk.middlewares.loop_detection import LoopDetectionMiddleware
from agent_sdk.middlewares.subagent_limit import SubagentLimitMiddleware
from agent_sdk.middlewares.summarization import SummarizationMiddleware
from agent_sdk.middlewares.thread_data import ThreadDataMiddleware
from agent_sdk.middlewares.title import TitleMiddleware
from agent_sdk.middlewares.token_usage import TokenUsageMiddleware
from agent_sdk.middlewares.tool_error_handling import ToolErrorHandlingMiddleware
from agent_sdk.middlewares.uploads import UploadsMiddleware
from agent_sdk.middlewares.view_image import ViewImageMiddleware
from agent_sdk.paths.provider import PathProvider
from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import (
    MiddlewareChainConfig,
    _insert_extra_middlewares,
    assemble_chain,
)
from agent_sdk.sandbox.audit import SandboxAuditMiddleware
from agent_sdk.sandbox.base import Sandbox, SandboxProvider
from langchain.agents.middleware import AgentMiddleware

# ---------------------------------------------------------------------------
# Minimal in-memory stand-ins
# ---------------------------------------------------------------------------


class _PathProvider(PathProvider):
    """Deterministic provider that returns fixed paths per thread."""

    def __init__(self, base: Path) -> None:
        self._base = Path(base)

    def get_base_dir(self) -> Path:
        return self._base

    def _for(self, thread_id: str, kind: str, user_id: str | None = None) -> Path:
        return self._base / thread_id / kind

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._for(thread_id, "workspace", user_id)

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._for(thread_id, "uploads", user_id)

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._for(thread_id, "outputs", user_id)

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._for(thread_id, "user-data", user_id)

    def get_skills_dir(self) -> Path:
        return self._base / "skills"

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None) -> Path | None:
        return None

    def get_virtual_prefix(self) -> str:
        return "/mnt/user-data"

    def is_host_bash_allowed(self) -> bool:
        return True


class _Sandbox(Sandbox):
    def __init__(self, sid: str) -> None:
        super().__init__(sid)

    def execute_command(self, command):
        return ""

    def read_file(self, path):
        return ""

    def read_file_bytes(self, path):
        return b""

    def list_dir(self, path, max_depth=2):
        return []

    def write_file(self, path, content, append=False):
        return None

    def glob(self, path, pattern, *, include_dirs=False, max_results=200):
        return [], False

    def grep(self, path, pattern, *, glob=None, literal=False, case_sensitive=False, max_results=100):
        return [], False

    def update_file(self, path, content):
        return None


class _SandboxProvider(SandboxProvider):
    def __init__(self) -> None:
        super().__init__()
        self._counter = 0
        self._store: dict[str, Sandbox] = {}

    def acquire(self, thread_id=None):
        self._counter += 1
        sid = f"sb-{self._counter}"
        self._store[sid] = _Sandbox(sid)
        return sid

    def get(self, sandbox_id):
        return self._store.get(sandbox_id)

    def release(self, sandbox_id):
        self._store.pop(sandbox_id, None)


class _MemorySchema(MemorySchema):
    """Trivial in-memory schema for tests."""

    @classmethod
    def empty(cls):
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _MemorySchema:
        return cls()

    def get_user_profile(self) -> dict[str, Any]:
        return {}

    def get_conversation_history(self) -> list[dict[str, Any]]:
        return []


class _StubModel:
    """Stand-in for a chat model used by summarization middleware."""

    def __init__(self, content: str = "summary") -> None:
        self._content = content

    def invoke(self, prompt):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self._content)

    async def ainvoke(self, prompt):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self._content)


# ---------------------------------------------------------------------------
# Default chain (no optional features enabled)
# ---------------------------------------------------------------------------


class TestDefaultChain:
    def test_default_always_on_chain(self) -> None:
        chain, _ = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())
        names = [type(m).__name__ for m in chain]
        # always-on middlewares present, in order
        assert DanglingToolCallMiddleware.__name__ in names
        assert LLMErrorHandlingMiddleware.__name__ in names
        assert ToolErrorHandlingMiddleware.__name__ in names
        assert TokenUsageMiddleware.__name__ in names
        assert DeferredToolFilterMiddleware.__name__ in names
        assert LoopDetectionMiddleware.__name__ in names
        assert ClarificationMiddleware.__name__ in names

    def test_clarification_is_last_by_default(self) -> None:
        chain, _ = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())
        assert isinstance(chain[-1], ClarificationMiddleware)

    def test_no_extra_tools_by_default(self) -> None:
        _, tools = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())
        # ask_clarification is still added (always-on).
        assert any(t.name == "ask_clarification" for t in tools)

    def test_default_order_dangling_before_tool_error(self) -> None:
        chain, _ = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())
        d_idx = next(i for i, m in enumerate(chain) if isinstance(m, DanglingToolCallMiddleware))
        te_idx = next(i for i, m in enumerate(chain) if isinstance(m, ToolErrorHandlingMiddleware))
        assert d_idx < te_idx

    def test_default_order_token_usage_before_loop(self) -> None:
        chain, _ = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())
        t_idx = next(i for i, m in enumerate(chain) if isinstance(m, TokenUsageMiddleware))
        l_idx = next(i for i, m in enumerate(chain) if isinstance(m, LoopDetectionMiddleware))
        assert t_idx < l_idx


# ---------------------------------------------------------------------------
# Sandbox feature
# ---------------------------------------------------------------------------


class TestSandboxFeature:
    def test_sandbox_true_inserts_three_middlewares(self, tmp_path: Path) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=True),
            MiddlewareChainConfig(
                path_provider=_PathProvider(tmp_path),
                sandbox_provider=_SandboxProvider(),
            ),
        )
        assert any(isinstance(m, ThreadDataMiddleware) for m in chain)
        assert any(isinstance(m, UploadsMiddleware) for m in chain)
        assert any(isinstance(m, SandboxAuditMiddleware) for m in chain)

    def test_sandbox_true_missing_path_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="path_provider"):
            assemble_chain(
                RuntimeFeatures(sandbox=True),
                MiddlewareChainConfig(sandbox_provider=_SandboxProvider()),
            )

    def test_sandbox_true_missing_sandbox_provider_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="sandbox_provider"):
            assemble_chain(
                RuntimeFeatures(sandbox=True),
                MiddlewareChainConfig(path_provider=_PathProvider(tmp_path)),
            )

    def test_sandbox_order_thread_data_uploads_audit(self, tmp_path: Path) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=True),
            MiddlewareChainConfig(
                path_provider=_PathProvider(tmp_path),
                sandbox_provider=_SandboxProvider(),
            ),
        )
        td_idx = next(i for i, m in enumerate(chain) if isinstance(m, ThreadDataMiddleware))
        up_idx = next(i for i, m in enumerate(chain) if isinstance(m, UploadsMiddleware))
        sa_idx = next(i for i, m in enumerate(chain) if isinstance(m, SandboxAuditMiddleware))
        assert td_idx < up_idx < sa_idx

    def test_sandbox_audit_runs_after_tool_error(self, tmp_path: Path) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=True),
            MiddlewareChainConfig(
                path_provider=_PathProvider(tmp_path),
                sandbox_provider=_SandboxProvider(),
            ),
        )
        te_idx = next(i for i, m in enumerate(chain) if isinstance(m, ToolErrorHandlingMiddleware))
        sa_idx = next(i for i, m in enumerate(chain) if isinstance(m, SandboxAuditMiddleware))
        # SandboxAudit runs BEFORE ToolErrorHandling so audit
        # can block before the error-handler swallows the call.
        assert sa_idx < te_idx


# ---------------------------------------------------------------------------
# Other optional features
# ---------------------------------------------------------------------------


class TestSubagentFeature:
    def test_subagent_true_inserts_limit_middleware(self) -> None:
        chain, tools = assemble_chain(
            RuntimeFeatures(subagent=True, sandbox=False),
            MiddlewareChainConfig(),
        )
        assert any(isinstance(m, SubagentLimitMiddleware) for m in chain)
        # The ``task`` tool is auto-registered.
        assert any(t.name == "task" for t in tools)


class TestVisionFeature:
    def test_vision_true_inserts_view_image_middleware(self) -> None:
        chain, tools = assemble_chain(
            RuntimeFeatures(vision=True, sandbox=False),
            MiddlewareChainConfig(),
        )
        assert any(isinstance(m, ViewImageMiddleware) for m in chain)
        assert any(t.name == "view_image" for t in tools)


class TestTitleFeature:
    def test_title_true_inserts_title_middleware(self) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(auto_title=True, sandbox=False),
            MiddlewareChainConfig(),
        )
        assert any(isinstance(m, TitleMiddleware) for m in chain)

    def test_title_accepts_model_factory(self) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(auto_title=True, sandbox=False),
            MiddlewareChainConfig(title_model_factory=lambda: _StubModel()),
        )
        assert any(isinstance(m, TitleMiddleware) for m in chain)


class TestMemoryFeature:
    def test_memory_true_requires_schema_and_storage(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="memory_schema_cls"):
            assemble_chain(
                RuntimeFeatures(memory=True, sandbox=False),
                MiddlewareChainConfig(),
            )

    def test_memory_true_with_schema_and_storage(self, tmp_path: Path) -> None:
        from agent_sdk.memory.storage import FileMemoryStorage

        storage = FileMemoryStorage(
            file_path=tmp_path / "memory.json",
            schema_cls=_MemorySchema,
        )
        chain, _ = assemble_chain(
            RuntimeFeatures(memory=True, sandbox=False),
            MiddlewareChainConfig(
                memory_schema_cls=_MemorySchema,
                memory_storage=storage,
            ),
        )
        # MemoryMiddleware is in the chain.
        from agent_sdk.memory.middleware import MemoryMiddleware

        assert any(isinstance(m, MemoryMiddleware) for m in chain)


class TestSummarizationFeature:
    def test_summarization_true_requires_model(self) -> None:
        with pytest.raises(ValueError, match="summarization_model"):
            assemble_chain(
                RuntimeFeatures(summarization=True, sandbox=False),
                MiddlewareChainConfig(),
            )

    def test_summarization_true_with_model(self) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(summarization=True, sandbox=False),
            MiddlewareChainConfig(summarization_model=_StubModel()),
        )
        assert any(isinstance(m, SummarizationMiddleware) for m in chain)

    def test_summarization_partitioner_is_forwarded(self) -> None:
        from agent_sdk.middlewares.summarization import skill_rescue_partitioner

        partitioner = skill_rescue_partitioner({"read_skill"})
        chain, _ = assemble_chain(
            RuntimeFeatures(summarization=True, sandbox=False),
            MiddlewareChainConfig(
                summarization_model=_StubModel(),
                summarization_partitioner=partitioner,
            ),
        )
        smw = next(m for m in chain if isinstance(m, SummarizationMiddleware))
        # The middleware stored the caller-supplied partitioner.
        assert smw._partitioner is partitioner


# ---------------------------------------------------------------------------
# Skills integration (stage 5.5)
# ---------------------------------------------------------------------------


class TestSkillsFeature:
    def test_skills_true_requires_path(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="skills_path"):
            assemble_chain(
                RuntimeFeatures(skills=True, sandbox=False),
                MiddlewareChainConfig(),
            )

    def test_skills_true_with_path(self, tmp_path) -> None:
        from agent_sdk.skills import SkillsMiddleware

        chain, _ = assemble_chain(
            RuntimeFeatures(skills=True, sandbox=False),
            MiddlewareChainConfig(skills_path=tmp_path),
        )
        assert any(isinstance(m, SkillsMiddleware) for m in chain)

    def test_skills_custom_instance(self) -> None:
        from agent_sdk.skills import SkillsMiddleware
        from langchain.agents.middleware import AgentMiddleware

        custom = SkillsMiddleware(skills_path="/nonexistent", allowed_names=[])
        chain, _ = assemble_chain(
            RuntimeFeatures(skills=custom, sandbox=False),
            MiddlewareChainConfig(),
        )
        # The exact instance is in the chain.
        assert custom in chain
        # And it is an AgentMiddleware.
        assert isinstance(custom, AgentMiddleware)


class TestPlanMode:
    def test_plan_mode_inserts_todo(self) -> None:
        from agent_sdk.middlewares.todo.middleware import TodoMiddleware

        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=False),
            MiddlewareChainConfig(),
            plan_mode=True,
        )
        assert any(isinstance(m, TodoMiddleware) for m in chain)

    def test_plan_mode_clarification_still_last(self) -> None:
        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=False),
            MiddlewareChainConfig(),
            plan_mode=True,
        )
        assert isinstance(chain[-1], ClarificationMiddleware)


# ---------------------------------------------------------------------------
# Clarification-last invariant after extra middleware
# ---------------------------------------------------------------------------


class TestClarificationLast:
    def test_clarification_remains_last_after_unanchored_extras(self) -> None:
        class _Extra(AgentMiddleware):
            pass

        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=False),
            MiddlewareChainConfig(),
            extra_middleware=[_Extra()],
        )
        assert isinstance(chain[-1], ClarificationMiddleware)
        # The unanchored extra is right before Clarification.
        assert isinstance(chain[-2], _Extra)

    def test_clarification_anchored_with_next_is_restored_to_last(self) -> None:
        """@Next(ClarificationMiddleware) should NOT push Clar off the tail."""
        from agent_sdk.runtime.decorators import Next

        @Next(ClarificationMiddleware)
        class _BeforeClar(AgentMiddleware):
            pass

        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=False),
            MiddlewareChainConfig(),
            extra_middleware=[_BeforeClar()],
        )
        # Clarification is still last.
        assert isinstance(chain[-1], ClarificationMiddleware)


# ---------------------------------------------------------------------------
# @Next / @Prev insertion
# ---------------------------------------------------------------------------


class TestExtraInsertion:
    def test_next_anchor_inserts_after_target(self) -> None:
        from agent_sdk.runtime.decorators import Next

        @Next(DanglingToolCallMiddleware)
        class _Extra(AgentMiddleware):
            pass

        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=False),
            MiddlewareChainConfig(),
            extra_middleware=[_Extra()],
        )
        d_idx = next(i for i, m in enumerate(chain) if isinstance(m, DanglingToolCallMiddleware))
        # The extra lands directly after DanglingToolCall.
        assert isinstance(chain[d_idx + 1], _Extra)

    def test_prev_anchor_inserts_before_target(self) -> None:
        from agent_sdk.runtime.decorators import Prev

        @Prev(LoopDetectionMiddleware)
        class _Extra(AgentMiddleware):
            pass

        chain, _ = assemble_chain(
            RuntimeFeatures(sandbox=False),
            MiddlewareChainConfig(),
            extra_middleware=[_Extra()],
        )
        l_idx = next(i for i, m in enumerate(chain) if isinstance(m, LoopDetectionMiddleware))
        assert isinstance(chain[l_idx - 1], _Extra)

    def test_conflict_raises(self) -> None:
        from agent_sdk.runtime.decorators import Next

        @Next(DanglingToolCallMiddleware)
        class _A(AgentMiddleware):
            pass

        @Next(DanglingToolCallMiddleware)
        class _B(AgentMiddleware):
            pass

        with pytest.raises(ValueError, match="both @Next"):
            _insert_extra_middlewares([], [_A(), _B()])

    def test_unresolved_anchor_raises(self) -> None:
        from agent_sdk.runtime.decorators import Next

        @Next(SubagentLimitMiddleware)
        class _Extra(AgentMiddleware):
            pass

        # SubagentLimitMiddleware is not in the chain (subagent=False).
        with pytest.raises(ValueError, match="not found in chain"):
            _insert_extra_middlewares(
                [DanglingToolCallMiddleware()],
                [_Extra()],
            )

    def test_both_anchors_raises(self) -> None:
        from agent_sdk.runtime.decorators import Next, Prev

        @Next(DanglingToolCallMiddleware)
        @Prev(LoopDetectionMiddleware)
        class _Extra(AgentMiddleware):
            pass

        with pytest.raises(ValueError, match="both @Next and @Prev"):
            _insert_extra_middlewares(
                [DanglingToolCallMiddleware(), LoopDetectionMiddleware()],
                [_Extra()],
            )


# ---------------------------------------------------------------------------
# Full chain: every feature on
# ---------------------------------------------------------------------------


class TestFullChain:
    def test_every_feature_on(self, tmp_path: Path) -> None:
        from agent_sdk.memory.storage import FileMemoryStorage

        feat = RuntimeFeatures(
            sandbox=True,
            memory=True,
            subagent=True,
            vision=True,
            auto_title=True,
            summarization=True,
        )
        config = MiddlewareChainConfig(
            path_provider=_PathProvider(tmp_path),
            sandbox_provider=_SandboxProvider(),
            title_model_factory=lambda: _StubModel(),
            summarization_model=_StubModel(),
            memory_schema_cls=_MemorySchema,
            memory_storage=FileMemoryStorage(
                file_path=tmp_path / "memory.json",
                schema_cls=_MemorySchema,
            ),
        )
        chain, tools = assemble_chain(feat, config, plan_mode=True)
        names = {type(m).__name__ for m in chain}

        # Spot-check every enabled feature is present.
        assert "ThreadDataMiddleware" in names
        assert "UploadsMiddleware" in names
        assert "SandboxAuditMiddleware" in names
        assert "DanglingToolCallMiddleware" in names
        assert "LLMErrorHandlingMiddleware" in names
        assert "ToolErrorHandlingMiddleware" in names
        assert "SummarizationMiddleware" in names
        assert "TodoMiddleware" in names
        assert "TokenUsageMiddleware" in names
        assert "TitleMiddleware" in names
        assert "MemoryMiddleware" in names
        assert "ViewImageMiddleware" in names
        assert "DeferredToolFilterMiddleware" in names
        assert "SubagentLimitMiddleware" in names
        assert "LoopDetectionMiddleware" in names
        assert "ClarificationMiddleware" in names

        # Tools auto-registered.
        assert {t.name for t in tools} >= {
            "view_image",
            "task",
            "ask_clarification",
        }

        # Clarification is still last.
        assert isinstance(chain[-1], ClarificationMiddleware)

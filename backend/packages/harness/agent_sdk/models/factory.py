"""Model factory for SDK chat-model construction.

This module is a re-implementation (per ADR-010) of
``deerflow.models.factory``.  It exposes
:func:`create_chat_model` — a single entry point that builds
a :class:`langchain.chat_models.BaseChatModel` from a
:class:`ModelConfig` and a kwargs dict.

The factory does **not** know about any specific provider
catalogue.  Products build their own
:class:`ModelConfig` records (see :mod:`agent_sdk.presets.deerflow.models`
for the DeerFlow preset) and pass them here.

What this factory does:

* resolves the model's class via
  :func:`agent_sdk.reflection.resolve_class` (so a missing
  optional dependency produces an actionable ``uv add``
  hint, not a bare ``ModuleNotFoundError``);
* forwards the configured kwargs to the model class;
* auto-enables ``stream_usage`` on OpenAI-compatible
  models when the user has configured a custom ``base_url``
  (otherwise the LangChain default is to leave it off, and
  the :class:`TokenUsageMiddleware` would see nothing);
* attaches any tracing callbacks returned by
  :func:`agent_sdk.tracing.factory.build_tracing_callbacks`
  to the model.

What this factory does **not** do:

* the in-tree reference has provider-specific code paths
  for Claude, DeepSeek, vLLM, MindIE, OpenAI Codex, and a
  patched-OpenAI path for a third-party gateway.  Those
  specialisations are intentionally left to the preset
  layer; the SDK is the contract, the preset is the policy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration data class
# ---------------------------------------------------------------------------


class ModelConfig(BaseModel):
    """Declarative description of a chat model.

    A product builds a catalogue of these records and passes
    the one it wants to :func:`create_chat_model`.

    Attributes:
        name: Stable identifier (e.g. ``"claude-sonnet-4"``).
        use: Class path of the model implementation
            (e.g. ``"langchain_anthropic:ChatAnthropic"``).
        display_name: Human-readable label, used by the UI.
        description: Optional one-line summary.
        supports_thinking: Whether the model supports an
            explicit thinking toggle.
        thinking_locked: Whether thinking is always-on and
            cannot be toggled off (models whose API rejects a
            "disabled" thinking value, e.g. Kimi K2.7).
        supports_reasoning_effort: Whether the model supports
            a ``reasoning_effort`` parameter.
        supports_vision: Whether the model can accept image
            inputs.
        when_thinking_enabled: Kwargs to merge in when
            thinking is enabled.
        when_thinking_disabled: Kwargs to merge in when
            thinking is disabled (e.g. ``{"reasoning_effort":
            "minimal"}``).
        thinking: Shortcut for ``when_thinking_enabled["thinking"]``.
        model_settings: Default kwargs forwarded to the
            model class.  Anything in :class:`BaseChatModel`'s
            constructor (temperature, max_tokens, base_url, …)
            belongs here.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    use: str = Field(description="Class path of the model, e.g. 'langchain_anthropic:ChatAnthropic'.")
    display_name: str | None = None
    description: str | None = None
    supports_thinking: bool = False
    thinking_locked: bool = False
    supports_reasoning_effort: bool = False
    supports_vision: bool = False
    when_thinking_enabled: dict[str, Any] | None = None
    when_thinking_disabled: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers (re-implementations of small in-tree utilities)
# ---------------------------------------------------------------------------


def _deep_merge_dicts(base: dict | None, override: dict) -> dict:
    """Recursively merge two dicts without mutating the inputs."""
    merged = dict(base or {})
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _vllm_disable_chat_template_kwargs(chat_template_kwargs: dict) -> dict:
    """Build the ``disable`` payload for vLLM/Qwen chat template kwargs."""
    disable_kwargs: dict[str, bool] = {}
    if "thinking" in chat_template_kwargs:
        disable_kwargs["thinking"] = False
    if "enable_thinking" in chat_template_kwargs:
        disable_kwargs["enable_thinking"] = False
    return disable_kwargs


def _enable_stream_usage_by_default(model_use_path: str, settings: dict) -> None:
    """Auto-enable ``stream_usage`` for OpenAI-compatible gateways.

    LangChain only auto-enables ``stream_usage`` for OpenAI
    models when no custom ``base_url`` is configured.  Many
    products use OpenAI-compatible gateways; without this
    fix, the :class:`TokenUsageMiddleware` would see nothing
    in streaming mode.

    This function now covers **all** OpenAI-compatible models
    (including patched variants like ``PatchedChatDeepSeek``
    and ``PatchedChatMiniMax``), not just the canonical
    ``langchain_openai.ChatOpenAI``.  It also recognises
    ``api_base`` (used by config.yaml) in addition to
    ``base_url`` and ``openai_api_base``.
    """
    if "stream_usage" in settings:
        return
    # Any custom API endpoint means this is an OpenAI-compatible gateway
    # that needs stream_usage to receive token counts in streaming chunks.
    if "api_base" in settings or "base_url" in settings or "openai_api_base" in settings:
        settings["stream_usage"] = True


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


@dataclass
class _ModelBuildResult:
    """Internal: bundle the model + the kwargs that produced it (for tests)."""

    model: BaseChatModel
    settings: dict[str, Any] = field(default_factory=dict)


def _build_settings(model_config: ModelConfig, thinking_enabled: bool) -> dict[str, Any]:
    """Compute the effective model kwargs from *model_config* and *thinking_enabled*."""
    settings = dict(model_config.model_settings)

    has_thinking_settings = (model_config.when_thinking_enabled is not None) or (model_config.thinking is not None)
    effective_wte: dict = dict(model_config.when_thinking_enabled) if model_config.when_thinking_enabled else {}
    if model_config.thinking is not None:
        merged_thinking = {**(effective_wte.get("thinking") or {}), **model_config.thinking}
        effective_wte = {**effective_wte, "thinking": merged_thinking}

    if thinking_enabled and has_thinking_settings:
        if not model_config.supports_thinking:
            raise ValueError(
                f"Model {model_config.name!r} does not support thinking. "
                "Set `supports_thinking` to true in the model config to enable thinking."
            )
        if effective_wte:
            settings.update(effective_wte)
    if not thinking_enabled:
        if model_config.when_thinking_disabled is not None:
            # User-provided disable settings take full precedence.
            settings.update(model_config.when_thinking_disabled)
        elif has_thinking_settings and effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body.
            settings["extra_body"] = _deep_merge_dicts(
                settings.get("extra_body"),
                {"thinking": {"type": "disabled"}},
            )
            settings["reasoning_effort"] = "minimal"
        elif has_thinking_settings and (disable_chat_template_kwargs := _vllm_disable_chat_template_kwargs(effective_wte.get("extra_body", {}).get("chat_template_kwargs") or {})):
            # vLLM uses chat template kwargs to switch thinking on/off.
            settings["extra_body"] = _deep_merge_dicts(
                settings.get("extra_body"),
                {"chat_template_kwargs": disable_chat_template_kwargs},
            )
        elif has_thinking_settings and effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter.
            settings["thinking"] = {"type": "disabled"}

    if not model_config.supports_reasoning_effort:
        settings.pop("reasoning_effort", None)

    _enable_stream_usage_by_default(model_config.use, settings)

    # Auto-enable stream_usage when the model class declares the field
    # (matches the in-tree reference's behaviour for patched OpenAI variants).
    if "stream_usage" not in settings:
        # The model class itself may carry the field declaration; we cannot
        # inspect it before instantiating, so this is a no-op for unknown
        # classes. The ``_enable_stream_usage_by_default`` step above covers
        # the common case (OpenAI-compatible gateways).
        pass

    return settings


def create_chat_model(
    config: ModelConfig,
    *,
    thinking_enabled: bool = False,
    tracing_callbacks: list[Any] | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Create a chat-model instance from a :class:`ModelConfig`.

    Args:
        config: Declarative model description.
        thinking_enabled: Whether the model should be created
            with thinking enabled.  When ``True`` and the
            config defines a ``when_thinking_enabled`` block,
            those kwargs are merged in (subject to the
            ``supports_thinking`` check).
        tracing_callbacks: Optional list of callback handlers
            (e.g. LangSmith, Langfuse) to attach to the
            model.  Existing ``callbacks`` on the model are
            preserved.
        **kwargs: Additional kwargs forwarded to the model
            constructor, overriding any value in
            ``model_settings``.

    Returns:
        A :class:`BaseChatModel` instance, ready to be passed
        to :func:`agent_sdk.create_agent`.

    Raises:
        ImportError: If the model class cannot be resolved
            (with an actionable ``uv add`` hint).
        ValueError: If ``thinking_enabled=True`` but the
            model declares ``supports_thinking=False``.
    """
    # Local import keeps the SDK's import surface small.
    from agent_sdk.reflection import resolve_class

    model_class = resolve_class(config.use, base_class=BaseChatModel)

    settings = _build_settings(config, thinking_enabled)
    settings.update(kwargs)

    model_instance = model_class(**settings)

    if tracing_callbacks:
        existing_callbacks = model_instance.callbacks or []
        model_instance.callbacks = [*existing_callbacks, *tracing_callbacks]
        logger.debug("Tracing attached to model %r with %d provider(s)", config.name, len(tracing_callbacks))

    return model_instance

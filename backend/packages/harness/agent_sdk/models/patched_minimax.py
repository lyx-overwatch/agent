"""Patched ChatDeepSeek adapter for MiniMax models.

MiniMax 的 OpenAI-compatible API 与 DeepSeek 有几点差异:

1. **thinking.type**: MiniMax 接受 ``"adaptive"`` / ``"disabled"``，
   不接受 DeepSeek 的 ``"enabled"``。本适配器在 ``_get_request_payload``
   中自动将 ``"enabled"`` → ``"adaptive"``，使得 config.yaml 可以对
   所有模型统一使用 ``"enabled"``。

2. **reasoning_split**: 当 thinking 开启时，发送 ``reasoning_split: true``
   让 MiniMax 以结构化 ``reasoning_details`` 返回推理内容；关闭时不发送，
   避免干扰工具调用的 ID 格式。

3. **<think> 标签**: MiniMax 在 thinking 关闭但未显式设置 ``thinking.type``
   时仍可能在 content 中内联 ``<think>`` 标签，``_create_chat_result``
   会将其剥离并移入 ``additional_kwargs.reasoning_content``。

本类继承 ``ChatDeepSeek`` 而非 ``ChatOpenAI``，以利用 ``api_base``
原生支持和 ``reasoning_content`` 多轮保留能力。

Usage with ModelConfig::

    config = ModelConfig(
        name="minimax-m3",
        use="agent_sdk.models.patched_minimax:PatchedChatMiniMax",
        model_settings={
            "model": "minimax-m3",
            "api_base": "https://your-gateway/v3",
            "api_key": "...",
        },
        supports_thinking=True,
        when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
    )
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# lazy import — langchain_deepseek 是可选依赖
try:
    from langchain_deepseek import ChatDeepSeek
except ImportError as exc:
    raise ImportError(
        "langchain-deepseek is required for PatchedChatMiniMax. "
        "Install it with: uv add langchain-deepseek"
    ) from exc

from langchain_openai.chat_models.base import (
    _convert_delta_to_message_chunk,
    _create_usage_metadata,
)

_THINK_TAG_RE = re.compile(r"<think>\s*(.*?)\s*</think>", re.DOTALL)


# ── Helper functions ──────────────────────────────────────────────────────


def _extract_reasoning_text(
    reasoning_details: Any,
    *,
    strip_parts: bool = True,
) -> str | None:
    """Extract reasoning text from MiniMax ``reasoning_details`` list.

    Each item is a dict like ``{"text": "...", "signature": "..."}``.
    """
    if not isinstance(reasoning_details, list):
        return None

    parts: list[str] = []
    for item in reasoning_details:
        if not isinstance(item, Mapping):
            continue
        text = item.get("text")
        if isinstance(text, str):
            normalized = text.strip() if strip_parts else text
            if normalized.strip():
                parts.append(normalized)

    return "\n\n".join(parts) if parts else None


def _strip_inline_think_tags(content: str) -> tuple[str, str | None]:
    """Strip ``<think>...</think>`` blocks from content."""
    reasoning_parts: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        reasoning = match.group(1).strip()
        if reasoning:
            reasoning_parts.append(reasoning)
        return ""

    cleaned = _THINK_TAG_RE.sub(_replace, content).strip()
    reasoning = "\n\n".join(reasoning_parts) if reasoning_parts else None
    return cleaned, reasoning


def _merge_reasoning(*values: str | None) -> str | None:
    """Merge multiple reasoning strings, deduplicating by content."""
    merged: list[str] = []
    for value in values:
        if not value:
            continue
        normalized = value.strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return "\n\n".join(merged) if merged else None


def _with_reasoning_content(
    message: AIMessage | AIMessageChunk,
    reasoning: str | None,
    *,
    preserve_whitespace: bool = False,
) -> AIMessage | AIMessageChunk:
    """Attach reasoning content to a message's ``additional_kwargs``."""
    if not reasoning:
        return message

    additional_kwargs = dict(message.additional_kwargs)
    if preserve_whitespace:
        existing = additional_kwargs.get("reasoning_content")
        additional_kwargs["reasoning_content"] = f"{existing}{reasoning}" if isinstance(existing, str) else reasoning
    else:
        additional_kwargs["reasoning_content"] = _merge_reasoning(
            additional_kwargs.get("reasoning_content"),
            reasoning,
        )
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


# ── Patched model ─────────────────────────────────────────────────────────


class PatchedChatMiniMax(ChatDeepSeek):
    """ChatDeepSeek adapter for MiniMax's OpenAI-compatible API.

    Differences from the vanilla ``ChatDeepSeek`` path:

    * Translates ``thinking.type`` from ``"enabled"`` to ``"adaptive"``
      (MiniMax doesn't accept ``"enabled"``).
    * Injects ``reasoning_split: true`` when thinking is enabled so
      MiniMax returns structured ``reasoning_details`` in streaming.
    * Strips inline ``<think>...</think>`` tags from non-streaming
      responses and promotes them to
      ``additional_kwargs.reasoning_content``.
    """

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "MINIMAX_API_KEY", "openai_api_key": "MINIMAX_API_KEY"}

    # ── Request ────────────────────────────────────────────────────────────

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Override to add MiniMax-specific request adjustments.

        1. Preserve ``reasoning_content`` across turns (inherited from
           ``ChatDeepSeek._get_request_payload``).
        2. Translate ``thinking.type`` from ``"enabled"`` → ``"adaptive"``
           (MiniMax doesn't support ``"enabled"``).
        3. Inject ``reasoning_split: true`` only when thinking is active
           — sending it unconditionally can cause MiniMax to enter a
           different tool-call code path, leading to intermittent
           ``"tool result's tool id ... not found"`` errors.
        """
        # Step 1: Call ChatDeepSeek._get_request_payload (preserves reasoning_content)
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        extra_body = payload.get("extra_body")
        if not isinstance(extra_body, dict):
            extra_body = {}

        # Step 2: Translate thinking.type enabled → adaptive
        thinking_cfg = extra_body.get("thinking")
        if isinstance(thinking_cfg, dict) and thinking_cfg.get("type") == "enabled":
            thinking_cfg["type"] = "adaptive"

        # Step 3: reasoning_split only when thinking is active
        thinking_type = thinking_cfg.get("type") if isinstance(thinking_cfg, dict) else None
        if thinking_type and thinking_type != "disabled":
            extra_body["reasoning_split"] = True

        if extra_body:
            payload["extra_body"] = extra_body

        return payload

    # ── Response: streaming ───────────────────────────────────────────────

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """Handle MiniMax ``reasoning_details`` in streaming chunks.

        When ``reasoning_split: true`` is set, MiniMax returns reasoning
        in ``delta.reasoning_details`` instead of inline ``<think>`` tags.
        This override extracts that field and maps it to
        ``additional_kwargs.reasoning_content`` — the same shape
        ``ChatDeepSeek`` uses for its own reasoning content.
        """
        if chunk.get("type") == "content.delta":
            return None

        token_usage = chunk.get("usage")
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        usage_metadata = _create_usage_metadata(token_usage, chunk.get("service_tier")) if token_usage else None

        if len(choices) == 0:
            generation_chunk = ChatGenerationChunk(
                message=default_chunk_class(content="", usage_metadata=usage_metadata),
                generation_info=base_generation_info,
            )
            if self.output_version == "v1":
                generation_chunk.message.content = []
                generation_chunk.message.response_metadata["output_version"] = "v1"
            return generation_chunk

        choice = choices[0]
        delta = choice.get("delta")
        if delta is None:
            return None

        message_chunk = _convert_delta_to_message_chunk(delta, default_chunk_class)
        generation_info = {**base_generation_info} if base_generation_info else {}

        if finish_reason := choice.get("finish_reason"):
            generation_info["finish_reason"] = finish_reason
            if model_name := chunk.get("model"):
                generation_info["model_name"] = model_name
            if system_fingerprint := chunk.get("system_fingerprint"):
                generation_info["system_fingerprint"] = system_fingerprint
            if service_tier := chunk.get("service_tier"):
                generation_info["service_tier"] = service_tier

        logprobs = choice.get("logprobs")
        if logprobs:
            generation_info["logprobs"] = logprobs

        reasoning = _extract_reasoning_text(
            delta.get("reasoning_details"),
            strip_parts=False,
        )
        if isinstance(message_chunk, AIMessageChunk):
            if usage_metadata:
                message_chunk.usage_metadata = usage_metadata
            if reasoning:
                message_chunk = _with_reasoning_content(
                    message_chunk,
                    reasoning,
                    preserve_whitespace=True,
                )

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(
            message=message_chunk,
            generation_info=generation_info or None,
        )

    # ── Response: non-streaming ────────────────────────────────────────────

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        """Override to strip inline ``<think>`` tags from MiniMax responses.

        MiniMax may return ``<think>...</think>`` blocks inline in the
        ``content`` field (especially when ``reasoning_split`` is off or
        when ``thinking.type`` is not explicitly set).  This method strips
        those tags and merges the extracted reasoning with any
        structured ``reasoning_content`` that ``ChatDeepSeek`` may have
        already extracted.
        """
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        generations: list[ChatGeneration] = []
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            message = generation.message
            if not isinstance(message, AIMessage):
                generations.append(generation)
                continue

            content = message.content
            if not isinstance(content, str) or not content.strip():
                generations.append(generation)
                continue

            # Strip <think> tags from content
            cleaned_content, inline_reasoning = _strip_inline_think_tags(content)

            # Also check for structured reasoning_details in the API response
            choice_message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
            split_reasoning = _extract_reasoning_text(choice_message.get("reasoning_details"))

            # Merge with any reasoning already extracted by ChatDeepSeek parent
            existing = message.additional_kwargs.get("reasoning_content")
            merged_reasoning = _merge_reasoning(existing, split_reasoning, inline_reasoning)

            updated_message = message
            if cleaned_content != content:
                updated_message = updated_message.model_copy(update={"content": cleaned_content})
            if merged_reasoning:
                updated_message = _with_reasoning_content(updated_message, merged_reasoning)

            generation = ChatGeneration(
                message=updated_message,
                generation_info=generation.generation_info,
            )
            generations.append(generation)

        return ChatResult(generations=generations, llm_output=result.llm_output)

"""Patched ChatDeepSeek — 在 thinking 模式下保留多轮对话的 reasoning_content。

移植自 deerflow_origin 的 ``deerflow.models.patched_deepseek``。

当启用 thinking 模式时，DeepSeek API 要求**所有** assistant 消息都携带
reasoning_content。原版 ``ChatDeepSeek`` 将 reasoning_content 存放在
additional_kwargs 中，但发送后续请求时不会回传，导致 API 报错。
本补丁通过重写 ``_get_request_payload`` 修复了这个问题。

依赖: ``langchain-deepseek`` (可选，仅在使用 DeepSeek 模型时需要)
安装: ``uv add langchain-deepseek``

Usage with ModelConfig::

    from agent_sdk.models.factory import ModelConfig, create_chat_model

    config = ModelConfig(
        name="deepseek-v4",
        use="agent_sdk.models.patched_deepseek:PatchedChatDeepSeek",
        model_settings={
            "model": "deepseek-v4-flash-202605",
            "api_base": "https://your-gateway/v3",
            "api_key": "...",
        },
        supports_thinking=True,
        when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
    )
    model = create_chat_model(config)
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage

# lazy import — langchain_deepseek 是可选依赖
try:
    from langchain_deepseek import ChatDeepSeek
except ImportError as exc:
    raise ImportError(
        "langchain-deepseek is required for PatchedChatDeepSeek. "
        "Install it with: uv add langchain-deepseek"
    ) from exc


class PatchedChatDeepSeek(ChatDeepSeek):
    """ChatDeepSeek with proper reasoning_content preservation.

    When using thinking/reasoning enabled models, the API expects
    reasoning_content to be present on ALL assistant messages in
    multi-turn conversations. This patched version ensures
    reasoning_content from additional_kwargs is included in the
    request payload.
    """

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "DEEPSEEK_API_KEY", "openai_api_key": "DEEPSEEK_API_KEY"}

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Get request payload with reasoning_content preserved.

        Overrides the parent method to inject reasoning_content from
        additional_kwargs into assistant messages in the payload.
        """
        # Get the original messages before conversion
        original_messages = self._convert_input(input_).to_messages()

        # Call parent to get the base payload
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        # Match payload messages with original messages to restore reasoning_content
        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    reasoning_content = orig_msg.additional_kwargs.get("reasoning_content")
                    if reasoning_content is not None:
                        payload_msg["reasoning_content"] = reasoning_content
        else:
            # Fallback: match by counting assistant messages
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [(i, m) for i, m in enumerate(payload_messages) if m.get("role") == "assistant"]

            for (idx, payload_msg), ai_msg in zip(assistant_payloads, ai_messages):
                reasoning_content = ai_msg.additional_kwargs.get("reasoning_content")
                if reasoning_content is not None:
                    payload_messages[idx]["reasoning_content"] = reasoning_content

        return payload
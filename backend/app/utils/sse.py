"""SSE event formatting."""

import json
from typing import Any


def get_sse_event(
    message_id: str,
    event_type: str,
    delta: Any,
    finish_reason: str | None = None,
    created: int = 0,
    model: str = "",
) -> str:
    """Format an OpenAI-compatible SSE frame.

    Produces: ``data: {"id":"<message_uuid>","object":"agent.event","created":...,"model":"...","type":"...","choices":[{"index":0,"delta":{...},"finish_reason":null}]}\\n\\n``

    All chunks of the same assistant response share the same ``message_id``
    (the pre-generated ``Message.id``).  This matches OpenAI's chat completion
    chunk format so any OpenAI-compatible SSE client can consume the stream.
    """
    payload = json.dumps(
        {
            "id": message_id,
            "object": "agent.event",
            "created": created,
            "model": model,
            "type": event_type,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        },
        ensure_ascii=False,
    )
    return f"data: {payload}\n\n"

"""Cache warm-up utilities for pre-heating model inference caches."""

import uuid

from langchain_core.messages import HumanMessage
from loguru import logger

from app.core.agent import get_agent
from app.core.config_loader import get_agent_config
from app.utils.chat import make_config

#: Prefix for the synthetic thread_id used by warm-up requests.  A fresh
#: unique suffix is appended per warm-up so that a failed warm-up (e.g. a
#: schema error) never leaks its error message into the next warm-up via the
#: checkpointer.  The DeepSeek disk cache is keyed on the system prompt + tool
#: prefix — not the thread_id — so a unique id still primes the cache correctly.
_WARM_THREAD_PREFIX = "__cache_warm__"


async def warm_cache() -> None:
    """Send a minimal agent invocation to pre-heat the DeepSeek disk KV cache.

    DeepSeek's automatic disk-based KV cache requires one full-price cold-start
    request before subsequent requests can benefit from ~99 % cache hit rates.
    This warm-up absorbs that cost at startup so the first real user request
    already gets a cache hit.

    **Only DeepSeek models are warmed.**  MiniMax / Kimi and other backends
    don't implement the same disk-cache mechanism; warming them is a wasted
    API call and adds startup latency.
    """
    cfg = get_agent_config()
    for model_config in cfg.model_configs:
        model_name = model_config.name
        # Only DeepSeek models benefit from disk-cache warm-up.  Other
        # backends (MiniMax, Kimi, …) don't have the same cache layer.
        model_id = model_config.model_settings.get("model", "")
        if not isinstance(model_id, str) or not model_id.lower().startswith("deepseek"):
            logger.info("Skipping cache warm-up for {} (not a DeepSeek model)", model_name)
            continue

        try:
            agent = get_agent(thinking_enabled=False, model_name=model_name)
            config = make_config(f"{_WARM_THREAD_PREFIX}-{uuid.uuid4().hex[:12]}")
            logger.info("Cache warm-up starting for {} (model={})...", model_name, model_id)
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content="ping")]},
                config=config,
            )
            msgs = result.get("messages", [])
            last = msgs[-1] if msgs else None
            last_content = getattr(last, "content", "") if last else ""
            if isinstance(last_content, str) and last_content.startswith("LLM request failed:"):
                logger.warning("Cache warm-up for {} returned error: {}", model_name, last_content[:100])
            else:
                logger.info("Cache warm-up complete for {} (result={})", model_name, last_content[:80])
        except Exception:
            logger.warning("Cache warm-up failed for {} (non-fatal)", model_name)

"""后台异步标题生成 —— 与 agent 执行隔离。

TitleMiddleware 原先在 agent 回合内同步调用标题模型，那次非流式
``ainvoke`` 会阻塞回合结束（网关延迟波动时可达 80s+）。现在标题改为
后台异步生成：回合结束只取决于回答是否完成，AI 标题随后写入数据库，
前端通过 ``GET /conversations`` 轮询同步进度。

本模块只负责「用标题模型把用户首条消息变成干净短标题」，纯函数化、
best-effort —— 任何失败都静默降级为已有的截断占位标题。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger

# 标题模型输出里的 <thinking>…</thinking> 思考残留（DeepSeek 系列常见）
_THINK_TAGS_RE = re.compile(r"<thinking>[\s\S]*?</thinking>", flags=re.IGNORECASE)

_PROMPT_TEMPLATE = "Generate a short title (max {max_words} words) for a conversation based on the user's first message. Output ONLY the title — no quotes, no preamble.\n\nUser: {user_msg}"


def _normalize(content: Any) -> str:
    """把 LangChain 消息内容（str / list / dict 嵌套）拍平成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p for p in (_normalize(c) for c in content) if p)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        nested = content.get("content")
        if nested is not None:
            return _normalize(nested)
    return ""


def parse_title(content: Any, max_chars: int) -> str | None:
    """把标题模型的原始输出解析成干净短标题。"""
    text = _THINK_TAGS_RE.sub("", _normalize(content)).strip()
    # 去掉模型偶尔包裹的引号
    text = text.strip("\"'").strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


async def generate_title(
    user_message: str,
    model: Any,
    *,
    max_words: int = 6,
    max_chars: int = 60,
) -> str | None:
    """用标题模型从用户首条消息生成短标题（best-effort）。

    Args:
        user_message: 用户首条消息（用于 prompt）。
        model: 标题模型实例（``AgentConfig.create_title_model()`` 返回）。
        max_words: 软性词数目标。
        max_chars: 硬性长度上限（截断）。

    Returns:
        生成的标题；任何失败返回 None（调用方保持占位标题）。
    """
    prompt = _PROMPT_TEMPLATE.format(max_words=max_words, user_msg=user_message[:500])
    try:
        # 标题模型可能偶发极慢（网关冷启动），设个宽裕超时兜底，
        # 超时即放弃、保留占位标题 —— 别让 title_pending 永远挂起。
        response = await asyncio.wait_for(model.ainvoke(prompt), timeout=180.0)
    except Exception:
        logger.opt(exception=True).warning("标题模型调用失败，保留占位标题")
        return None
    return parse_title(response.content, max_chars)

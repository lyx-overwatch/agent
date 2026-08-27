"""Generic web search tool backed by the CUE (感易) gateway.

Proxies Volcengine Ark 融合信息搜索 (豆包搜索) through the CUE LLM gateway.

Requires WEB_SEARCH_API_KEY environment variable.
"""

import os

import requests
from langchain_core.tools import tool

# CUE gateway web search endpoint (豆包搜索).
# SearchType:
#   "web"         → structured results (volcengine-web-search-custom)
#   "web_summary" → summarized answer (volcengine-web-search-summary, 需付费配额)
WEB_SEARCH_ENDPOINT = "https://cuecue.cn/llm-api/v1/web_search"
WEB_SEARCH_TYPE = "web"

# 每条结果 snippet 的最大长度，避免超长内容撑爆上下文。
_MAX_SNIPPET_CHARS = 800

# Map exception type names to user-friendly messages — avoids leaking
# hostnames, IPs, and connection internals into tool output.
_ERROR_FRIENDLY_MAP: dict[str, str] = {
    "ConnectTimeout": "连接超时，目标服务器无响应",
    "ConnectTimeoutError": "连接超时，目标服务器无响应",
    "ReadTimeout": "读取超时，服务器响应过慢",
    "ReadTimeoutError": "读取超时，服务器响应过慢",
    "ConnectionError": "网络连接失败",
    "ConnectionRefusedError": "连接被拒绝",
    "SSLError": "SSL/TLS 证书验证失败",
    "ProxyError": "代理连接失败",
    "TooManyRedirects": "重定向次数过多",
    "HTTPError": "HTTP 错误",
    "RequestException": "网络请求异常",
}


def _truncate(text: str, limit: int = _MAX_SNIPPET_CHARS) -> str:
    """截断过长文本，避免单条结果占用过多上下文。"""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


@tool("web_search")
def web_search(query: str, count: int = 5) -> str:
    """Search the web for up-to-date information using Doubao (豆包) web search.

    Use this tool to look up current events, real-time facts, news, or any
    information that may have changed after the model's training data.

    Args:
        query: The search query (in Chinese or English).
        count: Number of results to return (default 5).

    Returns:
        Search results with titles, URLs, and snippets.
    """
    api_key = os.getenv("WEB_SEARCH_API_KEY")
    if not api_key:
        return "WEB_SEARCH_API_KEY environment variable is not set. Please set it to enable web search."

    payload = {
        "Query": query,
        "SearchType": WEB_SEARCH_TYPE,
        "Count": max(1, min(count, 20)),
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(WEB_SEARCH_ENDPOINT, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        # Return a user-friendly error message without internal details
        # (hostnames, IPs, port numbers, etc.) that would leak infrastructure info.
        _err_type = type(e).__name__
        _friendly = _ERROR_FRIENDLY_MAP.get(_err_type, f"请求失败 ({_err_type})")
        return f"Web search failed: {_friendly}"

    try:
        data = response.json()
    except Exception:
        return "Web search failed: failed to parse response as JSON"

    # 网关在配额耗尽等场景返回 Result=null，错误放在 ResponseMetadata.Error 里。
    result = data.get("Result")
    if not result:
        err = (data.get("ResponseMetadata") or {}).get("Error") or {}
        message = err.get("Message") or "empty result"
        return f"Web search failed: {message}"

    web_results = result.get("WebResults") or []
    if not web_results:
        return "No search results found."

    lines = []
    for i, item in enumerate(web_results, 1):
        title = item.get("Title", "")
        content = item.get("Snippet") or item.get("Summary") or item.get("Content", "")
        link = item.get("Url", "")
        publish_time = item.get("PublishTime", "")

        snippet = f"[{i}] {title}\n"
        if publish_time:
            snippet += f"Date: {publish_time}\n"
        if content:
            snippet += f"{_truncate(content)}\n"
        if link:
            snippet += f"Link: {link}\n"
        lines.append(snippet)

    return "\n".join(lines)

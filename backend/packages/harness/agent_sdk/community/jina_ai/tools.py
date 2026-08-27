"""Jina AI web fetch tool.

Fetches web page content and returns clean markdown via Jina Reader API.
Requires JINA_API_KEY environment variable (optional but recommended for higher rate limits).
"""

import os

import requests
from langchain_core.tools import tool

JINA_READER_ENDPOINT = "https://r.jina.ai/"

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


@tool("web_fetch")
def web_fetch_tool(url: str) -> str:
    """Fetch and extract the content of a web page as clean markdown.

    Use this tool to read the full content of a specific URL. Only fetch URLs
    that have been provided directly by the user or returned in search results.

    Args:
        url: The URL to fetch (must include https:// or http://).

    Returns:
        The page content as markdown text.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Return-Format": "markdown",
        "X-Timeout": "15",
    }

    api_key = os.getenv("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(
            JINA_READER_ENDPOINT,
            headers=headers,
            json={"url": url},
            timeout=20,
        )
        response.raise_for_status()

        # Explicitly set UTF-8 encoding to avoid latin-1 fallback which
        # causes UnicodeEncodeError when Chinese/emoji/etc. content is
        # later serialized through the LangGraph pipeline.
        if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "latin-1"):
            response.encoding = "utf-8"

        text = response.text
    except Exception as e:
        # Return a user-friendly error message without internal details
        # (hostnames, IPs, port numbers, etc.) that would leak infrastructure info.
        _err_type = type(e).__name__
        _friendly = _ERROR_FRIENDLY_MAP.get(_err_type, f"请求失败 ({_err_type})")
        return f"Web fetch failed: {_friendly}"

    if not text or not text.strip():
        return "Web fetch returned empty content."

    # Truncate very long pages to avoid context overflow
    return text[:8000]

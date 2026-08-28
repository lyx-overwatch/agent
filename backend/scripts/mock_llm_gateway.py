"""Mock LLM 网关 —— 用来在本地复现「LLM 连接失败 / provider busy → 重试」场景。

配合 ``backend/config.yaml`` 里把某个模型的 ``api_base`` 指向本服务，即可
在不依赖真实网关的情况下，验证 :class:`LLMErrorHandlingMiddleware` 的重试与
``llm_retry`` 事件透传（前端状态条显示「正在重试… (x/3)」）。

用法::

    # 默认：前 2 次 POST 返回 503，之后返回一段 SSE 流（演示「重试后恢复」）
    uv run python scripts/mock_llm_gateway.py

    # 一直返回 503（演示「重试耗尽」）：把 fail-count 调大即可
    uv run python scripts/mock_llm_gateway.py --fail-count 9999

    # 自定义端口 / 失败状态码
    uv run python scripts/mock_llm_gateway.py --port 9933 --status 500

然后把 ``config.yaml`` 的模型 ``api_base`` 改成 ``http://127.0.0.1:9933/v3``，
重启后端、发消息。前端状态条应出现「正在重试… (1/3) → (2/3)」，重试耗尽后收到
中文兜底文案；后端日志出现 ``Transient LLM error on attempt X/3; retrying in Yms``。

说明：

* 失败响应是 503 + ``server busy`` 文案，同时命中 ``_RETRIABLE_STATUS_CODES``
  与 ``_BUSY_PATTERNS``，会走 transient/busy 重试分支。
* 成功响应是最小化的 OpenAI 兼容 SSE 流（``chat.completion.chunk``），用于演示
  恢复；内容仅为占位，不必与真实模型格式完全一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 全局请求计数（跨连接共享，模拟「先故障 N 次再恢复」的网关）
_REQUEST_COUNT = 0

_SUCCESS_TEXT = "这是 mock 网关返回的回复。"


class MockLLMGatewayHandler(BaseHTTPRequestHandler):
    """处理 OpenAI 兼容的 ``/v3/chat/completions`` 请求。"""

    # 由 serve 时注入，避免用全局可变状态跨线程裸改
    fail_count = 2
    fail_status = 503

    def _count_and_decide(self) -> bool:
        """返回 True 表示本次应失败（在 fail_count 阈值内）。"""
        global _REQUEST_COUNT
        _REQUEST_COUNT += 1
        return _REQUEST_COUNT <= self.fail_count

    def _reply_failure(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "message": "server busy, please retry later",
                    "type": "service_unavailable",
                    "code": "service_unavailable",
                }
            }
        ).encode()
        self.send_response(self.fail_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_success_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _chunk(delta: dict, finish_reason: str | None) -> str:
            return json.dumps(
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "mock",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                },
                ensure_ascii=False,
            )

        for char in _SUCCESS_TEXT:
            self.wfile.write(f"data: {_chunk({'content': char}, None)}\n\n".encode())
        self.wfile.write(f"data: {_chunk({}, 'stop')}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        # 写完 [DONE] 主动关闭连接：客户端读到 [DONE] 即结束，同时让 curl 之类的
        # 手动测试不会因 keep-alive 挂住等数据。
        self.close_connection = True

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self._count_and_decide():
                self._reply_failure()
            else:
                self._reply_success_sse()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        # 客户端偶尔会 probe；返回一个空 JSON 即可
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        # 默认会往 stderr 打每条请求，太吵；这里只打印精简一行
        sys.stderr.write(f"[mock-gateway] {self.command} {self.path} -> {self._last_status}\n")

    def send_response(self, code: int, message: str | None = None) -> None:
        self._last_status = code
        super().send_response(code, message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock LLM gateway for retry testing")
    parser.add_argument("--port", type=int, default=9933, help="监听端口（默认 9933）")
    parser.add_argument("--fail-count", type=int, default=2, help="前 N 次 POST 返回失败（默认 2）")
    parser.add_argument("--status", type=int, default=503, help="失败状态码（默认 503）")
    args = parser.parse_args()

    MockLLMGatewayHandler.fail_count = args.fail_count
    MockLLMGatewayHandler.fail_status = args.status

    server = ThreadingHTTPServer(("127.0.0.1", args.port), MockLLMGatewayHandler)
    print(f"mock-llm-gateway listening on http://127.0.0.1:{args.port}")
    print(f"  fail first {args.fail_count} POST request(s) with HTTP {args.status}, then SSE")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

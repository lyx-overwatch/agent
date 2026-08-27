"""SkillHub 启动入口。

用法:
    uv run python run.py                    # 默认 0.0.0.0:8001
    uv run python run.py --reload           # 开发模式热重载
    uv run python run.py --port 9000        # 自定义端口

Windows + Postgres checkpointer 需要 SelectorEventLoop:
    run.py 已在 import uvicorn 之前设置，切换 type: postgres 后即可使用。
"""

import argparse
import asyncio
import sys

if sys.platform == "win32":
    # Windows 上 psycopg async 需要 SelectorEventLoop 而非默认的 ProactorEventLoop。
    # 必须在 import uvicorn 之前设置，否则 uvicorn 会用 ProactorEventLoop 创建事件循环。
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SkillHub server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8001, help="Bind port (default: 8001)")
    parser.add_argument("--reload", action="store_true", help="Enable hot-reload")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_includes=["*.yaml", "*.yml"] if args.reload else None,
    )
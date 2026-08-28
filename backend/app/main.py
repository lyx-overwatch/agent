"""Heyu Agent FastAPI application — powered by agent-sdk.

The agent runtime is assembled at startup via :func:`agent_sdk.create_agent`
with a local subprocess sandbox and on-disk skill loading.
"""

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager

# LangGraph 严格序列化开关：必须在 import 任何 langgraph.checkpoint 模块之前设置，
# 否则 JsonPlusSerializer 的类属性已在宽松模式下实例化、此开关将不生效。
# 用 setdefault 允许部署环境通过 LANGGRAPH_STRICT_MSGPACK=false 显式关闭。
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from agent_sdk.runtime.checkpointer import make_checkpointer
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text

from app.core.agent import init_agent, shutdown_agent
from app.core.checkpoint_cleanup import run_cleanup_loop
from app.core.config import settings
from app.core.config_loader import get_agent_config
from app.models.database import engine
from app.routes import register_routers
from app.utils import setup_logging, warm_cache

setup_logging(environment=settings.environment, debug=settings.debug)

# ── Windows: psycopg async requires SelectorEventLoop (not Proactor) ──────
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create checkpointer (if configured), init agent, warm cache
    cfg = get_agent_config()
    if cfg.checkpointer_cfg.type == "memory":
        # InMemorySaver — no async context manager needed
        app.state.checkpointer = None
        await init_agent()
        await warm_cache()
        try:
            yield
        except asyncio.CancelledError:
            logger.info("Server stopped via Ctrl+C.")
        finally:
            shutdown_agent()
    else:
        async with make_checkpointer(cfg.checkpointer_cfg) as checkpointer:
            app.state.checkpointer = checkpointer
            await init_agent(checkpointer=checkpointer)
            await warm_cache()

            # ── Checkpointer 表清理（仅 postgres 后端）──────────────────
            # checkpoint 表无内置 TTL，随每次节点切换持续增长；后台任务按
            # keep_latest 语义周期性删除超过保留期的中间快照，但每个 thread
            # 保留最新一条，续聊上下文不丢失。
            cleanup_task: asyncio.Task | None = None
            cleanup_stop: asyncio.Event | None = None
            if settings.checkpoint_cleanup_enabled and cfg.checkpointer_cfg.type == "postgres":
                cleanup_stop = asyncio.Event()
                cleanup_task = asyncio.create_task(
                    run_cleanup_loop(
                        ttl_days=settings.checkpoint_cleanup_ttl_days,
                        interval_seconds=settings.checkpoint_cleanup_interval_seconds,
                        stop_event=cleanup_stop,
                    )
                )

            try:
                yield
            except asyncio.CancelledError:
                logger.info("Server stopped via Ctrl+C.")
            finally:
                if cleanup_stop is not None:
                    cleanup_stop.set()
                if cleanup_task is not None:
                    cleanup_task.cancel()
                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass
                shutdown_agent()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app = register_routers(app)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    with logger.contextualize(request_id=request_id):
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _run_health_checks(checkpointer) -> dict[str, bool]:
    """探活主业务库与 LangGraph checkpointer，返回各项健康状态。

    K8s liveness/readiness 探针据此判断实例是否还能正常服务请求：
    数据库或 checkpointer 任一不可用即视为不健康（返回 503）。
    """
    checks: dict[str, bool] = {}

    # 1. 主业务库（runs/messages/users 表）—— SQLAlchemy async engine
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        logger.warning("Health check failed: database")
        checks["database"] = False

    # 2. LangGraph checkpointer —— 固定 thread_id 做只读读取，不写入任何数据。
    #    连接失效会在 checkout 时被池的 check=check_connection 探活兜住，
    #    这里验证整条 checkpoint 读写链路（池 → 连接 → 表）都可用。
    if checkpointer is not None:
        try:
            await checkpointer.aget({"configurable": {"thread_id": "__health_probe__"}})
            checks["checkpointer"] = True
        except Exception:
            logger.warning("Health check failed: checkpointer")
            checks["checkpointer"] = False

    return checks


@app.get("/health")
async def health(request: Request):
    """K8s liveness/readiness probe — 根路径，不进 /py/api 路由。

    真实探活数据库与 checkpointer，任一不可用返回 503 以便 K8s 踢掉坏实例。
    """
    checks = await _run_health_checks(request.app.state.checkpointer)
    if all(checks.values()):
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "degraded", "checks": checks})


@app.get("/py/api/health")
async def api_health(request: Request):
    """前端健康检查 — 跟其他 API 一样走 /py/api 前缀，线上 Ingress 可路由到后端。"""
    checks = await _run_health_checks(request.app.state.checkpointer)
    if all(checks.values()):
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "degraded", "checks": checks})

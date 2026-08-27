from fastapi import FastAPI

from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.conversations import router as conversations_router
from app.routes.models import router as models_router
from app.routes.skills import router as skills_router
from app.routes.storage import router as storage_router


def register_routers(app: FastAPI):
    """注册所有路由"""
    app.include_router(auth_router, prefix="/py/api")
    app.include_router(chat_router, prefix="/py/api")
    app.include_router(conversations_router, prefix="/py/api")
    app.include_router(models_router, prefix="/py/api")
    app.include_router(skills_router, prefix="/py/api")
    app.include_router(storage_router, prefix="/py/api")
    return app

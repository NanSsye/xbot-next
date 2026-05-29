from __future__ import annotations

from fastapi import FastAPI

from xbot.api.v1.router import router as api_v1_router
from xbot.app.lifespan import lifespan


def create_app() -> FastAPI:
    app = FastAPI(title="xbot backend", version="0.1.0", lifespan=lifespan)
    app.include_router(api_v1_router, prefix="/api/v1")
    return app


app = create_app()


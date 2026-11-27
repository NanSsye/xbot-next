from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from xbot.api.v1.router import router as api_v1_router
from xbot.app.lifespan import lifespan
from xbot.app.security import ApiTokenAuthMiddleware
from xbot.core.config import load_settings


class ConversationMedia(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response


def mount_media(app: FastAPI, root: Path) -> None:
    directories = {'/files/wechat_outbox': 'files/wechat_outbox'}
    for channel in ('wechat869', 'wechat_ilink', 'qq', 'telegram'):
        directories[f'/media/{channel}/media'] = f'data/{channel}/media'
    for url, relative in directories.items():
        directory = root / relative
        if directory.resolve() != root.resolve() / relative:
            raise ValueError(f'Unexpected media directory symlink: {relative}')
        directory.mkdir(parents=True, exist_ok=True)
        app.mount(url, ConversationMedia(directory=directory), name=url.strip('/').replace('/', '-'))


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="xbot backend", version="0.1.0", lifespan=lifespan)
    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(ApiTokenAuthMiddleware, settings=settings)
    app.include_router(api_v1_router, prefix="/api/v1")
    project_root = Path(__file__).resolve().parents[3]
    mount_media(app, project_root)
    ui_dist = project_root / "ui" / "dist"
    if ui_dist.exists():
        app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="ui")
    return app


app = create_app()

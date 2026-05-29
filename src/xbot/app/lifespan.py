from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from xbot.core.config import load_settings
from xbot.core.logging import configure_logging, logger
from xbot.runtime.context import build_context
from xbot.storage.bootstrap import ensure_storage_ready


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    configure_logging(settings.xbot.debug)
    await ensure_storage_ready(settings)
    context = build_context(settings)
    app.state.context = context
    logger.info("Starting xbot-next backend")
    await context.engine.start()
    try:
        yield
    finally:
        logger.info("Stopping xbot-next backend")
        await context.engine.stop()
        await context.storage.close()

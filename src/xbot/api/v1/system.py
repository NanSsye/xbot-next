from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from xbot.app.deps import get_context
from xbot.messaging.redis_queue import RedisMessageQueue
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get('/readiness')
async def readiness(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    digest = request.app.state.release_digest
    ready = False
    if digest and ctx.engine.is_serving():
        try:
            async with asyncio.timeout(3):
                async with ctx.storage.engine.connect() as connection:
                    database_ok = (await connection.scalar(text('SELECT 1'))) == 1
                queue = ctx.message_queue
                ready = database_ok and (not isinstance(queue, RedisMessageQueue) or await queue.ping())
        except (TimeoutError, SQLAlchemyError, RedisError, OSError):
            ready = False
    return JSONResponse({'ready': ready, 'release': digest}, status_code=200 if ready else 503,
                        headers={'Cache-Control': 'no-store'})


@router.get("/status")
async def system_status(ctx: AppContext = Depends(get_context)) -> dict:
    return {
        "success": True,
        "data": {
            "name": ctx.settings.xbot.name,
            "debug": ctx.settings.xbot.debug,
            "storage": ctx.settings.storage.type,
            "engine": ctx.engine.status().model_dump(),
        },
    }


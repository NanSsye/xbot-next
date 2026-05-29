from __future__ import annotations

from fastapi import APIRouter, Depends

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("/status")
async def bot_status(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.engine.status().model_dump()}


@router.post("/start")
async def bot_start(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.engine.start()
    return {"success": True, "data": ctx.engine.status().model_dump()}


@router.post("/stop")
async def bot_stop(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.engine.stop()
    return {"success": True, "data": ctx.engine.status().model_dump()}


@router.post("/restart")
async def bot_restart(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.engine.restart()
    return {"success": True, "data": ctx.engine.status().model_dump()}


from __future__ import annotations

from fastapi import APIRouter, Depends

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


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


from __future__ import annotations

from fastapi import APIRouter, Depends

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("")
async def get_config(ctx: AppContext = Depends(get_context)) -> dict:
    data = ctx.settings.model_dump(mode="json", exclude={"config_file"})
    return {"success": True, "data": data}


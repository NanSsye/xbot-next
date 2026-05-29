from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("")
async def list_adapters(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.adapters.list_adapters()}


@router.post("/{name}/enable")
async def enable_adapter(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    if name not in {item["name"] for item in ctx.adapters.list_adapters()}:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": True}}


@router.post("/{name}/disable")
async def disable_adapter(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    if name not in {item["name"] for item in ctx.adapters.list_adapters()}:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": False}}


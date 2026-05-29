from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("")
async def list_skills(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.skills.list_skills()}


@router.post("/reload")
async def reload_skills(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.skills.load_all()
    return {"success": True, "data": ctx.skills.list_skills()}


@router.post("/{name}/enable")
async def enable_skill(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    enabled = await ctx.skills.enable(name)
    if not enabled:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": True}}


@router.post("/{name}/disable")
async def disable_skill(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    disabled = await ctx.skills.disable(name)
    if not disabled:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": False}}

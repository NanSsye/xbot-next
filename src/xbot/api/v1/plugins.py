from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("")
async def list_plugins(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.plugins.list_plugins()}


@router.get("/agent-tools")
async def list_plugin_agent_tools(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.plugins.list_agent_tools()}


@router.post("/reload")
async def reload_plugins(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.plugins.load_all()
    return {"success": True, "data": ctx.plugins.list_plugins()}


@router.get("/{name}/agent-tools")
async def list_one_plugin_agent_tools(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    tools = ctx.plugins.list_agent_tools(name)
    if not tools and name not in {item["name"] for item in ctx.plugins.list_plugins()}:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    return {"success": True, "data": tools}


@router.post("/{name}/enable")
async def enable_plugin(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    enabled = await ctx.plugins.enable(name)
    if not enabled:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": True}}


@router.post("/{name}/disable")
async def disable_plugin(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    disabled = await ctx.plugins.disable(name)
    if not disabled:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": False}}

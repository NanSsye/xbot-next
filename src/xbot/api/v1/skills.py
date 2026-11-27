from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
import httpx

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get('/catalog')
async def official_catalog() -> dict:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get('https://xbot.catmi.si/api/catalog')
            response.raise_for_status()
            items = response.json()
            if not isinstance(items, list):
                raise ValueError('invalid catalog')
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, '暂时无法读取官方目录，请稍后重试。') from exc
    return {'success': True, 'data': items}


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

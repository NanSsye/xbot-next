from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xbot.adapters.wechat_ilink import WechatIlinkAdapter
from xbot.adapters.wechat_ilink.client import WechatIlinkError
from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


@router.get("")
async def list_adapters(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.adapters.list_adapters()}


@router.post("/{name}/enable")
async def enable_adapter(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    adapter = await ctx.adapters.enable(name)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {name}")
    return {"success": True, "data": ctx.adapters.list_adapters()}


@router.post("/{name}/disable")
async def disable_adapter(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    disabled = await ctx.adapters.disable(name)
    if not disabled:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {name}")
    return {"success": True, "data": ctx.adapters.list_adapters()}


@router.post("/wechat_ilink/login/qrcode")
async def wechat_ilink_login_qrcode(ctx: AppContext = Depends(get_context)) -> dict:
    adapter = ctx.adapters.get("wechat_ilink")
    if not isinstance(adapter, WechatIlinkAdapter):
        raise HTTPException(
            status_code=404,
            detail="wechat_ilink adapter is not enabled. Set adapters.wechat_ilink.enabled=true first.",
        )
    try:
        return {"success": True, "data": await adapter.get_login_qrcode()}
    except WechatIlinkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/wechat_ilink/login/status")
async def wechat_ilink_login_status(
    qrcode: str | None = None,
    ctx: AppContext = Depends(get_context),
) -> dict:
    adapter = ctx.adapters.get("wechat_ilink")
    if not isinstance(adapter, WechatIlinkAdapter):
        raise HTTPException(
            status_code=404,
            detail="wechat_ilink adapter is not enabled. Set adapters.wechat_ilink.enabled=true first.",
        )
    try:
        return {"success": True, "data": await adapter.poll_login_status(qrcode)}
    except WechatIlinkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

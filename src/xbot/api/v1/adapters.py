from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from xbot.adapters.wechat869 import Wechat869Adapter
from xbot.adapters.wechat_ilink import WechatIlinkAdapter
from xbot.adapters.wechat_ilink.client import WechatIlinkError
from xbot.app.deps import get_context
from xbot.runtime.context import AppContext

router = APIRouter()


class Wechat869LoginStartRequest(BaseModel):
    device_type: str = "ipad"
    proxy: str = ""


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


@router.get("/{name}/status")
async def adapter_status(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    adapter = ctx.adapters.get(name)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Adapter not enabled: {name}")
    if isinstance(adapter, Wechat869Adapter):
        try:
            return {"success": True, "data": await adapter.refreshed_public_status()}
        except Exception as exc:
            return {
                "success": True,
                "data": {
                    **adapter.public_status(),
                    "login_status": "error",
                    "login_error": str(exc),
                },
            }
    public_status = getattr(adapter, "public_status", None)
    if callable(public_status):
        return {"success": True, "data": public_status()}
    return {
        "success": True,
        "data": {
            "adapter": name,
            "platform": getattr(adapter, "platform", ""),
            "started": bool(getattr(adapter, "started", False)),
        },
    }


@router.post("/wechat869/login/start")
async def wechat869_login_start(
    payload: Wechat869LoginStartRequest | None = None,
    ctx: AppContext = Depends(get_context),
) -> dict:
    adapter = ctx.adapters.get("wechat869")
    if not isinstance(adapter, Wechat869Adapter):
        raise HTTPException(
            status_code=404,
            detail="wechat869 adapter is not enabled. Enable the channel first.",
        )
    try:
        request = payload or Wechat869LoginStartRequest()
        return {
            "success": True,
            "data": await adapter.start_login(
                device_type=request.device_type,
                proxy=request.proxy,
            ),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/wechat869/login/status")
async def wechat869_login_status(ctx: AppContext = Depends(get_context)) -> dict:
    adapter = ctx.adapters.get("wechat869")
    if not isinstance(adapter, Wechat869Adapter):
        raise HTTPException(
            status_code=404,
            detail="wechat869 adapter is not enabled. Enable the channel first.",
        )
    try:
        return {"success": True, "data": await adapter.poll_login_status()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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

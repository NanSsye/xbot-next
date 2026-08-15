from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from xbot.app.deps import get_context
from xbot.community.config import CommunityConfig
from xbot.community.service import (
    CommunityError,
    CommunityInsufficientPointsError,
    CommunityNotBoundError,
    CommunityService,
)
from xbot.runtime.context import AppContext

router = APIRouter()


class PointsAdjustment(BaseModel):
    delta: int = Field(ge=-100_000, le=100_000)
    reason: str = Field(min_length=1, max_length=256)


class FreezeRequest(BaseModel):
    frozen: bool


@router.get("/config")
async def get_config(ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        config, record = await CommunityService(session).get_config()
        data = config.model_dump(mode="json")
        data["created_at"] = record.created_at.isoformat()
        data["updated_at"] = record.updated_at.isoformat()
    return {"success": True, "data": data}


@router.put("/config")
async def update_config(
    payload: CommunityConfig,
    ctx: AppContext = Depends(get_context),
) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        config = await CommunityService(session).update_config(payload)
    reloaded = await ctx.plugins.reload("WeibanCommunity")
    if not reloaded:
        raise HTTPException(status_code=503, detail="配置已保存，但微伴社区插件热加载失败。")
    return {"success": True, "data": config.model_dump(mode="json")}


@router.get("/overview")
async def overview(ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        service = CommunityService(session)
        config, _ = await service.get_config()
        data = await service.overview(config)
    return {"success": True, "data": data}


@router.get("/users")
async def users(
    limit: int = Query(default=100, ge=1, le=500),
    ctx: AppContext = Depends(get_context),
) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        data = await CommunityService(session).admin_users(limit=limit)
    return {"success": True, "data": data}


@router.get("/ledger")
async def ledger(
    limit: int = Query(default=100, ge=1, le=500),
    ctx: AppContext = Depends(get_context),
) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        data = await CommunityService(session).admin_ledger(limit=limit)
    return {"success": True, "data": data}


@router.delete("/identities/{identity_id}")
async def unbind(identity_id: int, ctx: AppContext = Depends(get_context)) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        deleted = await CommunityService(session).unbind(identity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="绑定记录不存在。")
    return {"success": True, "data": {"identity_id": identity_id, "deleted": True}}


@router.put("/accounts/{account_id}/freeze")
async def freeze_account(
    account_id: int,
    payload: FreezeRequest,
    ctx: AppContext = Depends(get_context),
) -> dict:
    async with ctx.storage.session_factory() as session, session.begin():
        changed = await CommunityService(session).set_frozen(account_id, payload.frozen)
    if not changed:
        raise HTTPException(status_code=404, detail="积分账号不存在。")
    return {"success": True, "data": {"account_id": account_id, "frozen": payload.frozen}}


@router.post("/accounts/{account_id}/points")
async def adjust_points(
    account_id: int,
    payload: PointsAdjustment,
    ctx: AppContext = Depends(get_context),
) -> dict:
    if payload.delta == 0:
        raise HTTPException(status_code=422, detail="积分调整值不能为 0。")
    try:
        async with ctx.storage.session_factory() as session, session.begin():
            data = await CommunityService(session).adjust_points(
                account_id, payload.delta, payload.reason
            )
    except (CommunityInsufficientPointsError, CommunityNotBoundError, CommunityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": data}

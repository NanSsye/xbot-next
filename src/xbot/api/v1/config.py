from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext
from xbot.services.config_service import ConfigApplyError, ConfigConflictError, ConfigService
from xbot.services.llm_model_service import LLMModelDiscoveryError, LLMModelDiscoveryService

router = APIRouter()


class ConfigChange(BaseModel):
    path: str
    value: Any = None
    reset: bool = False


class ConfigUpdateRequest(BaseModel):
    revision: str | None = None
    changes: list[ConfigChange] = Field(default_factory=list, max_length=200)


@router.get("")
async def get_config(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ConfigService(ctx.settings.config_file).snapshot(ctx.settings)}


@router.post("/llm/models/discover")
async def discover_llm_models(ctx: AppContext = Depends(get_context)) -> dict:
    try:
        models = await LLMModelDiscoveryService().discover(ctx.settings.agent.llm)
    except LLMModelDiscoveryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "success": True,
        "data": {
            "models": models,
            "count": len(models),
        },
    }


@router.put("")
async def update_config(
    payload: ConfigUpdateRequest,
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> dict:
    service = ConfigService(ctx.settings.config_file)
    try:
        data = await service.apply(
            request.app,
            changes=[item.model_dump() for item in payload.changes],
            revision=payload.revision,
        )
    except ConfigConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ConfigApplyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "data": data}

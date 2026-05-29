from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from xbot.app.deps import get_context
from xbot.core.exceptions import XBotError
from xbot.runtime.context import AppContext

router = APIRouter()


class AgentTaskRequest(BaseModel):
    input: str
    source: str = "api"


class AgentToolExecuteRequest(BaseModel):
    payload: dict = {}
    task_id: str | None = None
    source: str = "api"


class AgentMemoryRequest(BaseModel):
    kind: str = "semantic"
    summary: str


@router.get("/tools")
async def list_tools(
    toolset: str | None = None,
    platform: str | None = None,
    scope: str | None = None,
    ctx: AppContext = Depends(get_context),
) -> dict:
    toolsets = {item.strip() for item in toolset.split(",") if item.strip()} if toolset else None
    return {
        "success": True,
        "data": ctx.agent.tools.list_tools(
            toolsets=toolsets,
            platform=platform,
            scope=scope,
            mode=ctx.agent.config.mode,
        ),
    }


@router.get("/llm/status")
async def llm_status(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.agent.llm_status()}


@router.get("/mcp/status")
async def mcp_status(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.agent.mcp_status()}


@router.post("/mcp/reload")
async def reload_mcp(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": await ctx.agent.reload_mcp()}


@router.post("/tools/{tool_name}/execute")
async def execute_tool(
    tool_name: str,
    payload: AgentToolExecuteRequest,
    ctx: AppContext = Depends(get_context),
) -> dict:
    try:
        result = await ctx.agent.execute_tool(
            tool_name,
            payload.payload,
            task_id=payload.task_id,
            source=payload.source,
        )
    except XBotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": result.status == "completed", "data": result.model_dump(mode="json")}


@router.get("/policy")
async def get_policy(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.agent.policy.snapshot()}


@router.post("/policy/validate")
async def validate_policy(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": {"valid": True, "policy": ctx.agent.policy.snapshot()}}


@router.post("/tasks")
async def create_task(payload: AgentTaskRequest, ctx: AppContext = Depends(get_context)) -> dict:
    result = await ctx.agent.run_task(payload.input, source=payload.source)
    return {"success": True, "data": result.model_dump()}


@router.get("/memories")
async def list_memories(limit: int = 50, ctx: AppContext = Depends(get_context)) -> dict:
    items = await ctx.agent.memory.list(limit)
    return {
        "success": True,
        "data": [
            {
                "id": item.id,
                "kind": item.kind,
                "summary": item.summary,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
    }


@router.post("/memories")
async def create_memory(
    payload: AgentMemoryRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    item = await ctx.agent.memory.add(payload.kind, payload.summary)
    return {
        "success": True,
        "data": {
            "id": item.id,
            "kind": item.kind,
            "summary": item.summary,
            "created_at": item.created_at.isoformat(),
        },
    }


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    deleted = await ctx.agent.memory.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory not found: {memory_id}")
    return {"success": True, "data": {"id": memory_id, "deleted": True}}


@router.post("/memories/compact")
async def compact_memories(ctx: AppContext = Depends(get_context)) -> dict:
    item = await ctx.agent.memory.compact()
    return {
        "success": True,
        "data": {
            "id": item.id,
            "kind": item.kind,
            "summary": item.summary,
            "created_at": item.created_at.isoformat(),
        },
    }

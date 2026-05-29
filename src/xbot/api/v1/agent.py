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


class BackgroundTaskRequest(BaseModel):
    tool: str
    payload: dict = {}
    source: str = "api"
    description: str = ""
    notify: dict | None = None
    replayable: bool = True


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


@router.get("/tools/visibility")
async def tool_visibility(ctx: AppContext = Depends(get_context)) -> dict:
    mode = ctx.agent.config.mode
    config = ctx.agent.config.toolsets
    sources = {
        "api": set(config.api),
        "private": set(config.private),
        "group": set(config.group),
        "admin": None if mode == "admin" else set(config.admin),
    }
    data = {
        "mode": mode,
        "toolsets": config.model_dump(mode="json"),
        "sources": {},
    }
    for source, toolsets in sources.items():
        tools = ctx.agent.tools.list_tools(toolsets=toolsets, mode=mode)
        data["sources"][source] = {
            "tool_count": len(tools),
            "tools": tools,
        }
    return {"success": True, "data": data}


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


@router.post("/background-tasks")
async def create_background_task(
    payload: BackgroundTaskRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    async def runner():
        result = await ctx.agent.execute_tool(payload.tool, payload.payload, source="background")
        return result.model_dump(mode="json")

    record = ctx.agent.background.start(
        kind="tool",
        runner=runner,
        source=payload.source,
        description=payload.description or f"Run {payload.tool}",
        metadata={
            "tool": payload.tool,
            "payload": payload.payload,
            "notify": payload.notify,
            "replayable": payload.replayable,
        },
    )
    return {"success": True, "data": record.model_dump(mode="json")}


@router.get("/background-tasks/overview")
async def background_task_overview(limit: int = 20, ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": await ctx.agent.background_task_overview(limit)}


@router.get("/background-tasks")
async def list_background_tasks(limit: int = 50, ctx: AppContext = Depends(get_context)) -> dict:
    return {
        "success": True,
        "data": [item.model_dump(mode="json") for item in await ctx.agent.list_background_tasks(limit)],
    }


@router.get("/background-tasks/{task_id}")
async def get_background_task(task_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    record = await ctx.agent.get_background_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Background task not found: {task_id}")
    return {"success": True, "data": record.model_dump(mode="json")}


@router.post("/background-tasks/{task_id}/replay")
async def replay_background_task(task_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        record = await ctx.agent.replay_background_task(task_id)
    except XBotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": record.model_dump(mode="json")}


@router.post("/background-tasks/{task_id}/cancel")
async def cancel_background_task(task_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    record = await ctx.agent.background.cancel(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Background task not found: {task_id}")
    return {"success": True, "data": record.model_dump(mode="json")}


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

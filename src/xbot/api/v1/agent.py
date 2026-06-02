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


class AgentTaskResumeRequest(BaseModel):
    source: str | None = None


class AgentToolExecuteRequest(BaseModel):
    payload: dict = {}
    task_id: str | None = None
    source: str = "api"


class AgentMemoryRequest(BaseModel):
    kind: str = "note"
    summary: str = ""


class BackgroundTaskRequest(BaseModel):
    tool: str
    payload: dict = {}
    source: str = "api"
    description: str = ""
    notify: dict | None = None
    replayable: bool = True


class ScheduledJobCreateRequest(BaseModel):
    input: str
    schedule: str
    name: str | None = None
    source: str = "api:schedule"
    reply_policy: str = "none"
    max_runs: int | None = None
    timezone: str | None = None
    metadata: dict = {}


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
    tools = ctx.agent.tools.list_tools(mode=ctx.agent.config.mode)
    data = {
        "mode": ctx.agent.config.mode,
        "runtime": "hermes",
        "note": "Hermes owns Agent tool visibility and execution. xbot keeps this catalog for UI display only.",
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


@router.get("/tasks")
async def list_tasks(limit: int = 50, ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": await ctx.agent.list_tasks(limit=limit)}


@router.get("/tasks/{task_id}")
async def get_task_detail(task_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    detail = await ctx.agent.get_task_detail(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Agent task not found: {task_id}")
    return {"success": True, "data": detail}


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    payload: AgentTaskResumeRequest | None = None,
    ctx: AppContext = Depends(get_context),
) -> dict:
    try:
        result = await ctx.agent.resume_task(task_id, source=payload.source if payload else None)
    except XBotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": result.model_dump(mode="json")}


@router.get("/events")
async def list_agent_events(
    task_id: str | None = None,
    limit: int = 100,
    ctx: AppContext = Depends(get_context),
) -> dict:
    return {"success": True, "data": await ctx.agent.list_events(task_id=task_id, limit=limit)}


@router.get("/memories")
async def list_memories(limit: int = 50) -> dict:
    return {"success": True, "data": []}


@router.post("/memories")
async def create_memory(payload: AgentMemoryRequest) -> dict:
    return {
        "success": True,
        "data": {
            "id": "hermes-memory-managed",
            "kind": payload.kind or "note",
            "summary": "Hermes owns memory in data/hermes; xbot memory API is compatibility-only.",
            "created_at": "",
        },
    }


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str) -> dict:
    return {"success": True, "data": {"id": memory_id, "deleted": False, "runtime": "hermes"}}


@router.post("/memories/compact")
async def compact_memories() -> dict:
    return {
        "success": True,
        "data": {
            "id": "hermes-memory-managed",
            "kind": "system",
            "summary": "Hermes handles memory compaction internally.",
            "created_at": "",
        },
    }


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


@router.get("/scheduled-jobs")
async def list_scheduled_jobs(
    include_disabled: bool = False,
    limit: int = 100,
    ctx: AppContext = Depends(get_context),
) -> dict:
    jobs = await ctx.agent.scheduler.list(include_disabled=include_disabled, limit=limit)
    return {"success": True, "data": [item.model_dump(mode="json") for item in jobs]}


@router.post("/scheduled-jobs")
async def create_scheduled_job(
    payload: ScheduledJobCreateRequest,
    ctx: AppContext = Depends(get_context),
) -> dict:
    try:
        job = await ctx.agent.scheduler.create(
            input_text=payload.input,
            schedule=payload.schedule,
            name=payload.name,
            source=payload.source,
            reply_policy=payload.reply_policy,
            max_runs=payload.max_runs,
            timezone_name=payload.timezone,
            metadata=payload.metadata,
        )
    except XBotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": job.model_dump(mode="json")}


@router.get("/scheduled-jobs/{job_id}")
async def get_scheduled_job(job_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    job = await ctx.agent.scheduler.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Scheduled job not found: {job_id}")
    return {"success": True, "data": job.model_dump(mode="json")}


@router.post("/scheduled-jobs/{job_id}/pause")
async def pause_scheduled_job(job_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        job = await ctx.agent.scheduler.pause(job_id)
    except XBotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": job.model_dump(mode="json")}


@router.post("/scheduled-jobs/{job_id}/resume")
async def resume_scheduled_job(job_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        job = await ctx.agent.scheduler.resume(job_id)
    except XBotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": job.model_dump(mode="json")}


@router.post("/scheduled-jobs/{job_id}/run")
async def run_scheduled_job(job_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        job = await ctx.agent.scheduler.run_now(job_id)
    except XBotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": job.model_dump(mode="json")}


@router.delete("/scheduled-jobs/{job_id}")
async def delete_scheduled_job(job_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    deleted = await ctx.agent.scheduler.delete(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Scheduled job not found: {job_id}")
    return {"success": True, "data": {"id": job_id, "deleted": True}}


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

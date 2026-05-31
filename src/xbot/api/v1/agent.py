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


class CuratedMemoryCreateRequest(BaseModel):
    target: str = "memory"
    content: str


class CuratedMemoryReplaceRequest(BaseModel):
    target: str = "memory"
    old_text: str
    content: str


class CuratedMemoryRemoveRequest(BaseModel):
    target: str = "memory"
    old_text: str


class MemoryFlushRequest(BaseModel):
    reason: str = "api"


class WikiManageRequest(BaseModel):
    action: str
    wiki: str = "xbot"
    topic: str | None = None
    source: str | None = None
    text: str | None = None
    query: str | None = None
    limit: int | None = None
    pages: list[str] | None = None
    page: str | None = None
    title: str | None = None
    content: str | None = None
    message: str | None = None
    dry_run: bool | None = None


class CuratorReportRequest(BaseModel):
    use_llm: bool = True


class CuratorApplyRequest(BaseModel):
    report_id: str = "latest"
    proposal_ids: list[str] = []


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


@router.get("/events")
async def list_agent_events(
    task_id: str | None = None,
    limit: int = 100,
    ctx: AppContext = Depends(get_context),
) -> dict:
    return {"success": True, "data": await ctx.agent.list_events(task_id=task_id, limit=limit)}


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


@router.get("/memory/{target}")
async def read_curated_memory(target: str, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        result = ctx.agent.memory.read_curated(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": bool(result.get("success")), "data": result}


@router.post("/memory")
async def create_curated_memory(
    payload: CuratedMemoryCreateRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    try:
        result = ctx.agent.memory.add_curated(payload.target, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "failed to add memory"))
    return {"success": True, "data": result}


@router.put("/memory")
async def replace_curated_memory(
    payload: CuratedMemoryReplaceRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    try:
        result = ctx.agent.memory.replace_curated(payload.target, payload.old_text, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "failed to replace memory"))
    return {"success": True, "data": result}


@router.delete("/memory")
async def remove_curated_memory(
    payload: CuratedMemoryRemoveRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    try:
        result = ctx.agent.memory.remove_curated(payload.target, payload.old_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "failed to remove memory"))
    return {"success": True, "data": result}


@router.post("/memory/flush")
async def flush_curated_memory(
    payload: MemoryFlushRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    result = await ctx.agent.flush_memory(reason=payload.reason)
    return {"success": True, "data": result}


@router.post("/wiki")
async def manage_wiki(payload: WikiManageRequest, ctx: AppContext = Depends(get_context)) -> dict:
    if not ctx.agent.wiki:
        raise HTTPException(status_code=404, detail="Wiki store is disabled")
    try:
        result = ctx.agent.wiki.manage(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success", False):
        raise HTTPException(status_code=400, detail=result.get("error", "wiki operation failed"))
    return {"success": True, "data": result}


@router.get("/wiki/{wiki}/query")
async def query_wiki(wiki: str, query: str, limit: int = 5, ctx: AppContext = Depends(get_context)) -> dict:
    if not ctx.agent.wiki:
        raise HTTPException(status_code=404, detail="Wiki store is disabled")
    try:
        result = ctx.agent.wiki.query(wiki=wiki, query=query, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success", False):
        raise HTTPException(status_code=400, detail=result.get("error", "wiki query failed"))
    return {"success": True, "data": result}


@router.get("/curator")
async def curator_status(ctx: AppContext = Depends(get_context)) -> dict:
    usage = ctx.skills.agent_usage_snapshot() if ctx.skills else {}
    counts: dict[str, int] = {}
    for record in usage.values():
        state = str(record.get("state") or "active")
        counts[state] = counts.get(state, 0) + 1
    return {
        "success": True,
        "data": {
            "enabled": bool(ctx.skills and ctx.skills.config.curator_enabled),
            "counts": counts,
            "skills": ctx.skills.list_agent_owned_skills() if ctx.skills else [],
        },
    }


@router.post("/curator/run")
async def run_curator(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": await ctx.agent.run_curator()}


@router.post("/curator/report")
async def create_curator_report(
    payload: CuratorReportRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    return {"success": True, "data": await ctx.agent.generate_curator_report(use_llm=payload.use_llm)}


@router.get("/curator/report/{report_id}")
async def get_curator_report(report_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    try:
        report = ctx.skills.load_curator_report(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": report}


@router.post("/curator/apply")
async def apply_curator_report(
    payload: CuratorApplyRequest, ctx: AppContext = Depends(get_context)
) -> dict:
    try:
        result = await ctx.agent.apply_curator_report(
            report_id=payload.report_id,
            proposal_ids=payload.proposal_ids or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": result}


@router.post("/curator/{action}/{name}")
async def update_curator_skill(action: str, name: str, ctx: AppContext = Depends(get_context)) -> dict:
    if action not in {"archive", "restore", "pin", "unpin"}:
        raise HTTPException(status_code=400, detail="action must be archive, restore, pin, or unpin")
    try:
        result = await ctx.skills.manage({"action": action, "name": name})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": result}


@router.get("/skills/agent-owned")
async def list_agent_owned_skills(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.skills.list_agent_owned_skills() if ctx.skills else []}


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

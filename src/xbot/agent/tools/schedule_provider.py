from __future__ import annotations

from typing import Any

from xbot.agent.scheduler import ScheduledJobManager, parse_schedule
from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.exceptions import XBotError


def register_schedule_tools(registry: ToolRegistry, *, scheduler: ScheduledJobManager) -> None:
    provider = ScheduleToolProvider(scheduler=scheduler)
    for tool in provider.tools():
        registry.register(tool)


class ScheduleToolProvider:
    def __init__(self, *, scheduler: ScheduledJobManager) -> None:
        self.scheduler = scheduler

    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="schedule.create",
                description=(
                    "Create a persistent scheduled Agent job. Supports one-shot durations "
                    "(30m, 2h), recurring intervals (every 30m), daily HH:MM, ISO datetime, "
                    "and 5-field cron expressions."
                ),
                risk_level="execute",
                handler=self.create,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["input", "schedule"],
                    "properties": {
                        "input": {"type": "string"},
                        "schedule": {"type": "string"},
                        "name": {"type": "string"},
                        "source": {"type": "string"},
                        "reply_policy": {
                            "type": "string",
                            "enum": ["none", "parent_agent", "channel"],
                            "default": "parent_agent",
                        },
                        "max_runs": {"type": "integer"},
                        "notify": {"type": "object"},
                        "timezone": {"type": "string"},
                    },
                },
            ),
            ToolDefinition(
                name="schedule.list",
                description="List scheduled Agent jobs.",
                risk_level="read",
                handler=self.list_jobs,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_disabled": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
            ToolDefinition(
                name="schedule.get",
                description="Get one scheduled Agent job.",
                risk_level="read",
                handler=self.get,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["job_id"],
                    "properties": {"job_id": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="schedule.pause",
                description="Pause a scheduled Agent job.",
                risk_level="execute",
                handler=self.pause,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["job_id"],
                    "properties": {"job_id": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="schedule.resume",
                description="Resume a scheduled Agent job.",
                risk_level="execute",
                handler=self.resume,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["job_id"],
                    "properties": {"job_id": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="schedule.delete",
                description="Delete a scheduled Agent job.",
                risk_level="execute",
                handler=self.delete,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["job_id"],
                    "properties": {"job_id": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="schedule.run_now",
                description="Run a scheduled Agent job immediately without changing its next scheduled time.",
                risk_level="execute",
                handler=self.run_now,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["job_id"],
                    "properties": {"job_id": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="schedule.parse",
                description="Parse and validate a schedule expression.",
                risk_level="read",
                handler=self.parse,
                toolset="schedule",
                source="schedule",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["schedule"],
                    "properties": {
                        "schedule": {"type": "string"},
                        "timezone": {"type": "string"},
                    },
                },
            ),
        ]

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = {}
        notify = payload.get("notify")
        if isinstance(notify, dict):
            metadata["notify"] = notify
        source = str(payload.get("source") or payload.get("_source") or "schedule")
        reply_policy = str(payload.get("reply_policy") or "parent_agent")
        job = await self.scheduler.create(
            input_text=str(payload.get("input") or ""),
            schedule=str(payload.get("schedule") or ""),
            name=str(payload.get("name") or "").strip() or None,
            source=source,
            reply_policy=reply_policy,
            max_runs=_optional_int(payload.get("max_runs")),
            metadata=metadata,
            timezone_name=str(payload.get("timezone") or "").strip() or None,
        )
        return self._format(job)

    async def list_jobs(self, payload: dict[str, Any]) -> dict[str, Any]:
        jobs = await self.scheduler.list(
            include_disabled=bool(payload.get("include_disabled", False)),
            limit=int(payload.get("limit", 50)),
        )
        return {"jobs": [self._format(job) for job in jobs], "count": len(jobs)}

    async def get(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = await self.scheduler.get(str(payload["job_id"]))
        if not job:
            raise XBotError(f"Scheduled job not found: {payload['job_id']}")
        return self._format(job)

    async def pause(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._format(await self.scheduler.pause(str(payload["job_id"])))

    async def resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._format(await self.scheduler.resume(str(payload["job_id"])))

    async def delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        deleted = await self.scheduler.delete(str(payload["job_id"]))
        return {"success": deleted, "job_id": str(payload["job_id"])}

    async def run_now(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._format(await self.scheduler.run_now(str(payload["job_id"])))

    async def parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = parse_schedule(
            str(payload.get("schedule") or ""),
            timezone_name=str(payload.get("timezone") or self.scheduler.timezone_name),
        )
        return spec.model_dump(mode="json")

    def _format(self, job) -> dict[str, Any]:
        data = job.model_dump(mode="json")
        data["metadata"] = {
            key: value
            for key, value in (job.metadata or {}).items()
            if key not in {"notify"}
        }
        data["has_notify_target"] = isinstance((job.metadata or {}).get("notify"), dict)
        return data


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed <= 0:
        raise XBotError("max_runs must be greater than 0.")
    return parsed

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from xbot.agent.background import BackgroundTaskManager
from xbot.core.exceptions import XBotError
from xbot.core.logging import logger

AgentRunnerCallback = Callable[[str, str], Awaitable[Any]]
RepositoryProvider = Callable[[], Any]


class ScheduleSpec(BaseModel):
    schedule_type: str
    schedule_expr: str
    schedule_display: str
    next_run_at: datetime | None = None


class ScheduledJob(BaseModel):
    id: str
    name: str
    enabled: bool = True
    schedule_type: str
    schedule_expr: str
    schedule_display: str = ""
    timezone: str = "Asia/Shanghai"
    input: str
    source: str = "schedule"
    reply_policy: str = "parent_agent"
    max_runs: int | None = None
    run_count: int = 0
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_task_id: str | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_storage(cls, record) -> "ScheduledJob":
        if isinstance(record, cls):
            return record
        metadata = json.loads(record.metadata_json or "{}")
        return cls(
            id=record.id,
            name=record.name,
            enabled=record.enabled,
            schedule_type=record.schedule_type,
            schedule_expr=record.schedule_expr,
            schedule_display=record.schedule_display,
            timezone=record.timezone,
            input=record.input,
            source=record.source,
            reply_policy=record.reply_policy,
            max_runs=record.max_runs,
            run_count=record.run_count,
            next_run_at=record.next_run_at,
            last_run_at=record.last_run_at,
            last_status=record.last_status,
            last_task_id=record.last_task_id,
            last_error=record.last_error,
            metadata=metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_schedule(schedule: str, *, timezone_name: str = "Asia/Shanghai") -> ScheduleSpec:
    text = (schedule or "").strip()
    if not text:
        raise XBotError("schedule is required.")
    lowered = text.lower()
    tz = _zoneinfo(timezone_name)
    now = datetime.now(tz)

    if lowered.startswith("every "):
        seconds = _parse_duration_seconds(text[6:].strip())
        if seconds < 60:
            raise XBotError("interval schedule must be at least 1 minute.")
        next_run = now + timedelta(seconds=seconds)
        return ScheduleSpec(
            schedule_type="interval",
            schedule_expr=str(seconds),
            schedule_display=f"every {_duration_display(seconds)}",
            next_run_at=_to_utc_naive(next_run),
        )

    if lowered.startswith("daily "):
        run_time = _parse_hhmm(text[6:].strip())
        next_run = _next_daily(now, run_time[0], run_time[1])
        return ScheduleSpec(
            schedule_type="daily",
            schedule_expr=f"{run_time[0]:02d}:{run_time[1]:02d}",
            schedule_display=f"daily {run_time[0]:02d}:{run_time[1]:02d}",
            next_run_at=_to_utc_naive(next_run),
        )

    hhmm = _try_parse_hhmm(text)
    if hhmm:
        next_run = _next_daily(now, hhmm[0], hhmm[1])
        return ScheduleSpec(
            schedule_type="daily",
            schedule_expr=f"{hhmm[0]:02d}:{hhmm[1]:02d}",
            schedule_display=f"daily {hhmm[0]:02d}:{hhmm[1]:02d}",
            next_run_at=_to_utc_naive(next_run),
        )

    cron_parts = text.split()
    if len(cron_parts) == 5:
        _validate_cron_expr(text)
        next_run = _next_cron_time(text, now)
        return ScheduleSpec(
            schedule_type="cron",
            schedule_expr=text,
            schedule_display=text,
            next_run_at=_to_utc_naive(next_run),
        )

    dt = _try_parse_datetime(text, tz)
    if dt:
        return ScheduleSpec(
            schedule_type="once",
            schedule_expr=_to_utc_naive(dt).isoformat(),
            schedule_display=f"once at {dt.strftime('%Y-%m-%d %H:%M')}",
            next_run_at=_to_utc_naive(dt),
        )

    seconds = _parse_duration_seconds(text, allow_error=False)
    if seconds is not None:
        run_at = now + timedelta(seconds=seconds)
        return ScheduleSpec(
            schedule_type="once",
            schedule_expr=_to_utc_naive(run_at).isoformat(),
            schedule_display=f"once in {_duration_display(seconds)}",
            next_run_at=_to_utc_naive(run_at),
        )

    raise XBotError(
        "Invalid schedule. Use examples like: 30m, every 2h, daily 09:00, "
        "2026-06-01T09:00:00, or cron '0 9 * * *'."
    )


def compute_next_run(job: ScheduledJob, *, from_time: datetime | None = None) -> datetime | None:
    base_utc = _ensure_utc_naive(from_time or now_utc())
    tz = _zoneinfo(job.timezone)
    base = base_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    if job.max_runs is not None and job.run_count >= job.max_runs:
        return None
    if job.schedule_type == "once":
        return None
    if job.schedule_type == "interval":
        seconds = int(job.schedule_expr)
        return _to_utc_naive(base + timedelta(seconds=seconds))
    if job.schedule_type == "daily":
        hour, minute = _parse_hhmm(job.schedule_expr)
        return _to_utc_naive(_next_daily(base, hour, minute))
    if job.schedule_type == "cron":
        return _to_utc_naive(_next_cron_time(job.schedule_expr, base))
    return None


class ScheduledJobManager:
    def __init__(
        self,
        *,
        background: BackgroundTaskManager,
        run_agent: AgentRunnerCallback,
        repository_provider: RepositoryProvider | None = None,
        timezone_name: str = "Asia/Shanghai",
        tick_seconds: float = 30.0,
        max_due_per_tick: int = 10,
    ) -> None:
        self.background = background
        self.run_agent = run_agent
        self.repository_provider = repository_provider
        self.timezone_name = timezone_name
        self.tick_seconds = tick_seconds
        self.max_due_per_tick = max_due_per_tick
        self._jobs: dict[str, ScheduledJob] = {}
        self._running_job_ids: set[str] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self._load_jobs()
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="xbot-agent-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def create(
        self,
        *,
        input_text: str,
        schedule: str,
        name: str | None = None,
        source: str = "schedule",
        reply_policy: str = "parent_agent",
        max_runs: int | None = None,
        metadata: dict[str, Any] | None = None,
        timezone_name: str | None = None,
    ) -> ScheduledJob:
        input_text = input_text.strip()
        if not input_text:
            raise XBotError("input is required.")
        tz_name = timezone_name or self.timezone_name
        spec = parse_schedule(schedule, timezone_name=tz_name)
        if spec.schedule_type == "once":
            max_runs = 1
        job = ScheduledJob(
            id=str(uuid4()),
            name=(name or _default_job_name(input_text)).strip()[:256],
            schedule_type=spec.schedule_type,
            schedule_expr=spec.schedule_expr,
            schedule_display=spec.schedule_display,
            timezone=tz_name,
            input=input_text,
            source=source or "schedule",
            reply_policy=reply_policy or "parent_agent",
            max_runs=max_runs,
            next_run_at=spec.next_run_at,
            metadata=metadata or {},
        )
        await self._save(job)
        return job

    async def list(self, *, include_disabled: bool = False, limit: int = 100) -> list[ScheduledJob]:
        if not self.repository_provider:
            jobs = list(self._jobs.values())
            if not include_disabled:
                jobs = [job for job in jobs if job.enabled]
            return sorted(jobs, key=lambda item: item.created_at, reverse=True)[:limit]
        async with self.repository_provider() as repo:
            records = await repo.list_scheduled_jobs(include_disabled=include_disabled, limit=limit)
        jobs = [ScheduledJob.from_storage(record) for record in records]
        self._jobs.update({job.id: job for job in jobs})
        return jobs

    async def get(self, job_id: str) -> ScheduledJob | None:
        if job_id in self._jobs:
            return self._jobs[job_id]
        if not self.repository_provider:
            return None
        async with self.repository_provider() as repo:
            record = await repo.get_scheduled_job(job_id)
        if not record:
            return None
        job = ScheduledJob.from_storage(record)
        self._jobs[job.id] = job
        return job

    async def pause(self, job_id: str) -> ScheduledJob:
        job = await self._require(job_id)
        job.enabled = False
        job.updated_at = now_utc()
        await self._save(job)
        return job

    async def resume(self, job_id: str) -> ScheduledJob:
        job = await self._require(job_id)
        job.enabled = True
        if job.next_run_at is None:
            job.next_run_at = compute_next_run(job, from_time=now_utc()) or now_utc()
        job.updated_at = now_utc()
        await self._save(job)
        return job

    async def delete(self, job_id: str) -> bool:
        self._jobs.pop(job_id, None)
        if not self.repository_provider:
            return True
        async with self.repository_provider() as repo:
            return await repo.delete_scheduled_job(job_id)

    async def run_now(self, job_id: str) -> ScheduledJob:
        job = await self._require(job_id)
        await self._start_job(job, manual=True)
        return job

    async def tick(self) -> int:
        await self._load_due_jobs()
        due = [
            job
            for job in self._jobs.values()
            if job.enabled
            and job.next_run_at is not None
            and _ensure_utc_naive(job.next_run_at) <= now_utc()
            and job.id not in self._running_job_ids
        ]
        due.sort(key=lambda item: item.next_run_at or now_utc())
        for job in due[: self.max_due_per_tick]:
            await self._start_job(job)
        return len(due[: self.max_due_per_tick])

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Agent scheduler tick failed: {}", exc)
            await asyncio.sleep(max(1.0, self.tick_seconds))

    async def _start_job(self, job: ScheduledJob, *, manual: bool = False) -> None:
        if job.id in self._running_job_ids:
            return
        self._running_job_ids.add(job.id)
        job.last_status = "queued"
        job.last_error = None
        job.updated_at = now_utc()
        await self._save(job)

        async def runner(job_id=job.id, manual=manual):
            current = await self.get(job_id)
            if current is None:
                return {"success": False, "error": "scheduled job deleted"}
            try:
                current.last_status = "running"
                current.last_run_at = now_utc()
                current.run_count += 1
                if not manual:
                    current.next_run_at = compute_next_run(current, from_time=current.last_run_at)
                await self._save(current)
                result = await self.run_agent(current.input, source=current.source or "schedule")
            except Exception as exc:
                current.last_status = "failed"
                current.last_error = str(exc)
                if current.enabled and current.next_run_at is None:
                    current.next_run_at = compute_next_run(current, from_time=now_utc())
                await self._save(current)
                raise
            else:
                current.last_status = "completed"
                current.last_error = None
                if hasattr(result, "task_id"):
                    current.last_task_id = str(result.task_id)
                elif isinstance(result, dict) and result.get("task_id"):
                    current.last_task_id = str(result["task_id"])
                if current.max_runs is not None and current.run_count >= current.max_runs:
                    current.enabled = False
                    current.next_run_at = None
                await self._save(current)
                return result
            finally:
                self._running_job_ids.discard(job_id)

        metadata = dict(job.metadata or {})
        if job.reply_policy:
            metadata.setdefault("notify_mode", job.reply_policy)
        notify_mode = str(metadata.get("notify_mode") or job.reply_policy or "parent_agent")
        notify = metadata.get("notify") if notify_mode != "none" else None
        record = self.background.start(
            kind="agent",
            runner=runner,
            source="schedule",
            description=f"Scheduled job: {job.name}",
            metadata={
                "scheduled_job_id": job.id,
                "scheduled_job_name": job.name,
                "input": job.input,
                "source": job.source,
                "notify": notify,
                "notify_mode": notify_mode,
                "replayable": True,
            },
        )
        job.last_task_id = record.id
        await self._save(job)

    async def _require(self, job_id: str) -> ScheduledJob:
        job = await self.get(job_id)
        if job is None:
            raise XBotError(f"Scheduled job not found: {job_id}")
        return job

    async def _save(self, job: ScheduledJob) -> None:
        job.updated_at = now_utc()
        self._jobs[job.id] = job
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            await repo.upsert_scheduled_job(job)

    async def _load_jobs(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            records = await repo.list_scheduled_jobs(include_disabled=True, limit=500)
        self._jobs = {record.id: ScheduledJob.from_storage(record) for record in records}

    async def _load_due_jobs(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            records = await repo.list_due_scheduled_jobs(now=now_utc(), limit=self.max_due_per_tick)
        for record in records:
            self._jobs[record.id] = ScheduledJob.from_storage(record)


def _default_job_name(input_text: str) -> str:
    first = re.sub(r"\s+", " ", input_text).strip()
    return first[:40] or "scheduled job"


def _zoneinfo(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8), name="Asia/Shanghai")


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _ensure_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_duration_seconds(text: str, *, allow_error: bool = True) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days)\s*", text, re.I)
    if not match:
        if allow_error:
            raise XBotError("Invalid duration. Use 30m, 2h, or 1d.")
        return None
    value = int(match.group(1))
    unit = match.group(2).lower()[0]
    return value * {"m": 60, "h": 3600, "d": 86400}[unit]


def _duration_display(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}m"


def _try_parse_datetime(text: str, tz) -> datetime | None:
    if "T" not in text and not re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _try_parse_hhmm(text: str) -> tuple[int, int] | None:
    try:
        return _parse_hhmm(text)
    except XBotError:
        return None


def _parse_hhmm(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text)
    if not match:
        raise XBotError("Invalid time. Use HH:MM, for example 09:30.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise XBotError("Invalid time. Hour must be 0-23 and minute must be 0-59.")
    return hour, minute


def _next_daily(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _validate_cron_expr(expr: str) -> None:
    parts = expr.split()
    if len(parts) != 5:
        raise XBotError("Cron schedule must have 5 fields: minute hour day month weekday.")
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for part, bounds in zip(parts, ranges, strict=True):
        _parse_cron_field(part, bounds[0], bounds[1])


def _next_cron_time(expr: str, base: datetime) -> datetime:
    fields = expr.split()
    allowed = [
        _parse_cron_field(fields[0], 0, 59),
        _parse_cron_field(fields[1], 0, 23),
        _parse_cron_field(fields[2], 1, 31),
        _parse_cron_field(fields[3], 1, 12),
        _parse_cron_field(fields[4], 0, 7),
    ]
    candidate = (base + timedelta(minutes=1)).replace(second=0, microsecond=0)
    end = candidate + timedelta(days=366)
    while candidate <= end:
        weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in allowed[0]
            and candidate.hour in allowed[1]
            and candidate.day in allowed[2]
            and candidate.month in allowed[3]
            and (weekday in allowed[4] or (weekday == 0 and 7 in allowed[4]))
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise XBotError("Cron schedule has no run time within the next year.")


def _parse_cron_field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise XBotError(f"Invalid cron field: {text}")
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise XBotError(f"Invalid cron step: {step_text}")
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(part)
        if start < low or end > high or start > end:
            raise XBotError(f"Invalid cron range: {part}")
        values.update(range(start, end + 1, step))
    return values

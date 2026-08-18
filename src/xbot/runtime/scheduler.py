from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from xbot.core.timeutils import utc_now
from xbot.messaging.models import Reply
from xbot.storage.models import ReplyOutboxRecord, RuntimeScheduledJobRecord

JobHandler = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class _Job:
    name: str
    source: str
    interval_seconds: int
    handler: JobHandler
    run_immediately: bool


async def enqueue_reply(
    session,
    reply: Reply,
    *,
    idempotency_key: str,
    source: str,
    max_attempts: int = 8,
) -> bool:
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 128:
        raise ValueError("Outbox idempotency_key must contain 1-128 characters")
    now = utc_now()
    values = {
        "id": uuid4().hex,
        "idempotency_key": key,
        "source": str(source or "runtime")[:128],
        "platform": reply.platform[:64],
        "adapter": reply.adapter[:64],
        "conversation_id": reply.conversation_id[:512],
        "reply_json": json.dumps(
            reply.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ),
        "status": "pending",
        "attempt_count": 0,
        "max_attempts": max(1, int(max_attempts)),
        "available_at": now,
        "created_at": now,
        "updated_at": now,
    }
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        statement = (
            postgresql_insert(ReplyOutboxRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(ReplyOutboxRecord.id)
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(ReplyOutboxRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(ReplyOutboxRecord.id)
        )
    else:
        existing = await session.scalar(
            select(ReplyOutboxRecord.id).where(
                ReplyOutboxRecord.idempotency_key == key
            )
        )
        if existing is not None:
            return False
        session.add(ReplyOutboxRecord(**values))
        await session.flush()
        return True
    return (await session.execute(statement)).scalar_one_or_none() is not None


class Scheduler:
    def __init__(
        self,
        session_factory=None,
        reply_sender: Callable[[Reply], Awaitable[object | None]] | None = None,
        *,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 300,
        outbox_batch_size: int = 20,
    ) -> None:
        self.session_factory = session_factory
        self.reply_sender = reply_sender
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        self.lease_seconds = max(30, int(lease_seconds))
        self.outbox_batch_size = max(1, min(int(outbox_batch_size), 100))
        self.owner_id = uuid4().hex
        self._jobs: dict[str, _Job] = {}
        self._ensured_jobs: set[str] = set()
        self._job_tasks: dict[str, asyncio.Task] = {}
        self._task: asyncio.Task | None = None

    def attach_reply_sender(
        self, sender: Callable[[Reply], Awaitable[object | None]]
    ) -> None:
        self.reply_sender = sender

    def register(
        self,
        name: str,
        *,
        interval_seconds: int,
        handler: JobHandler,
        source: str = "runtime",
        run_immediately: bool = True,
    ) -> None:
        normalized = str(name or "").strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("Scheduled job name must contain 1-128 characters")
        self._jobs[normalized] = _Job(
            name=normalized,
            source=str(source or "runtime")[:128],
            interval_seconds=max(1, int(interval_seconds)),
            handler=handler,
            run_immediately=bool(run_immediately),
        )
        self._ensured_jobs.discard(normalized)

    async def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)
        self._ensured_jobs.discard(name)
        task = self._job_tasks.pop(name, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def start(self) -> None:
        if self._task is not None or self.session_factory is None:
            return
        self._task = asyncio.create_task(self._run(), name="xbot-runtime-scheduler")
        logger.info("Runtime scheduler started: owner={}", self.owner_id[:8])

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        jobs = list(self._job_tasks.values())
        self._job_tasks.clear()
        for job in jobs:
            job.cancel()
        for job in jobs:
            with contextlib.suppress(asyncio.CancelledError):
                await job
        logger.info("Runtime scheduler stopped")

    async def _run(self) -> None:
        while True:
            try:
                await self._schedule_due_jobs()
                await self.dispatch_outbox_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Runtime scheduler loop failed: {}", exc)
            await asyncio.sleep(self.poll_interval_seconds)

    async def _schedule_due_jobs(self) -> None:
        for job in list(self._jobs.values()):
            if job.name in self._job_tasks:
                continue
            if job.name not in self._ensured_jobs:
                await self._ensure_job(job)
                self._ensured_jobs.add(job.name)
            if not await self._claim_job(job):
                continue
            task = asyncio.create_task(
                self._execute_job(job), name=f"xbot-job-{job.name}"
            )
            self._job_tasks[job.name] = task
            task.add_done_callback(
                lambda completed, name=job.name: self._job_done(name, completed)
            )

    def _job_done(self, name: str, task: asyncio.Task) -> None:
        if self._job_tasks.get(name) is task:
            self._job_tasks.pop(name, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Scheduled job task failed: name={} error={}", name, exc)

    async def _ensure_job(self, job: _Job) -> None:
        now = utc_now()
        next_run = now if job.run_immediately else now + timedelta(
            seconds=job.interval_seconds
        )
        values = {
            "name": job.name,
            "source": job.source,
            "interval_seconds": job.interval_seconds,
            "next_run_at": next_run,
            "created_at": now,
            "updated_at": now,
        }
        async with self.session_factory() as session, session.begin():
            dialect = session.bind.dialect.name
            update_values = {
                "source": job.source,
                "interval_seconds": job.interval_seconds,
                "updated_at": now,
            }
            if dialect == "postgresql":
                statement = postgresql_insert(RuntimeScheduledJobRecord).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=["name"], set_=update_values
                )
            elif dialect == "sqlite":
                statement = sqlite_insert(RuntimeScheduledJobRecord).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=["name"], set_=update_values
                )
            else:
                record = await session.get(RuntimeScheduledJobRecord, job.name)
                if record is None:
                    session.add(RuntimeScheduledJobRecord(**values))
                else:
                    record.source = job.source
                    record.interval_seconds = job.interval_seconds
                    record.updated_at = now
                return
            await session.execute(statement)

    async def _claim_job(self, job: _Job) -> bool:
        now = utc_now()
        async with self.session_factory() as session, session.begin():
            record = (
                await session.execute(
                    select(RuntimeScheduledJobRecord)
                    .where(
                        RuntimeScheduledJobRecord.name == job.name,
                        RuntimeScheduledJobRecord.next_run_at <= now,
                        or_(
                            RuntimeScheduledJobRecord.lease_expires_at.is_(None),
                            RuntimeScheduledJobRecord.lease_expires_at <= now,
                        ),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if record is None:
                return False
            record.lease_owner = self.owner_id
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            record.next_run_at = now + timedelta(seconds=job.interval_seconds)
            record.last_started_at = now
            record.last_status = "running"
            record.last_error = None
            record.updated_at = now
            return True

    async def _execute_job(self, job: _Job) -> None:
        try:
            await job.handler()
        except asyncio.CancelledError:
            await asyncio.shield(self._finish_job(job.name, "cancelled", None))
            raise
        except Exception as exc:
            await self._finish_job(job.name, "failed", str(exc))
            logger.exception("Scheduled job failed: name={} error={}", job.name, exc)
            return
        await self._finish_job(job.name, "success", None)

    async def _finish_job(self, name: str, status: str, error: str | None) -> None:
        now = utc_now()
        async with self.session_factory() as session, session.begin():
            record = await session.get(RuntimeScheduledJobRecord, name)
            if record is None or record.lease_owner != self.owner_id:
                return
            record.lease_owner = None
            record.lease_expires_at = None
            record.last_finished_at = now
            record.last_status = status
            record.last_error = error[:2000] if error else None
            record.updated_at = now

    async def dispatch_outbox_once(self) -> int:
        if self.reply_sender is None or self.session_factory is None:
            return 0
        records = await self._claim_outbox()
        for record_id, reply_json in records:
            try:
                reply = Reply.model_validate_json(reply_json)
                response = await self.reply_sender(reply)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._fail_outbox(record_id, exc)
            else:
                await self._complete_outbox(record_id, response)
        return len(records)

    async def _claim_outbox(self) -> list[tuple[str, str]]:
        now = utc_now()
        async with self.session_factory() as session, session.begin():
            records = (
                await session.execute(
                    select(ReplyOutboxRecord)
                    .where(
                        ReplyOutboxRecord.status.in_(("pending", "failed", "sending")),
                        ReplyOutboxRecord.available_at <= now,
                        ReplyOutboxRecord.attempt_count < ReplyOutboxRecord.max_attempts,
                        or_(
                            ReplyOutboxRecord.lease_expires_at.is_(None),
                            ReplyOutboxRecord.lease_expires_at <= now,
                        ),
                    )
                    .order_by(ReplyOutboxRecord.available_at, ReplyOutboxRecord.created_at)
                    .limit(self.outbox_batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            claimed = []
            for record in records:
                record.status = "sending"
                record.attempt_count += 1
                record.lease_owner = self.owner_id
                record.lease_expires_at = now + timedelta(
                    seconds=min(self.lease_seconds, 60)
                )
                record.updated_at = now
                claimed.append((record.id, record.reply_json))
            return claimed

    async def _complete_outbox(self, record_id: str, response: object | None) -> None:
        now = utc_now()
        async with self.session_factory() as session, session.begin():
            record = await session.get(ReplyOutboxRecord, record_id)
            if record is None or record.lease_owner != self.owner_id:
                return
            record.status = "sent"
            record.platform_message_id = self._platform_message_id(response)
            record.last_error = None
            record.lease_owner = None
            record.lease_expires_at = None
            record.sent_at = now
            record.updated_at = now

    async def _fail_outbox(self, record_id: str, exc: Exception) -> None:
        now = utc_now()
        async with self.session_factory() as session, session.begin():
            record = await session.get(ReplyOutboxRecord, record_id)
            if record is None or record.lease_owner != self.owner_id:
                return
            exhausted = record.attempt_count >= record.max_attempts
            record.status = "dead" if exhausted else "failed"
            if not exhausted:
                delay = min(2 ** record.attempt_count, 300)
                record.available_at = now + timedelta(seconds=delay)
            record.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            record.lease_owner = None
            record.lease_expires_at = None
            record.updated_at = now
            logger.warning(
                "Reply outbox delivery failed: id={} attempt={}/{} error={}",
                record.id,
                record.attempt_count,
                record.max_attempts,
                record.last_error,
            )

    @staticmethod
    def _platform_message_id(response: object | None) -> str | None:
        if not isinstance(response, dict):
            return None
        for candidate in (
            response.get("message_id"),
            response.get("id"),
            (response.get("data") or {}).get("message_id")
            if isinstance(response.get("data"), dict)
            else None,
        ):
            if candidate is not None:
                return str(candidate)[:512]
        return None

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from xbot.core.logging import logger
from xbot.messaging.models import Reply

TaskRunner = Callable[[], Awaitable[Any]]
RepositoryProvider = Callable[[], Any]
ReplySender = Callable[[Reply], Awaitable[None]]
BackgroundTaskSubscriber = Callable[["BackgroundTaskRecord"], Awaitable[None] | None]


class BackgroundTaskRecord(BaseModel):
    id: str
    kind: str
    status: str = "queued"
    source: str = "api"
    description: str = ""
    progress: str = ""
    result: Any | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_storage(cls, record) -> "BackgroundTaskRecord":
        if isinstance(record, cls):
            return record
        result = json.loads(record.result_json) if record.result_json else None
        metadata = json.loads(record.metadata_json or "{}")
        return cls(
            id=record.id,
            kind=record.kind,
            status=record.status,
            source=record.source,
            description=record.description,
            progress=record.progress,
            result=result,
            error=record.error,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            metadata=metadata,
        )


class BackgroundTaskManager:
    def __init__(
        self,
        *,
        repository_provider: RepositoryProvider | None = None,
        send_reply: ReplySender | None = None,
    ) -> None:
        self.repository_provider = repository_provider
        self.send_reply = send_reply
        self._records: dict[str, BackgroundTaskRecord] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._persist_locks: dict[str, asyncio.Lock] = {}
        self._subscribers: set[BackgroundTaskSubscriber] = set()

    def attach_reply_sender(self, send_reply: ReplySender | None) -> None:
        self.send_reply = send_reply

    def subscribe(self, subscriber: BackgroundTaskSubscriber) -> Callable[[], None]:
        self._subscribers.add(subscriber)

        def unsubscribe() -> None:
            self._subscribers.discard(subscriber)

        return unsubscribe

    def start(
        self,
        *,
        kind: str,
        runner: TaskRunner,
        source: str = "api",
        description: str = "",
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
        created_at: datetime | None = None,
    ) -> BackgroundTaskRecord:
        task_id = task_id or str(uuid4())
        record = BackgroundTaskRecord(
            id=task_id,
            kind=kind,
            source=source,
            description=description,
            metadata=metadata or {},
            created_at=created_at or datetime.utcnow(),
        )
        self._records[task_id] = record
        self._persist_later(record)
        self._tasks[task_id] = asyncio.create_task(self._run(task_id, runner), name=f"xbot-bg-{task_id}")
        return record

    def remember(self, record: BackgroundTaskRecord) -> BackgroundTaskRecord:
        self._records[record.id] = record
        return record

    def replay(self, record: BackgroundTaskRecord, runner: TaskRunner) -> BackgroundTaskRecord:
        metadata = dict(record.metadata or {})
        metadata["replayed"] = True
        metadata["replay_count"] = int(metadata.get("replay_count") or 0) + 1
        record.metadata = metadata
        record.status = "queued"
        record.error = None
        record.finished_at = None
        self._records[record.id] = record
        self._persist_later(record)
        self._tasks[record.id] = asyncio.create_task(self._run(record.id, runner), name=f"xbot-bg-replay-{record.id}")
        return record

    def list(self, limit: int = 50) -> list[BackgroundTaskRecord]:
        items = sorted(self._records.values(), key=lambda item: item.created_at, reverse=True)
        return items[: max(1, min(limit, 500))]

    def get(self, task_id: str) -> BackgroundTaskRecord | None:
        return self._records.get(task_id)

    def heartbeat(self, task_id: str, *, progress: str = "") -> BackgroundTaskRecord | None:
        record = self._records.get(task_id)
        if record is None:
            return None
        if progress:
            record.progress = progress
        metadata = dict(record.metadata or {})
        metadata["heartbeat_at"] = datetime.utcnow().isoformat()
        record.metadata = metadata
        self._persist_later(record)
        return record

    def mark_stale(self, record: BackgroundTaskRecord, *, reason: str) -> BackgroundTaskRecord:
        record.status = "stale"
        record.error = reason
        record.finished_at = datetime.utcnow()
        metadata = dict(record.metadata or {})
        metadata["stale_reason"] = reason
        record.metadata = metadata
        self._records[record.id] = record
        self._persist_later(record)
        return record

    def mark_stale_running(self, *, older_than_seconds: int = 14400) -> list[BackgroundTaskRecord]:
        cutoff = datetime.utcnow() - timedelta(seconds=max(1, older_than_seconds))
        stale = []
        for record in list(self._records.values()):
            if record.status != "running":
                continue
            if record.id in self._tasks:
                continue
            last_seen = record.started_at or record.created_at
            heartbeat = (record.metadata or {}).get("heartbeat_at")
            if isinstance(heartbeat, str):
                try:
                    last_seen = max(last_seen, datetime.fromisoformat(heartbeat))
                except ValueError:
                    pass
            if last_seen <= cutoff:
                stale.append(self.mark_stale(record, reason="Background task heartbeat expired."))
        return stale

    async def cancel(self, task_id: str) -> BackgroundTaskRecord | None:
        record = self._records.get(task_id)
        if record is None:
            return None
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        record.status = "cancelled"
        record.finished_at = datetime.utcnow()
        self._persist_later(record)
        await self._publish(record)
        return record

    async def stop(self) -> None:
        task_ids = list(self._tasks)
        for task_id in task_ids:
            task = self._tasks.get(task_id)
            if task and not task.done():
                task.cancel()
        for task in list(self._tasks.values()):
            if not task.done():
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _run(self, task_id: str, runner: TaskRunner) -> None:
        record = self._records[task_id]
        record.status = "running"
        record.started_at = datetime.utcnow()
        self.heartbeat(task_id, progress=record.progress or "started")
        self._persist_later(record)
        try:
            record.result = await runner()
        except asyncio.CancelledError:
            record.status = "cancelled"
            record.finished_at = datetime.utcnow()
            self._persist_later(record)
            raise
        except Exception as exc:
            logger.warning("Background task failed: task_id={} error={}", task_id, exc)
            record.status = "failed"
            record.error = str(exc)
            record.finished_at = datetime.utcnow()
        else:
            record.status = "completed"
            record.finished_at = datetime.utcnow()
        finally:
            self._persist_later(record)
            await self._publish(record)
            await self._notify_if_needed(record)
            self._tasks.pop(task_id, None)

    def _persist_later(self, record: BackgroundTaskRecord) -> None:
        if not self.repository_provider:
            return
        asyncio.create_task(self._persist(record.model_copy(deep=True)), name=f"xbot-bg-persist-{record.id}")

    async def _persist(self, record: BackgroundTaskRecord) -> None:
        lock = self._persist_locks.setdefault(record.id, asyncio.Lock())
        try:
            async with lock:
                async with self.repository_provider() as repo:
                    await repo.upsert_background_task(record)
        except Exception as exc:
            logger.warning("Background task persistence failed: task_id={} error={}", record.id, exc)

    async def _publish(self, record: BackgroundTaskRecord) -> None:
        snapshot = record.model_copy(deep=True)
        for subscriber in list(self._subscribers):
            try:
                result = subscriber(snapshot)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.warning(
                    "Background task subscriber failed: task_id={} status={} error={}",
                    record.id,
                    record.status,
                    exc,
                )

    async def _notify_if_needed(self, record: BackgroundTaskRecord) -> None:
        if record.metadata.get("notify_mode") == "parent_agent":
            return
        notify = record.metadata.get("notify") if isinstance(record.metadata, dict) else None
        if not notify or not self.send_reply:
            return
        content = self._notification_content(record)
        if not content:
            return
        try:
            await self.send_reply(
                Reply(
                    platform=str(notify["platform"]),
                    adapter=str(notify["adapter"]),
                    conversation_id=str(notify["conversation_id"]),
                    type="text",
                    content=content,
                    quote_message_id=notify.get("quote_message_id"),
                )
            )
        except Exception as exc:
            logger.warning("Background task notification failed: task_id={} error={}", record.id, exc)

    def _notification_content(self, record: BackgroundTaskRecord) -> str:
        if record.status == "completed":
            result = self._to_plain_data(record.result)
            if isinstance(result, dict):
                output = result.get("output")
                return self._user_facing_output(output)
            return self._user_facing_output(result)
        if record.status == "failed":
            error = (record.error or "").strip()
            return f"执行失败：{error}" if error else ""
        return ""

    def _to_plain_data(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: self._to_plain_data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_plain_data(item) for item in value]
        return value

    def _user_facing_output(self, output: Any) -> str:
        output = self._to_plain_data(output)
        if isinstance(output, str):
            return output.strip()
        if isinstance(output, dict):
            stdout = output.get("stdout")
            stderr = output.get("stderr")
            if isinstance(stdout, str) and stdout.strip():
                return stdout.strip()
            if isinstance(stderr, str) and stderr.strip():
                return stderr.strip()
            if output.get("timed_out") is True:
                return "执行超时。"
            if output.get("returncode") not in (None, 0):
                return f"执行失败，退出码：{output['returncode']}"
            message = output.get("message") or output.get("text") or output.get("content")
            if isinstance(message, str) and message.strip():
                return message.strip()
            return ""
        if output is None:
            return ""
        if isinstance(output, (list, tuple)):
            if not output:
                return ""
            return json.dumps(output, ensure_ascii=False, default=str)
        return str(output).strip()

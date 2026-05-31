from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.storage.models import (
    AgentBackgroundTaskRecord,
    AgentEventRecord,
    AgentMemoryRecord,
    AgentScheduledJobRecord,
    AgentTaskRecord,
)


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_task(self, task_id: str, source: str, input_text: str) -> None:
        now = datetime.utcnow()
        self.session.add(
            AgentTaskRecord(
                id=task_id,
                status="running",
                source=source,
                input=input_text,
                result=None,
                created_at=now,
                updated_at=now,
            )
        )

    async def finish_task(self, result) -> None:
        record = await self.session.get(AgentTaskRecord, result.task_id)
        if record is None:
            self.session.add(
                AgentTaskRecord(
                    id=result.task_id,
                    status=result.status,
                    source=result.source,
                    input="",
                    result=result.output,
                    created_at=result.created_at,
                    updated_at=datetime.utcnow(),
                )
            )
            return
        record.status = result.status
        record.result = result.output
        record.updated_at = datetime.utcnow()

    async def add_event(self, task_id: str, event_type: str, content: str) -> None:
        self.session.add(
            AgentEventRecord(
                task_id=task_id,
                type=event_type,
                content=content,
                created_at=datetime.utcnow(),
            )
        )

    async def list_events(self, task_id: str | None = None, limit: int = 100) -> list[AgentEventRecord]:
        stmt = select(AgentEventRecord).order_by(AgentEventRecord.created_at.desc()).limit(limit)
        if task_id:
            stmt = stmt.where(AgentEventRecord.task_id == task_id)
        result = await self.session.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def upsert_background_task(self, item) -> None:
        result_json = json.dumps(item.result, ensure_ascii=False, default=str) if item.result is not None else None
        metadata_json = json.dumps(item.metadata or {}, ensure_ascii=False, default=str)
        record = AgentBackgroundTaskRecord(
            id=item.id,
            kind=item.kind,
            status=item.status,
            source=item.source,
            description=item.description,
            progress=item.progress,
            result_json=result_json,
            error=item.error,
            metadata_json=metadata_json,
            created_at=item.created_at,
            started_at=item.started_at,
            finished_at=item.finished_at,
            updated_at=datetime.utcnow(),
        )
        await self.session.merge(record)

    async def get_background_task(self, task_id: str) -> AgentBackgroundTaskRecord | None:
        return await self.session.get(AgentBackgroundTaskRecord, task_id)

    async def list_background_tasks(self, limit: int = 50) -> list[AgentBackgroundTaskRecord]:
        result = await self.session.execute(
            select(AgentBackgroundTaskRecord)
            .order_by(AgentBackgroundTaskRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def upsert_scheduled_job(self, item) -> None:
        metadata_json = json.dumps(item.metadata or {}, ensure_ascii=False, default=str)
        record = AgentScheduledJobRecord(
            id=item.id,
            name=item.name,
            enabled=item.enabled,
            schedule_type=item.schedule_type,
            schedule_expr=item.schedule_expr,
            schedule_display=item.schedule_display,
            timezone=item.timezone,
            input=item.input,
            source=item.source,
            reply_policy=item.reply_policy,
            max_runs=item.max_runs,
            run_count=item.run_count,
            next_run_at=item.next_run_at,
            last_run_at=item.last_run_at,
            last_status=item.last_status,
            last_task_id=item.last_task_id,
            last_error=item.last_error,
            metadata_json=metadata_json,
            created_at=item.created_at,
            updated_at=datetime.utcnow(),
        )
        await self.session.merge(record)

    async def get_scheduled_job(self, job_id: str) -> AgentScheduledJobRecord | None:
        return await self.session.get(AgentScheduledJobRecord, job_id)

    async def list_scheduled_jobs(
        self,
        *,
        include_disabled: bool = False,
        limit: int = 100,
    ) -> list[AgentScheduledJobRecord]:
        stmt = select(AgentScheduledJobRecord).order_by(AgentScheduledJobRecord.created_at.desc()).limit(limit)
        if not include_disabled:
            stmt = stmt.where(AgentScheduledJobRecord.enabled.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_due_scheduled_jobs(
        self,
        *,
        now: datetime,
        limit: int = 20,
    ) -> list[AgentScheduledJobRecord]:
        result = await self.session.execute(
            select(AgentScheduledJobRecord)
            .where(AgentScheduledJobRecord.enabled.is_(True))
            .where(AgentScheduledJobRecord.next_run_at.is_not(None))
            .where(AgentScheduledJobRecord.next_run_at <= now)
            .order_by(AgentScheduledJobRecord.next_run_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_scheduled_job(self, job_id: str) -> bool:
        record = await self.session.get(AgentScheduledJobRecord, job_id)
        if record is None:
            return False
        await self.session.delete(record)
        return True

    async def save_memory(
        self,
        item,
        *,
        scope: str = "global",
        source: str = "agent",
        tags: list[str] | None = None,
        importance: int = 0,
    ) -> None:
        record = AgentMemoryRecord(
            id=item.id,
            scope=scope,
            kind=item.kind,
            source=source,
            content_json=json.dumps({"summary": item.summary}, ensure_ascii=False),
            summary=item.summary,
            tags_json=json.dumps(tags or [], ensure_ascii=False),
            importance=importance,
            created_at=item.created_at,
            updated_at=datetime.utcnow(),
        )
        await self.session.merge(record)

    async def list_memories(self, limit: int = 50) -> list[AgentMemoryRecord]:
        result = await self.session.execute(
            select(AgentMemoryRecord).order_by(AgentMemoryRecord.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

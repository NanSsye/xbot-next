from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.storage.models import AgentEventRecord, AgentMemoryRecord, AgentTaskRecord


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

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from xbot.core.timeutils import utc_now
from xbot.storage.models import AdapterStateRecord


class AdapterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_state(self, adapter: str) -> dict:
        record = await self.session.get(AdapterStateRecord, adapter)
        if not record:
            return {}
        return json.loads(record.state_json or "{}")

    async def set_state(self, adapter: str, state: dict) -> None:
        record = AdapterStateRecord(
            adapter=adapter,
            state_json=json.dumps(state, ensure_ascii=False, default=str),
            updated_at=utc_now(),
        )
        await self.session.merge(record)

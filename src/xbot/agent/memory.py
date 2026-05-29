from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass(slots=True)
class MemoryItem:
    id: str
    kind: str
    summary: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class MemoryStore:
    def __init__(self) -> None:
        self._items: list[MemoryItem] = []

    async def add(self, kind: str, summary: str) -> MemoryItem:
        item = MemoryItem(id=str(uuid4()), kind=kind, summary=summary)
        self._items.append(item)
        return item

    async def recent(self, limit: int = 20) -> list[MemoryItem]:
        return self._items[-limit:]

    async def list(self, limit: int = 50) -> list[MemoryItem]:
        return self._items[-limit:]

    async def delete(self, memory_id: str) -> bool:
        before = len(self._items)
        self._items = [item for item in self._items if item.id != memory_id]
        return len(self._items) != before

    async def compact(self) -> MemoryItem:
        summaries = [item.summary for item in self._items[-20:]]
        summary = "\n".join(summaries)[:1000] if summaries else "No memories to compact."
        return await self.add("semantic", summary)

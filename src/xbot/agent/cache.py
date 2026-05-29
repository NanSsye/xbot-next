from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any


def stable_cache_key(parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CacheEntry:
    value: Any
    expires_at: datetime


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = max(0, ttl_seconds)
        self._items: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= datetime.now(timezone.utc):
            self._items.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        self._items[key] = CacheEntry(
            value=value,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
        )

    def clear(self) -> None:
        self._items.clear()

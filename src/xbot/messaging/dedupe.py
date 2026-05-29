from __future__ import annotations

from collections import OrderedDict


class DedupeService:
    def __init__(self, max_keys: int = 10000) -> None:
        self.max_keys = max_keys
        self._seen: OrderedDict[str, None] = OrderedDict()

    async def is_duplicate(self, dedupe_key: str) -> bool:
        if dedupe_key in self._seen:
            self._seen.move_to_end(dedupe_key)
            return True
        self._seen[dedupe_key] = None
        if len(self._seen) > self.max_keys:
            self._seen.popitem(last=False)
        return False


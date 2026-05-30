from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4

ENTRY_DELIMITER = "\n§\n"
MEMORY_TEMPLATE = """<!--
xbot long-term memory.

Write compact, durable facts here. Separate entries with a line containing only:
§

Good entries:
- Project convention: ...
- Runtime fact: ...
- Tool quirk: ...

Do not store secrets, temporary task progress, or raw logs.
-->
"""
USER_TEMPLATE = """<!--
xbot user profile memory.

Write stable user preferences, corrections, and workflow habits here. Separate entries with a line containing only:
§

Good entries:
- 用户偏好：...
- 用户纠正：...
- 沟通风格：...

Do not store secrets or temporary task progress.
-->
"""


@dataclass(slots=True)
class MemoryItem:
    id: str
    kind: str
    summary: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class MemoryStore:
    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        memory_char_limit: int = 2200,
        user_char_limit: int = 1375,
    ) -> None:
        self._items: list[MemoryItem] = []
        self.directory = Path(directory) if directory else None
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self._entries: dict[str, list[str]] = {"memory": [], "user": []}
        self._snapshot: dict[str, str] = {"memory": "", "user": ""}
        if self.directory:
            self.load_from_disk()

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

    def load_from_disk(self) -> None:
        if not self.directory:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._ensure_template_files()
        self._entries["memory"] = self._read_entries(self._path_for("memory"))
        self._entries["user"] = self._read_entries(self._path_for("user"))
        self._snapshot = {
            "memory": self._render_block("memory", self._entries["memory"]),
            "user": self._render_block("user", self._entries["user"]),
        }

    def format_for_system_prompt(self) -> str:
        blocks = [self._snapshot.get("user", ""), self._snapshot.get("memory", "")]
        return "\n\n".join(block for block in blocks if block)

    def read_curated(self, target: str = "memory") -> dict:
        target = self._normalize_target(target)
        entries = list(self._entries[target])
        return self._result(target, entries=entries)

    def add_curated(self, target: str, content: str) -> dict:
        target = self._normalize_target(target)
        content = content.strip()
        if not content:
            return {"success": False, "error": "content cannot be empty"}
        if self._blocked_content(content):
            return {"success": False, "error": "memory content looks like a secret or prompt injection"}
        entries = self._reload_live(target)
        if content in entries:
            return self._result(target, message="entry already exists")
        next_entries = entries + [content]
        limit = self._limit(target)
        if len(ENTRY_DELIMITER.join(next_entries)) > limit:
            return {
                "success": False,
                "error": f"{target} memory would exceed {limit} chars; replace or remove entries first",
                "usage": self._usage(target, entries),
                "entries": entries,
            }
        self._entries[target] = next_entries
        self._write_entries(target)
        return self._result(target, message="entry added")

    def replace_curated(self, target: str, old_text: str, content: str) -> dict:
        target = self._normalize_target(target)
        old_text = old_text.strip()
        content = content.strip()
        if not old_text or not content:
            return {"success": False, "error": "old_text and content are required"}
        if self._blocked_content(content):
            return {"success": False, "error": "memory content looks like a secret or prompt injection"}
        entries = self._reload_live(target)
        matches = [idx for idx, entry in enumerate(entries) if old_text in entry]
        if not matches:
            return {"success": False, "error": f"no entry matched {old_text!r}", "entries": entries}
        if len(matches) > 1:
            return {"success": False, "error": f"multiple entries matched {old_text!r}; be more specific"}
        next_entries = list(entries)
        next_entries[matches[0]] = content
        limit = self._limit(target)
        if len(ENTRY_DELIMITER.join(next_entries)) > limit:
            return {"success": False, "error": f"{target} memory would exceed {limit} chars"}
        self._entries[target] = next_entries
        self._write_entries(target)
        return self._result(target, message="entry replaced")

    def remove_curated(self, target: str, old_text: str) -> dict:
        target = self._normalize_target(target)
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text is required"}
        entries = self._reload_live(target)
        matches = [idx for idx, entry in enumerate(entries) if old_text in entry]
        if not matches:
            return {"success": False, "error": f"no entry matched {old_text!r}", "entries": entries}
        if len(matches) > 1:
            return {"success": False, "error": f"multiple entries matched {old_text!r}; be more specific"}
        next_entries = [entry for idx, entry in enumerate(entries) if idx != matches[0]]
        self._entries[target] = next_entries
        self._write_entries(target)
        return self._result(target, message="entry removed")

    def _normalize_target(self, target: str) -> str:
        if target not in {"memory", "user"}:
            raise ValueError("target must be 'memory' or 'user'")
        return target

    def _path_for(self, target: str) -> Path:
        if not self.directory:
            raise RuntimeError("curated memory directory is not configured")
        return self.directory / ("USER.md" if target == "user" else "MEMORY.md")

    def _limit(self, target: str) -> int:
        return self.user_char_limit if target == "user" else self.memory_char_limit

    def _reload_live(self, target: str) -> list[str]:
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._entries[target] = self._read_entries(self._path_for(target))
        return list(self._entries[target])

    def _write_entries(self, target: str) -> None:
        if not self.directory:
            return
        path = self._path_for(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ENTRY_DELIMITER.join(self._entries[target]), encoding="utf-8")

    def _read_entries(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
        return [entry.strip() for entry in raw.split(ENTRY_DELIMITER) if entry.strip()]

    def _ensure_template_files(self) -> None:
        for target, template in {"memory": MEMORY_TEMPLATE, "user": USER_TEMPLATE}.items():
            path = self._path_for(target)
            if not path.exists():
                path.write_text(template, encoding="utf-8")

    def _render_block(self, target: str, entries: list[str]) -> str:
        if not entries:
            return ""
        title = "USER PROFILE" if target == "user" else "MEMORY"
        return f"{title} [{self._usage(target, entries)}]\n" + ENTRY_DELIMITER.join(entries)

    def _usage(self, target: str, entries: list[str]) -> str:
        used = len(ENTRY_DELIMITER.join(entries)) if entries else 0
        limit = self._limit(target)
        percent = min(100, round((used / limit) * 100)) if limit > 0 else 0
        return f"{percent}% - {used}/{limit} chars"

    def _result(self, target: str, *, entries: list[str] | None = None, message: str = "") -> dict:
        entries = list(self._entries[target] if entries is None else entries)
        result = {
            "success": True,
            "target": target,
            "entries": entries,
            "entry_count": len(entries),
            "usage": self._usage(target, entries),
        }
        if message:
            result["message"] = message
        return result

    def _blocked_content(self, content: str) -> bool:
        lowered = content.lower()
        blocked = ("password", "api_key", "private_key", "secret", "ignore previous", "system prompt")
        return any(pattern in lowered for pattern in blocked)

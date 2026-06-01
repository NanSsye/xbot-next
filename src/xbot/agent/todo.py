from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


VALID_TODO_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


@dataclass
class TodoStore:
    items: list[dict[str, str]] = field(default_factory=list)

    def read(self) -> list[dict[str, str]]:
        return [item.copy() for item in self.items]

    def write(self, todos: list[dict[str, Any]], *, merge: bool = False) -> list[dict[str, str]]:
        normalized = [self._normalize(item) for item in self._dedupe(todos)]
        if not merge:
            self.items = normalized
            return self.read()

        by_id = {item["id"]: item.copy() for item in self.items}
        order = [item["id"] for item in self.items]
        for item in normalized:
            item_id = item["id"]
            if item_id not in by_id:
                order.append(item_id)
                by_id[item_id] = item
                continue
            by_id[item_id].update(
                {
                    key: value
                    for key, value in item.items()
                    if value and key in {"content", "status"}
                }
            )
        self.items = [by_id[item_id] for item_id in order if item_id in by_id]
        return self.read()

    def format_active(self) -> str:
        active = [item for item in self.items if item["status"] in {"pending", "in_progress"}]
        if not active:
            return ""
        markers = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "cancelled": "[~]"}
        lines = ["Active task list preserved for this session:"]
        for item in active:
            lines.append(
                f"- {markers.get(item['status'], '[?]')} {item['id']}: {item['content']} ({item['status']})"
            )
        return "\n".join(lines)

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, str]:
        item_id = str(item.get("id") or "").strip() or "?"
        content = str(item.get("content") or "").strip() or "(no description)"
        status = str(item.get("status") or "pending").strip().lower()
        if status not in VALID_TODO_STATUSES:
            status = "pending"
        return {"id": item_id, "content": content, "status": status}

    @staticmethod
    def _dedupe(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last_index: dict[str, int] = {}
        for index, item in enumerate(todos):
            item_id = str(item.get("id") or "").strip() or "?"
            last_index[item_id] = index
        return [todos[index] for index in sorted(last_index.values())]


class TodoManager:
    def __init__(self, path: str | Path | None = None) -> None:
        self._stores: dict[str, TodoStore] = {}
        self.path = Path(path) if path else None
        self._loaded = False

    def store_for(self, key: str) -> TodoStore:
        self._load_once()
        normalized = key.strip() or "global"
        return self._stores.setdefault(normalized, TodoStore())

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = str(payload.get("_session_key") or payload.get("session") or "global")
        store = self.store_for(key)
        todos = payload.get("todos")
        if todos is not None:
            if not isinstance(todos, list):
                raise ValueError("todo payload field 'todos' must be an array.")
            items = store.write(todos, merge=bool(payload.get("merge", False)))
            self._save()
        else:
            items = store.read()
        return {"todos": items, "summary": self._summary(items)}

    def active_prompt(self, key: str) -> str:
        return self.store_for(key).format_active()

    def has_active(self, key: str) -> bool:
        store = self.store_for(key)
        return any(item["status"] in {"pending", "in_progress"} for item in store.read())

    def _load_once(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for key, items in raw.items():
            if isinstance(items, list):
                self._stores[str(key)] = TodoStore([TodoStore._normalize(item) for item in items if isinstance(item, dict)])

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: store.read() for key, store in self._stores.items()}
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _summary(items: list[dict[str, str]]) -> dict[str, int]:
        return {
            "total": len(items),
            "pending": sum(1 for item in items if item["status"] == "pending"),
            "in_progress": sum(1 for item in items if item["status"] == "in_progress"),
            "completed": sum(1 for item in items if item["status"] == "completed"),
            "cancelled": sum(1 for item in items if item["status"] == "cancelled"),
        }

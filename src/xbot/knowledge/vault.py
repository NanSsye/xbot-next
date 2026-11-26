from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath

VAULT_FOLDERS = (
    "01-主题",
    "03-产品与项目",
    "04-问题与解决方案",
    "05-重要决策",
    "06-文件摘要",
    "90-系统",
    "assets",
)


def conversation_key(conversation_id: str) -> str:
    return hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:24]


def slugify(value: str, *, fallback: str = "未命名") -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "-", str(value or "").strip())
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return (value[:80] or fallback).strip()


class GroupVault:
    def __init__(self, root: Path, conversation_id: str) -> None:
        self.root = root.resolve()
        self.conversation_id = conversation_id
        self.group_root = (self.root / conversation_key(conversation_id)).resolve()
        self.raw_root = self.group_root / "raw"
        self.vault_root = self.group_root / "vault"

    def ensure(self) -> None:
        for path in (
            self.raw_root / "messages",
            self.raw_root / "files",
            self.raw_root / "extracts",
            *(self.vault_root / folder for folder in VAULT_FOLDERS),
        ):
            path.mkdir(parents=True, exist_ok=True)

    def resolve_vault_path(self, relative_path: str) -> Path:
        pure = PurePosixPath(str(relative_path or "").replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("invalid vault path")
        if pure.suffix.lower() != ".md":
            raise ValueError("knowledge pages must be Markdown files")
        target = (self.vault_root / Path(*pure.parts)).resolve()
        if not target.is_relative_to(self.vault_root):
            raise ValueError("vault path escapes the current group")
        current = target.parent
        while current != self.vault_root:
            if current.exists() and current.is_symlink():
                raise ValueError("symbolic links are not allowed in the vault")
            current = current.parent
        return target

    def read(self, relative_path: str, *, max_chars: int = 200_000) -> str:
        target = self.resolve_vault_path(relative_path)
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(relative_path)
        return target.read_text(encoding="utf-8")[:max_chars]

    def write_atomic(self, relative_path: str, content: str) -> str:
        target = self.resolve_vault_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        if len(encoded) > 2_000_000:
            raise ValueError("knowledge page exceeds 2 MB")
        fd, temp_name = tempfile.mkstemp(prefix=".xbot-wiki-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return hashlib.sha256(encoded).hexdigest()


def render_page(
    *,
    title: str,
    page_type: str,
    conversation_id: str,
    summary: str,
    tags: list[str],
    sources: list[str],
    body: str,
    updated_at: datetime,
    aliases: list[str] | None = None,
) -> str:
    frontmatter = [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"type: {json.dumps(page_type, ensure_ascii=False)}",
        f"conversation_id: {json.dumps(conversation_id, ensure_ascii=False)}",
        f"summary: {json.dumps(summary[:1000], ensure_ascii=False)}",
        f"tags: {json.dumps(tags[:20], ensure_ascii=False)}",
        f"aliases: {json.dumps((aliases or [])[:20], ensure_ascii=False)}",
        f"sources: {json.dumps(sources[:500], ensure_ascii=False)}",
        f"updated_at: {json.dumps(updated_at.isoformat(), ensure_ascii=False)}",
        "---",
    ]
    clean_body = str(body or "").strip()
    return "\n".join([*frontmatter, "", f"# {title}", "", clean_body, ""])

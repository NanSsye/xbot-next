"""Telegram tools backed by the current xbot Telegram adapter."""

from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SEND_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xbot_telegram_send_context", default=None
)


def set_send_context(context: dict[str, Any]):
    return _SEND_CONTEXT.set(context)


def reset_send_context(token) -> None:
    _SEND_CONTEXT.reset(token)


def _context() -> dict[str, Any]:
    context = _SEND_CONTEXT.get()
    if not context:
        raise RuntimeError("Telegram send context is unavailable")
    return context


def _target(args: dict[str, Any], context: dict[str, Any]) -> str:
    requested = str(args.get("to") or args.get("conversation_id") or "").strip()
    current = str(context.get("conversation_id") or "").strip()
    if str(context.get("profile") or "guest") != "admin" and requested and requested != current:
        raise PermissionError("Telegram guest/member 只能发送到当前会话")
    return requested or current


def _media_source(args: dict[str, Any], context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    source = str(args.get("url") or args.get("path") or "").strip()
    if not source:
        raise ValueError("url or path is required")
    metadata: dict[str, Any] = {"file_name": str(args.get("file_name") or "")}
    if source.startswith(("http://", "https://")):
        if not urlparse(source).hostname:
            raise ValueError("URL 必须是有效的 http(s) 地址")
        metadata["url"] = source
        return source, metadata
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError("媒体本地路径不存在或不是文件")
    if str(context.get("profile") or "guest") != "admin":
        roots = [Path(item).expanduser().resolve() for item in context.get("media_roots", []) if str(item).strip()]
        if not roots or not any(path == root or root in path.parents for root in roots):
            raise PermissionError("媒体路径不在 Telegram 允许目录内")
    metadata["path"] = str(path)
    return str(path), metadata


def _send(kind: str, args: dict[str, Any]) -> str:
    context = _context()
    target = _target(args, context)
    if kind == "text":
        content = str(args.get("text") or "").strip()
        metadata: dict[str, Any] = {}
        if not content:
            raise ValueError("text must not be empty")
    else:
        content, metadata = _media_source(args, context)
        if caption := str(args.get("caption") or "").strip():
            metadata["caption"] = caption
    sender: Callable[..., Any] = context["sender"]
    future = asyncio.run_coroutine_threadsafe(
        sender(
            platform="telegram",
            adapter="telegram",
            conversation_id=target,
            message_type=kind,
            content=content,
            metadata={**metadata, "quote_message_id": context.get("message_id")},
        ),
        context["loop"],
    )
    if future.result(timeout=120) is None:
        raise RuntimeError("Telegram message was rejected by the adapter")
    if marker := context.get("mark_proactive_send"):
        marker()
    return json.dumps({"success": True, "conversation_id": target, "type": kind}, ensure_ascii=False)


def send_text(args: dict[str, Any], **_: Any) -> str:
    return _send("text", args)


def send_image(args: dict[str, Any], **_: Any) -> str:
    return _send("image", args)


def send_file(args: dict[str, Any], **_: Any) -> str:
    return _send("file", args)


def send_voice(args: dict[str, Any], **_: Any) -> str:
    return _send("voice", args)


def send_video(args: dict[str, Any], **_: Any) -> str:
    return _send("video", args)


def _schema(name: str, kind: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "to": {"type": "string", "description": "Optional Telegram conversation id; defaults to current."},
    }
    if kind == "text":
        properties["text"] = {"type": "string", "minLength": 1}
        required = ["text"]
    else:
        properties.update({"url": {"type": "string"}, "path": {"type": "string"}, "caption": {"type": "string"}, "file_name": {"type": "string"}})
        required = []
    return {"name": name, "description": f"Send Telegram {kind} through xbot.", "parameters": {"type": "object", "properties": properties, "required": required}}


def register_xbot_telegram_tools() -> None:
    from tools.registry import registry

    for name, kind, handler in (
        ("telegram_send_text", "text", send_text),
        ("telegram_send_image", "image", send_image),
        ("telegram_send_file", "file", send_file),
        ("telegram_send_voice", "voice", send_voice),
        ("telegram_send_video", "video", send_video),
    ):
        schema = _schema(name, kind)
        registry.register(name=name, toolset="telegram", schema=schema, handler=handler, description=schema["description"], override=registry.get_entry(name) is not None)

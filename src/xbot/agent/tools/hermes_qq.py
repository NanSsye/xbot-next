"""QQ Bot v2 tools registered in the embedded Hermes runtime.

The tools intentionally delegate all network work to the current xbot QQ
adapter.  They do not accept arbitrary OpenIDs for guest/member turns and do
not parse message identifiers from prompt text; runtime context carries the
triggering conversation and message reference explicitly.
"""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SEND_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "xbot_qq_send_context", default=None
)


def set_send_context(context: dict[str, Any]):
    return _SEND_CONTEXT.set(context)


def reset_send_context(token) -> None:
    _SEND_CONTEXT.reset(token)


def _context() -> dict[str, Any]:
    context = _SEND_CONTEXT.get()
    if not context:
        raise RuntimeError("QQ send context is unavailable")
    return context


def _target(args: dict[str, Any], context: dict[str, Any]) -> str:
    requested = str(args.get("to") or args.get("conversation_id") or "").strip()
    current = str(context.get("conversation_id") or "").strip()
    profile = str(context.get("profile") or "guest")
    if profile != "admin" and requested and requested != current:
        raise PermissionError("QQ guest/member 只能发送到当前会话")
    return requested or current


def _safe_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL 必须是 http(s)")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("不允许访问 localhost/内网主机")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_unspecified or addr.is_multicast):
        raise ValueError("不允许访问私网 URL")
    if addr is None:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError:
            infos = []
        for info in infos:
            try:
                resolved = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if resolved.is_private or resolved.is_loopback or resolved.is_link_local or resolved.is_reserved or resolved.is_unspecified or resolved.is_multicast:
                raise ValueError("URL 解析到私网地址")
    return parsed.geturl()


def _safe_path(value: str, context: dict[str, Any]) -> str:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError("媒体本地路径不存在或不是文件")
    if str(context.get("profile") or "guest") != "admin":
        roots = [Path(item).expanduser().resolve() for item in context.get("media_roots", []) if str(item).strip()]
        if not roots:
            raise PermissionError("当前 QQ 权限未配置媒体目录")
        if not any(path == root or root in path.parents for root in roots):
            raise PermissionError("媒体路径不在当前 QQ 权限允许的目录内")
    return str(path)


def _call_sender(context: dict[str, Any], *, target: str, kind: str, content: str = "", metadata: dict[str, Any] | None = None) -> str:
    sender: Callable[..., Any] = context["sender"]
    if (
        target == context.get("conversation_id")
        and context.get("scope") == "group"
        and context.get("event_id")
    ):
        if kind == "text":
            nickname = str(context.get("sender_name") or "").strip()
            if nickname and not content.lstrip().startswith(f"@{nickname}"):
                content = f"@{nickname} {content}"
        elif kind == "markdown":
            sender_id = str(context.get("sender_id") or "").strip()
            if sender_id and not content.lstrip().startswith(f"<@{sender_id}>"):
                content = f"<@{sender_id}>\n\n{content}"
                if isinstance(metadata, dict) and metadata.get("markdown"):
                    metadata = {**metadata, "markdown": content}
    outgoing_metadata = {**(metadata or {}), "quote_message_id": context.get("message_id")}
    if context.get("event_id"):
        outgoing_metadata["event_id"] = context["event_id"]
        outgoing_metadata["quote_message_id"] = None
    outgoing_metadata["current_conversation_id"] = context.get("conversation_id")
    payload = {
        "platform": "qq", "adapter": context.get("adapter", "qq"),
        "conversation_id": target, "message_type": kind, "content": content,
        "metadata": outgoing_metadata,
    }
    future = asyncio.run_coroutine_threadsafe(sender(**payload), context["loop"])
    result = future.result(timeout=120)
    if result is None:
        raise RuntimeError("QQ message was rejected by the adapter")
    marker = context.get("mark_proactive_send")
    if marker:
        marker()
    response: dict[str, Any] = {"success": True, "conversation_id": target, "type": kind}
    if isinstance(result, dict):
        ids = result.get("message_ids")
        message_id = result.get("message_id") or result.get("id")
        if isinstance(ids, list):
            safe_ids = [str(item) for item in ids if item]
            if safe_ids:
                response["message_ids"] = safe_ids
        if message_id:
            response["message_id"] = str(message_id)
    return json.dumps(response, ensure_ascii=False)


def send_text(args: dict[str, Any], **_: Any) -> str:
    context = _context()
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("text must not be empty")
    return _call_sender(context, target=_target(args, context), kind="text", content=text)


def send_markdown(args: dict[str, Any], **_: Any) -> str:
    context = _context()
    text = str(args.get("content") or args.get("text") or "")
    if not text:
        raise ValueError("markdown content is required")
    return _call_sender(context, target=_target(args, context), kind="markdown", content=text, metadata={"markdown": args.get("markdown") or text, "keyboard": args.get("keyboard")})


def _send_media(args: dict[str, Any], kind: str) -> str:
    context = _context()
    source = str(args.get("url") or args.get("path") or "").strip()
    if not source:
        raise ValueError("url or path is required")
    metadata: dict[str, Any] = {"file_name": str(args.get("file_name") or "")}
    if source.startswith(("http://", "https://")):
        metadata["url"] = _safe_url(source)
    else:
        metadata["path"] = _safe_path(source, context)
    return _call_sender(context, target=_target(args, context), kind=kind, content=source, metadata=metadata)


def send_image(args: dict[str, Any], **_: Any) -> str:
    return _send_media(args, "image")


def send_file(args: dict[str, Any], **_: Any) -> str:
    return _send_media(args, "file")


def send_voice(args: dict[str, Any], **_: Any) -> str:
    return _send_media(args, "voice")


def send_video(args: dict[str, Any], **_: Any) -> str:
    return _send_media(args, "video")


def send_stream(args: dict[str, Any], **_: Any) -> str:
    context = _context()
    target = _target(args, context)
    if not target.startswith("qq:c2c:"):
        raise ValueError("QQ 流式消息仅支持单聊")
    content = str(args.get("content") or "")
    if not content:
        raise ValueError("stream content is required")
    metadata = {
        key: args[key] for key in ("input_mode", "input_state", "state", "index", "content_type", "stream_msg_id") if key in args
    }
    return _call_sender(context, target=target, kind="stream", content=content, metadata=metadata)


def send_input_notify(args: dict[str, Any], **_: Any) -> str:
    context = _context()
    target = _target(args, context)
    if not target.startswith("qq:c2c:"):
        raise ValueError("QQ 输入中状态仅支持 C2C 单聊")
    seconds = int(args.get("input_second") or 5)
    if seconds < 1 or seconds > 60:
        raise ValueError("input_second must be 1..60")
    return _call_sender(context, target=target, kind="input_notify", metadata={"input_second": seconds})


def recall(args: dict[str, Any], **_: Any) -> str:
    context = _context()
    callback = context.get("recall")
    if callback is None:
        raise RuntimeError("QQ recall context is unavailable")
    message_id = str(args.get("message_id") or "").strip()
    if not message_id:
        raise ValueError("message_id must not be empty")
    future = asyncio.run_coroutine_threadsafe(callback(_target(args, context), message_id), context["loop"])
    future.result(timeout=120)
    return json.dumps({"success": True, "type": "recall"}, ensure_ascii=False)


def react(args: dict[str, Any], **_: Any) -> str:
    context = _context()
    callback = context.get("react")
    if callback is None:
        raise RuntimeError("QQ reaction context is unavailable")
    message_id = str(args.get("message_id") or "").strip()
    reaction_id = str(args.get("reaction_id") or "").strip()
    if not message_id or not reaction_id:
        raise ValueError("message_id and reaction_id must not be empty")
    method = str(args.get("method") or "PUT").upper()
    reaction_type = str(args.get("reaction_type") or "emoji").strip()
    if method not in {"PUT", "DELETE"}:
        raise ValueError("method must be PUT or DELETE")
    if reaction_type not in {"1", "2", "system", "system_emoji", "emoji"}:
        raise ValueError("reaction_type must be 1 (system emoji) or 2 (emoji)")
    future = asyncio.run_coroutine_threadsafe(
        callback(
            _target(args, context), message_id=message_id,
            reaction_type=reaction_type, reaction_id=reaction_id, method=method,
        ), context["loop"],
    )
    future.result(timeout=120)
    return json.dumps({"success": True, "type": "reaction"}, ensure_ascii=False)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


def register_xbot_qq_tools() -> None:
    from tools.registry import registry

    # Remove the previously shipped card tool when Hermes is hot-reloaded;
    # QQ's currently verified bot contract does not expose this capability.
    deregister = getattr(registry, "deregister", None)
    if deregister is not None:
        deregister("qq_send_card")
    target = {"to": {"type": "string", "description": "Optional qq conversation id; defaults to current conversation."}}
    definitions = [
        ("qq_send_text", _schema("qq_send_text", "Send QQ text.", {**target, "text": {"type": "string", "minLength": 1}}, ["text"]), send_text),
        ("qq_send_markdown", _schema("qq_send_markdown", "Send QQ Markdown and optional keyboard.", {**target, "content": {"type": "string", "minLength": 1}, "keyboard": {"type": "object"}}, ["content"]), send_markdown),
        ("qq_send_image", _schema("qq_send_image", "Send a QQ image from a public URL or allowed local path.", {**target, "url": {"type": "string", "minLength": 1}, "path": {"type": "string", "minLength": 1}, "file_name": {"type": "string"}}, []), send_image),
        ("qq_send_file", _schema("qq_send_file", "Send a QQ file from a public URL or allowed local path.", {**target, "url": {"type": "string", "minLength": 1}, "path": {"type": "string", "minLength": 1}}, []), send_file),
        ("qq_send_voice", _schema("qq_send_voice", "Send QQ voice.", {**target, "url": {"type": "string", "minLength": 1}, "path": {"type": "string", "minLength": 1}}, []), send_voice),
        ("qq_send_video", _schema("qq_send_video", "Send QQ video.", {**target, "url": {"type": "string", "minLength": 1}, "path": {"type": "string", "minLength": 1}}, []), send_video),
        ("qq_send_stream", _schema("qq_send_stream", "Append/replace a QQ C2C stream message.", {**target, "content": {"type": "string", "minLength": 1}, "input_mode": {"type": "string", "enum": ["append", "replace"]}, "input_state": {"type": "integer", "enum": [1, 10]}, "index": {"type": "integer"}, "content_type": {"type": "string", "enum": ["text", "markdown"]}, "stream_msg_id": {"type": "string"}}, ["content"]), send_stream),
        ("qq_input_notify", _schema("qq_input_notify", "Show QQ C2C input status.", {**target, "input_second": {"type": "integer", "minimum": 1, "maximum": 60}}, []), send_input_notify),
        ("qq_recall", _schema("qq_recall", "Recall a QQ message sent by this adapter.", {"message_id": {"type": "string", "minLength": 1}}, ["message_id"]), recall),
        ("qq_react", _schema("qq_react", "Add or remove a QQ channel reaction.", {"message_id": {"type": "string", "minLength": 1}, "reaction_type": {"type": "string", "enum": ["1", "2"]}, "reaction_id": {"type": "string", "minLength": 1}, "method": {"type": "string", "enum": ["PUT", "DELETE"]}}, ["message_id", "reaction_id"]), react),
    ]
    for name, schema, handler in definitions:
        existing = registry.get_entry(name)
        registry.register(
            name=name, toolset="qq", schema=schema, handler=handler,
            description=schema["description"], override=existing is not None,
        )

from __future__ import annotations

import base64
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from xbot.core.logging import logger
from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext


class OpenClawBridgePlugin(PluginBase):
    name = "OpenClawBridge"
    version = "0.2.0"

    def __init__(self) -> None:
        self._processed: dict[str, float] = {}
        self._recent_media: dict[str, float] = {}
        self._message_expiry_seconds = 90
        self._ctx: PluginContext | None = None

    async def on_load(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        cfg = self._config(ctx)
        logger.info(
            "OpenClawBridge loaded: ws_url={} bridge_url={} trigger_words={}",
            cfg.get("ws_url") or cfg.get("bridge_url") or "",
            cfg.get("bridge_url") or cfg.get("ws_url") or "",
            cfg.get("trigger_words") or cfg.get("trigger_prefixes") or [],
        )

    async def on_message(self, message: Message, ctx: PluginContext):
        cfg = self._config(ctx)
        if not bool(cfg.get("enable", True)):
            return False
        if message.type not in {"text", "image", "file"}:
            return False
        if self._is_self_message(message):
            return True
        if self._is_processed(message):
            return True
        self._mark_processed(message)

        scope = self._scope(message)
        content = (message.content or "").strip()
        triggered = True
        user_text = content
        if scope == "group":
            triggered, user_text = self._match_trigger(content, message, cfg)
            if not triggered and not bool(cfg.get("store_untriggered_group_messages", True)):
                return False
        elif bool(cfg.get("disable_private_chat_at_trigger", False)):
            triggered, user_text = self._match_trigger(content, message, cfg)
            if not triggered:
                return False

        media_items = self._media_payloads(message, cfg)
        quote = self._quote_payload(message, cfg)
        if not user_text and media_items:
            user_text = self._media_prompt(media_items)
        if not user_text and not media_items and not quote:
            return False

        if not self._passes_filters(message, cfg):
            return False
        if triggered and scope == "group" and not self._consume_group_limit(message, cfg):
            await self._send_text(ctx, message.conversation_id, str(cfg.get("limit_reached_message") or "本群今日提问次数已达上限，请明天再来吧"), message)
            return True

        try:
            data = await self._call_bridge(ctx, message, user_text, need_reply=triggered or scope != "group", media_items=media_items, quote=quote)
            await self._handle_bridge_response(ctx, message, data)
        except Exception as exc:
            logger.warning("OpenClawBridge failed: id={} error={}", message.id, exc)
            return False
        return True

    def _config(self, ctx: PluginContext) -> dict[str, Any]:
        raw = dict(ctx.config or {})
        cfg: dict[str, Any] = {}
        for section in ("openclaw", "prompt", "filters", "owner", "limits", "OpenClawBridge", "openclaw_bridge"):
            value = raw.get(section)
            if isinstance(value, dict):
                cfg.update(value)
        cfg.update({k: v for k, v in raw.items() if not isinstance(v, dict)})
        if "trigger_words" in cfg and "trigger_prefixes" not in cfg:
            cfg["trigger_prefixes"] = cfg["trigger_words"]
        if cfg.get("ws_url") and not cfg.get("bridge_url"):
            cfg["bridge_url"] = str(cfg["ws_url"]).replace("ws://", "http://").replace("wss://", "https://").rstrip("/ws")
        return cfg

    async def _call_bridge(self, ctx: PluginContext, message: Message, user_text: str, *, need_reply: bool, media_items: list[dict], quote: dict | None) -> dict[str, Any]:
        cfg = self._config(ctx)
        bridge_url = str(cfg.get("bridge_url") or "").rstrip("/")
        if not bridge_url:
            raise RuntimeError("OpenClaw bridge_url/ws_url is empty")
        endpoint = "reply" if need_reply else "store_message"
        prompt_text = str(cfg.get("text") or "").strip() if bool(cfg.get("enabled", False)) else ""
        payload: dict[str, Any] = {
            "agent_id": str(cfg.get("agent_id") or cfg.get("agent") or "main"),
            "session_id": self._session_id(message, cfg),
            "timeout_seconds": int(cfg.get("timeout_seconds") or 300),
            "scope": self._scope(message),
            "wxid": str(message.raw.get("sender_wxid") or message.sender_id),
            "roomid": str(message.raw.get("group_wxid") or message.conversation_id) if self._scope(message) == "group" else None,
            "text": user_text.strip(),
            "body_for_agent": f"{prompt_text}\n\n{user_text}".strip() if prompt_text else user_text.strip(),
            "msg_id": str(message.raw.get("message_id") or message.raw.get("msg_id") or message.id),
            "sender_name": message.sender_name or message.raw.get("sender_name") or "",
            "need_reply": need_reply,
            "media": media_items,
            "quote": quote,
            "raw": {k: message.raw.get(k) for k in ("msg_type", "MsgType", "mentions_bot", "at_user_list") if k in message.raw},
        }
        if media_items:
            payload["incoming_file"] = media_items[0]
        headers = {}
        if cfg.get("shared_secret"):
            headers["X-OpenClaw-Secret"] = str(cfg["shared_secret"])
        timeout = max(10, int(cfg.get("timeout_seconds") or 300) + 5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{bridge_url}/{endpoint}", json=payload, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"bridge http {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content and resp.headers.get("content-type", "").startswith("application/json") else {"accepted": True}

    async def _handle_bridge_response(self, ctx: PluginContext, message: Message, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or data.get("accepted") is True:
            return
        target = str(data.get("to_wxid") or data.get("to") or message.conversation_id)
        text = str(data.get("text") or data.get("content") or "").strip()
        media_urls: list[str] = []
        for key in ("mediaUrl", "media_url", "url", "path"):
            if data.get(key):
                media_urls.append(str(data[key]))
        for item in data.get("media") or data.get("files") or []:
            if isinstance(item, str):
                media_urls.append(item)
            elif isinstance(item, dict):
                media_urls.append(str(item.get("url") or item.get("path") or item.get("mediaUrl") or ""))
        if text:
            found = re.findall(r"MEDIA:(.+?)(?:\s|$)", text)
            media_urls.extend(x.strip() for x in found if x.strip())
            text = re.sub(r"MEDIA:.+?(?:\s|$)", "", text).strip()
            if text:
                await self._send_text(ctx, target, text, message)
        for media in self._dedupe([x for x in media_urls if x]):
            await self._send_media(ctx, target, media, message)

    async def _send_text(self, ctx: PluginContext, target: str, text: str, message: Message) -> None:
        if ctx.send_reply:
            await ctx.send_reply(Reply(platform=message.platform, adapter=message.adapter, conversation_id=target, type="text", content=text))

    async def _send_media(self, ctx: PluginContext, target: str, media: str, message: Message) -> None:
        path = await self._resolve_media_path(ctx, media)
        if not path:
            await self._send_text(ctx, target, media if media.startswith("http") else f"[文件不存在: {media}]", message)
            return
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rtype = "image" if mime.startswith("image/") else "file"
        if ctx.send_reply:
            await ctx.send_reply(Reply(platform=message.platform, adapter=message.adapter, conversation_id=target, type=rtype, content=str(path)))

    async def _resolve_media_path(self, ctx: PluginContext, media: str) -> Path | None:
        if media.lower().startswith(("http://", "https://")):
            key = media
            now = time.time()
            if key in self._recent_media and now - self._recent_media[key] < 10:
                return None
            self._recent_media[key] = now
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(media)
                resp.raise_for_status()
            name = Path(unquote(urlparse(media).path)).name or f"openclaw_{int(now)}.bin"
            path = ctx.data_dir / "media" / self._safe_filename(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(resp.content)
            return path
        p = Path(os.path.expanduser(media))
        if p.exists():
            return p
        cfg = self._config(ctx)
        bases = [ctx.data_dir, Path(__file__).parent, Path(str(cfg.get("workspace_path") or "")) if cfg.get("workspace_path") else None]
        for base in bases:
            if not base:
                continue
            candidate = (base / media).resolve()
            if candidate.exists():
                return candidate
        return None

    def _media_payloads(self, message: Message, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for att in self._attachments(message, include_quote=False):
            item = self._attachment_payload(att, cfg)
            if item:
                items.append(item)
        return items

    def _quote_payload(self, message: Message, cfg: dict[str, Any]) -> dict[str, Any] | None:
        quote = message.raw.get("quote") if isinstance(message.raw, dict) else None
        if not isinstance(quote, dict) or not quote:
            return None
        payload = {
            "message_id": quote.get("message_id") or quote.get("msg_id"),
            "sender_wxid": quote.get("sender_wxid"),
            "sender_name": quote.get("sender_name"),
            "msg_type": quote.get("msg_type"),
            "content": quote.get("content") or "",
            "media": [],
        }
        for att in self._attachments(message, include_quote=True):
            item = self._attachment_payload(att, cfg)
            if item:
                payload["media"].append(item)
        return payload

    def _attachments(self, message: Message, *, include_quote: bool) -> list[dict[str, Any]]:
        raw = message.raw if isinstance(message.raw, dict) else {}
        source = (raw.get("quote") or {}).get("attachments") if include_quote and isinstance(raw.get("quote"), dict) else raw.get("attachments")
        return [x for x in (source or []) if isinstance(x, dict)]

    def _attachment_payload(self, att: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
        filename = self._safe_filename(str(att.get("filename") or "wechat_file"))
        payload: dict[str, Any] = {
            "kind": att.get("kind") or ("image" if str(att.get("mime") or "").startswith("image/") else "file"),
            "filename": filename,
            "mime_type": str(att.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream"),
            "size": int(att.get("size") or 0),
            "metadata": att.get("metadata") or {},
            "quoted": bool(att.get("quoted")),
        }
        local = str(att.get("local_path") or "")
        if local and Path(local).is_file():
            size = Path(local).stat().st_size
            payload["size"] = size
            if size <= int(cfg.get("media_max_bytes") or 26214400):
                payload["data_base64"] = base64.b64encode(Path(local).read_bytes()).decode("ascii")
            payload["local_path"] = local
        return payload

    def _match_trigger(self, content: str, message: Message, cfg: dict[str, Any]) -> tuple[bool, str]:
        text = content.strip()
        stripped = self._strip_at(text, message)
        if message.raw.get("mentions_bot"):
            return True, stripped
        words = []
        for key in ("trigger_prefix", "trigger_prefixes", "trigger_words", "trigger_keywords"):
            val = cfg.get(key)
            if isinstance(val, str):
                words.append(val)
            elif isinstance(val, list):
                words.extend(str(x) for x in val)
        for word in self._dedupe([w.strip() for w in words if w.strip()]):
            if text.startswith(word):
                return True, text[len(word):].strip()
            if word in text:
                return True, stripped
        return False, stripped

    def _passes_filters(self, message: Message, cfg: dict[str, Any]) -> bool:
        mode = str(cfg.get("filter_mode") or "None").lower()
        sender = str(message.raw.get("sender_wxid") or message.sender_id)
        if mode == "whitelist":
            return sender in {str(x) for x in cfg.get("whitelist") or []}
        if mode == "blacklist":
            return sender not in {str(x) for x in cfg.get("blacklist") or []}
        return True

    def _consume_group_limit(self, message: Message, cfg: dict[str, Any]) -> bool:
        if not bool(cfg.get("enable_group_limit", False)) or self._scope(message) != "group":
            return True
        # 轻量占位：本进程内计数，重启清零。
        day = time.strftime("%Y%m%d")
        room = str(message.raw.get("group_wxid") or message.conversation_id)
        key = f"limit:{day}:{room}"
        count = int(self._processed.get(key, 0)) + 1
        self._processed[key] = float(count)
        custom = cfg.get("custom_groups") if isinstance(cfg.get("custom_groups"), dict) else {}
        limit = int(custom.get(room) or cfg.get("default_group_limit") or 100)
        return count <= limit

    def _scope(self, message: Message) -> str:
        return str(message.raw.get("scope") or ("group" if message.conversation_id.endswith("@chatroom") else "private"))

    def _session_id(self, message: Message, cfg: dict[str, Any]) -> str:
        sender = str(message.raw.get("sender_wxid") or message.sender_id or "")
        if self._scope(message) != "group":
            return f"private:{sender or message.conversation_id}"
        room = str(message.raw.get("group_wxid") or message.conversation_id or "unknown")
        return f"group:{room}" if str(cfg.get("session_mode") or "room_user") == "room" else f"group:{room}:user:{sender or 'unknown'}"

    def _strip_at(self, text: str, message: Message) -> str:
        value = text.strip()
        for c in (message.raw.get("bot_nickname"), message.raw.get("bot_wxid"), "小球子", "OpenClaw"):
            if c:
                value = value.replace(f"@{c}", "").replace(str(c), "").strip()
        if value.startswith("@"):
            parts = value.split(maxsplit=1)
            return parts[1].strip() if len(parts) == 2 else ""
        return value

    def _media_prompt(self, items: list[dict[str, Any]]) -> str:
        lines = ["[用户媒体]"]
        for item in items:
            lines.append(f"- {item.get('kind')}: {item.get('filename')} ({item.get('size') or 'unknown'} bytes)")
        lines.append("[/用户媒体]")
        return "\n".join(lines)

    def _is_processed(self, message: Message) -> bool:
        now = time.time()
        for k, v in list(self._processed.items()):
            if k.startswith("limit:"):
                continue
            if now - v > self._message_expiry_seconds:
                self._processed.pop(k, None)
        return message.id in self._processed

    def _mark_processed(self, message: Message) -> None:
        self._processed[message.id] = time.time()

    def _is_self_message(self, message: Message) -> bool:
        raw = message.raw if isinstance(message.raw, dict) else {}
        senders = {str(message.sender_id or ""), str(raw.get("sender_wxid") or ""), str(raw.get("group_member_wxid") or "")}
        bots = {str(raw.get("bot_wxid") or ""), str(raw.get("self_wxid") or "")}
        senders.discard(""); bots.discard("")
        return bool(senders & bots)

    def _safe_filename(self, filename: str, fallback: str = "file") -> str:
        name = Path(filename or fallback).name
        return (re.sub(r'[\\/*?:"<>|\r\n]+', "_", name).strip(" .") or fallback)[:200]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set(); out: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item); out.append(item)
        return out

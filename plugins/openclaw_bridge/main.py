from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import httpx

from xbot.core.logging import logger
from xbot.messaging.models import Message
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext


class OpenClawBridgePlugin(PluginBase):
    name = "openclaw_bridge"
    version = "0.1.0"

    def __init__(self) -> None:
        self._processed_messages: dict[str, float] = {}
        self._message_expiry_seconds = 60
        self._ctx: PluginContext | None = None

    async def on_load(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        logger.info(
            "OpenClawBridgePlugin loaded: enable={} bridge_url={} agent_id={}",
            bool(self._config(ctx).get("enable", True)),
            self._config(ctx).get("bridge_url", ""),
            self._config(ctx).get("agent_id", "main"),
        )

    async def on_message(self, message: Message, ctx: PluginContext):
        cfg = self._config(ctx)
        if not cfg.get("enable", True):
            return False
        if message.type not in {"text", "image", "file"}:
            return False
        if self._is_self_message(message):
            logger.info(
                "OpenClawBridgePlugin 跳过机器人自身消息: id={} sender={} content={}",
                message.id,
                message.sender_id,
                (message.content or "")[:80],
            )
            return True
        if self._is_message_processed(message):
            return True
        self._mark_processed(message)

        scope = str(message.raw.get("scope") or ("group" if message.conversation_id.endswith("@chatroom") else "private"))
        content = (message.content or "").strip()
        if not content and message.type == "text":
            return False

        if scope == "group":
            triggered, query = self._match_group_trigger(content, message, cfg)
            need_reply = triggered or not bool(cfg.get("group_at_only", True))
            if not need_reply and not bool(cfg.get("store_untriggered_group_messages", True)):
                return False
            user_text = query if triggered else content
        else:
            need_reply = True
            user_text = content

        incoming_file = self._incoming_file_payload(message, cfg)
        if incoming_file and not user_text:
            user_text = self._build_file_prompt(incoming_file)
        if not user_text:
            return False

        try:
            await self._call_bridge(
                ctx,
                message=message,
                user_text=user_text,
                need_reply=need_reply,
                incoming_file=incoming_file,
            )
        except Exception as exc:
            logger.warning("OpenClawBridgePlugin 调用 bridge 失败: id={} error={}", message.id, exc)
            return False

        # OpenClaw 桥的 /reply 是异步接收：返回 {"accepted": true} 后，桥会自己调用微信接口回复。
        # 这里必须标记已处理，避免 xbot 的 agent_chat 再生成一条重复回复。
        return True

    def _config(self, ctx: PluginContext) -> dict[str, Any]:
        return dict(ctx.config or {})

    async def _call_bridge(
        self,
        ctx: PluginContext,
        *,
        message: Message,
        user_text: str,
        need_reply: bool,
        incoming_file: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cfg = self._config(ctx)
        bridge_url = str(cfg.get("bridge_url") or "").rstrip("/")
        if not bridge_url:
            raise RuntimeError("openclaw bridge_url is empty")
        endpoint = "reply" if need_reply else "store_message"
        url = f"{bridge_url}/{endpoint}"
        headers: dict[str, str] = {}
        shared_secret = str(cfg.get("shared_secret") or "")
        if shared_secret:
            headers["X-OpenClaw-Secret"] = shared_secret

        payload = {
            "agent_id": str(cfg.get("agent_id") or "main"),
            "session_id": self._session_id_for(message, cfg),
            "timeout_seconds": int(cfg.get("timeout_seconds") or 300),
            "scope": str(message.raw.get("scope") or "private"),
            "wxid": str(message.raw.get("sender_wxid") or message.sender_id),
            "roomid": str(message.raw.get("group_wxid") or message.conversation_id)
            if str(message.raw.get("scope") or "") == "group"
            else None,
            "text": user_text.strip(),
            "msg_id": str(message.raw.get("message_id") or message.raw.get("msg_id") or message.id),
            "sender_name": message.sender_name or message.raw.get("sender_name") or "",
        }
        if need_reply:
            payload["need_reply"] = True
        if incoming_file:
            payload["incoming_file"] = incoming_file

        timeout = max(5, int(cfg.get("timeout_seconds") or 300) + 5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"bridge http {response.status_code}: {response.text[:300]}")
        data = response.json() if response.content else {}
        return data if isinstance(data, dict) else {"accepted": True}

    def _incoming_file_payload(self, message: Message, cfg: dict[str, Any]) -> dict[str, Any] | None:
        attachment = self._first_attachment(message)
        if not attachment:
            return None
        filename = self._safe_filename(str(attachment.get("filename") or "wechat_file"), fallback="wechat_file")
        payload: dict[str, Any] = {
            "filename": filename,
            "mime_type": str(attachment.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream"),
            "size": int(attachment.get("size") or 0),
        }
        local_path = str(attachment.get("local_path") or "")
        if not local_path:
            return payload
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            return payload
        max_bytes = int(cfg.get("media_max_bytes") or 0)
        size = path.stat().st_size
        payload["size"] = size
        if max_bytes and size > max_bytes:
            return payload
        payload["data_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
        return payload

    def _first_attachment(self, message: Message) -> dict[str, Any] | None:
        raw_attachments = message.raw.get("attachments") if isinstance(message.raw, dict) else None
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if isinstance(item, dict):
                    return item
        quote = message.raw.get("quote") if isinstance(message.raw, dict) else None
        quote_attachments = quote.get("attachments") if isinstance(quote, dict) else None
        if isinstance(quote_attachments, list):
            for item in quote_attachments:
                if isinstance(item, dict):
                    return item
        return None

    def _build_file_prompt(self, incoming_file: dict[str, Any]) -> str:
        filename = str(incoming_file.get("filename") or "wechat_file")
        size = int(incoming_file.get("size") or 0)
        has_data = bool(incoming_file.get("data_base64"))
        return "\n".join(
            [
                "[用户文件]",
                f"文件名: {filename}",
                f"文件大小: {size} 字节" if size else "文件大小: 未知",
                "文件内容: 已上传，可解析处理" if has_data else "文件内容: 当前仅提供元信息",
                "[/用户文件]",
            ]
        )

    def _match_group_trigger(self, content: str, message: Message, cfg: dict[str, Any]) -> tuple[bool, str]:
        text = content.strip()
        mentions_bot = bool(message.raw.get("mentions_bot"))
        stripped = self._strip_at_prefix(text, message)
        if mentions_bot:
            return True, stripped

        prefix_str = str(cfg.get("trigger_prefix") or "").strip()
        prefixes = [prefix_str] if prefix_str else []
        prefixes.extend(str(item).strip() for item in cfg.get("trigger_prefixes") or [] if str(item).strip())
        for prefix in self._dedupe(prefixes):
            if text.startswith(prefix):
                return True, text[len(prefix) :].strip()

        keywords = [str(item).strip() for item in cfg.get("trigger_keywords") or [] if str(item).strip()]
        for keyword in self._dedupe(keywords):
            if keyword in text:
                return True, stripped
        return False, stripped

    def _strip_at_prefix(self, text: str, message: Message) -> str:
        value = text.strip()
        for candidate in (
            message.raw.get("bot_nickname"),
            message.raw.get("bot_wxid"),
            "小小x",
            "OpenClaw",
        ):
            if candidate:
                value = value.replace(f"@{candidate}", "").replace(str(candidate), "").strip()
        if value.startswith("@"):
            parts = value.split(maxsplit=1)
            value = parts[1].strip() if len(parts) == 2 else ""
        return value

    def _session_id_for(self, message: Message, cfg: dict[str, Any]) -> str:
        scope = str(message.raw.get("scope") or "private")
        sender = str(message.raw.get("sender_wxid") or message.sender_id or "")
        if scope != "group":
            return f"private:{sender or message.conversation_id}"
        roomid = str(message.raw.get("group_wxid") or message.conversation_id or "")
        if str(cfg.get("session_mode") or "room_user") == "room":
            return f"group:{roomid or 'unknown'}"
        return f"group:{roomid or 'unknown'}:user:{sender or 'unknown'}"

    def _is_message_processed(self, message: Message) -> bool:
        now = time.time()
        expired = [key for key, seen_at in self._processed_messages.items() if now - seen_at > self._message_expiry_seconds]
        for key in expired:
            self._processed_messages.pop(key, None)
        return message.id in self._processed_messages

    def _mark_processed(self, message: Message) -> None:
        self._processed_messages[message.id] = time.time()

    def _is_self_message(self, message: Message) -> bool:
        raw = message.raw if isinstance(message.raw, dict) else {}
        sender_candidates = {
            str(message.sender_id or ""),
            str(raw.get("sender_wxid") or ""),
            str(raw.get("group_member_wxid") or ""),
            str(raw.get("private_wxid") or ""),
        }
        bot_candidates = {
            str(raw.get("bot_wxid") or ""),
            str(raw.get("self_wxid") or ""),
        }
        sender_candidates.discard("")
        bot_candidates.discard("")
        if sender_candidates.intersection(bot_candidates):
            return True

        sender_name = str(message.sender_name or raw.get("sender_name") or "").strip()
        bot_nickname = str(raw.get("bot_nickname") or "").strip()
        return bool(sender_name and bot_nickname and sender_name == bot_nickname)

    def _safe_filename(self, filename: str, *, ext: str = "", fallback: str = "file") -> str:
        name = Path(filename or fallback).name
        name = re.sub(r'[\\/*?:"<>|\r\n]+', "_", name).strip(" .") or fallback
        if ext and "." not in name:
            name = f"{name}.{ext.lstrip('.')}"
        return name[:200]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

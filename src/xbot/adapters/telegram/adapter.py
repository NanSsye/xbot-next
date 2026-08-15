from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xbot.adapters.base import BaseAdapter
from xbot.adapters.telegram.client import TelegramApiError, TelegramBotClient
from xbot.core.config import TelegramAdapterConfig
from xbot.core.logging import logger
from xbot.messaging.models import Message, MessageEnvelope, Reply
from xbot.messaging.queue import MessageQueue


class TelegramAdapter(BaseAdapter):
    name = "telegram"
    platform = "telegram"

    def __init__(self, config: TelegramAdapterConfig, queue: MessageQueue | None = None, client_factory=None, repository_provider=None) -> None:
        self.config = config
        self.queue = queue
        self.client_factory = client_factory
        self.repository_provider = repository_provider
        self.client: TelegramBotClient | None = None
        self.started = False
        self.bot_id = ""
        self.bot_username = ""
        self.offset: int | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        if not self.config.bot_token.strip():
            logger.warning("TelegramAdapter 已启用但 Bot Token 未配置")
            return
        self.client = self.client or self._create_client()
        if self.queue is not None:
            self._task = asyncio.create_task(self._poll_loop(), name="xbot-telegram-adapter")

    async def stop(self) -> None:
        self.started = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self.client:
            await self.client.close()
            self.client = None

    async def send(self, reply: Reply) -> dict[str, Any] | None:
        target = self._target_from_conversation(reply.conversation_id)
        if target is None:
            logger.warning("TelegramAdapter 找不到回发目标: conversation={}", reply.conversation_id)
            return None
        client = self.client or self._create_client()
        self.client = client
        reply_to = self._telegram_message_id(reply.quote_message_id)
        if reply.type in {"text", "markdown", "keyboard", "card", "link", "embed", "ark"}:
            markup = self._inline_keyboard(reply.metadata) if reply.type in {"keyboard", "card"} else None
            parse_mode = "Markdown" if reply.type == "markdown" else None
            chunks = self._split_text(reply.content, max(1, min(4096, int(self.config.max_reply_chars))))
            result: dict[str, Any] = {}
            ids: list[str] = []
            for index, chunk in enumerate(chunks):
                kwargs = {
                    "chat_id": target,
                    "text": chunk,
                    "reply_to_message_id": reply_to if index == 0 else None,
                    "parse_mode": parse_mode,
                    "reply_markup": markup if index == len(chunks) - 1 else None,
                }
                try:
                    result = await client.send_message(**kwargs)
                except TelegramApiError as exc:
                    if not parse_mode or not self._is_markdown_parse_error(exc):
                        raise
                    logger.warning("Telegram Markdown 解析失败，已降级为纯文本")
                    kwargs["parse_mode"] = None
                    result = await client.send_message(**kwargs)
                if result.get("message_id") is not None:
                    ids.append(str(result["message_id"]))
            return {"message_id": ids[-1] if ids else "", "message_ids": ids}
        media_kind = "audio" if reply.type == "music_card" else reply.type
        if media_kind in {"image", "file", "audio", "voice", "video"}:
            if not self.config.media_enabled:
                raise TelegramApiError("Telegram 媒体能力未启用")
            metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
            source = str(metadata.get("url") or metadata.get("path") or reply.content or "").strip()
            if not source:
                raise TelegramApiError("Telegram 媒体回复缺少 url/path")
            group_sources = [str(item) for item in metadata.get("paths", []) if str(item).strip()]
            if media_kind == "image" and len(group_sources) > 1:
                kwargs = {
                    "chat_id": target,
                    "sources": group_sources[:10],
                    "caption": str(metadata.get("caption") or ""),
                    "parse_mode": str(metadata.get("parse_mode") or "") or None,
                    "reply_to_message_id": reply_to,
                }
                try:
                    results = await client.send_media_group(**kwargs)
                except TelegramApiError as exc:
                    if not kwargs["parse_mode"] or not self._is_markdown_parse_error(exc):
                        raise
                    logger.warning("Telegram 相册说明 Markdown 解析失败，已降级为纯文本")
                    kwargs["parse_mode"] = None
                    results = await client.send_media_group(**kwargs)
                ids = [str(item["message_id"]) for item in results if item.get("message_id") is not None]
                return {"message_id": ids[-1] if ids else "", "message_ids": ids}
            kwargs = {
                "kind": media_kind,
                "chat_id": target,
                "source": source,
                "caption": str(metadata.get("caption") or ""),
                "parse_mode": str(metadata.get("parse_mode") or "") or None,
                "reply_to_message_id": reply_to,
                "file_name": str(metadata.get("file_name") or ""),
            }
            try:
                return await client.send_media(**kwargs)
            except TelegramApiError as exc:
                if not kwargs["parse_mode"] or not self._is_markdown_parse_error(exc):
                    raise
                logger.warning("Telegram 媒体说明 Markdown 解析失败，已降级为纯文本")
                kwargs["parse_mode"] = None
                return await client.send_media(**kwargs)
        raise TelegramApiError(f"不支持的 Telegram Reply 类型: {reply.type}")

    async def normalize(self, raw: dict) -> Message:
        update_id = int(raw.get("update_id") or 0)
        callback = raw.get("callback_query") if isinstance(raw.get("callback_query"), dict) else None
        message = self._update_message(raw)
        if callback:
            message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
            sender = callback.get("from") if isinstance(callback.get("from"), dict) else {}
            content = str(callback.get("data") or "")
            message_type = "event"
        else:
            sender = message.get("from") if isinstance(message.get("from"), dict) else {}
            content = str(message.get("text") or message.get("caption") or "")
            message_type = self._message_type(message)
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "")
        chat_type = str(chat.get("type") or "private")
        scope = "private" if chat_type == "private" else "channel" if chat_type == "channel" else "group"
        telegram_message_id = int(message.get("message_id") or 0)
        attachments = await self._attachments(message, update_id=update_id, quoted=False)
        quote = await self._quote(message.get("reply_to_message"), update_id=update_id)
        sender_id = str(sender.get("id") or chat_id or "unknown_telegram")
        sender_name = self._display_name(sender, chat)
        raw_data = dict(raw)
        raw_data.update({
            "scope": scope,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "telegram_message_id": telegram_message_id,
            "message_id": f"{chat_id}:{telegram_message_id}" if telegram_message_id else f"update:{update_id}",
            "sender_id": sender_id,
            "sender_name": sender_name,
            "user_id": sender_id,
            "bot_id": self.bot_id,
            "bot_username": self.bot_username,
            "mentions_bot": True if callback or scope == "private" else self._mentions_bot(message),
            "attachments": attachments,
        })
        if quote:
            raw_data["quote"] = quote
        if callback:
            raw_data["telegram_callback_query"] = True
            raw_data["callback_query_id"] = str(callback.get("id") or "")
        identity = f"{chat_id}:{telegram_message_id}" if telegram_message_id else f"callback:{callback.get('id') if callback else update_id}"
        timestamp = (
            datetime.fromtimestamp(int(message["date"]), tz=UTC).replace(tzinfo=None)
            if message.get("date")
            else datetime.utcnow()
        )
        return Message(
            id=identity,
            platform=self.platform,
            adapter=self.name,
            type=message_type,
            conversation_id=f"telegram:{scope}:{chat_id}",
            sender_id=sender_id,
            sender_name=sender_name,
            content=content or self._placeholder(message_type),
            raw=raw_data,
            timestamp=timestamp,
        )

    def public_status(self) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "platform": self.platform,
            "started": self.started,
            "configured": bool(self.config.bot_token),
            "polling": bool(self._task and not self._task.done()),
            "bot_id": self.bot_id,
            "bot_username": self.bot_username,
            "offset": self.offset,
            "media_enabled": self.config.media_enabled,
        }

    async def _poll_loop(self) -> None:
        client = self.client or self._create_client()
        self.client = client
        try:
            me = await client.get_me()
            self.bot_id = str(me.get("id") or "")
            self.bot_username = str(me.get("username") or "")
            logger.info("TelegramAdapter 已连接: bot=@{}", self.bot_username or "unknown")
        except TelegramApiError as exc:
            logger.warning("TelegramAdapter 获取机器人信息失败，将继续轮询: {}", exc)
        while self.started:
            try:
                updates = await client.get_updates(offset=self.offset, timeout=int(self.config.polling_timeout_seconds))
                for raw in updates:
                    await self._handle_update(raw)
                    self.offset = int(raw.get("update_id") or 0) + 1
            except asyncio.CancelledError:
                raise
            except TelegramApiError as exc:
                logger.warning("TelegramAdapter 轮询失败，{} 秒后重试: {}", self.config.reconnect_seconds, exc)
                await asyncio.sleep(max(0.1, float(self.config.reconnect_seconds)))
            except Exception as exc:
                logger.warning("TelegramAdapter 处理消息异常，{} 秒后重试: {}", self.config.reconnect_seconds, type(exc).__name__)
                await asyncio.sleep(max(0.1, float(self.config.reconnect_seconds)))

    async def _handle_update(self, raw: dict[str, Any]) -> None:
        callback = raw.get("callback_query") if isinstance(raw.get("callback_query"), dict) else None
        if callback and callback.get("id"):
            with contextlib.suppress(TelegramApiError):
                await (self.client or self._create_client()).answer_callback_query(str(callback["id"]))
        message = await self.normalize(raw)
        if not message.conversation_id.rsplit(":", 1)[-1]:
            return
        if self.queue is None:
            logger.warning("TelegramAdapter 未配置消息队列，消息不会进入框架: {}", message.id)
            return
        logger.info(
            "TelegramAdapter 发布消息到队列: id={} conversation={} sender={} type={}",
            message.id,
            message.conversation_id,
            message.sender_id,
            message.type,
        )
        await self.queue.publish(MessageEnvelope.from_message(message))

    async def _attachments(self, message: dict[str, Any], *, update_id: int, quoted: bool) -> list[dict[str, Any]]:
        candidates: list[tuple[str, dict[str, Any]]] = []
        photos = message.get("photo") if isinstance(message.get("photo"), list) else []
        if photos:
            candidate = max((item for item in photos if isinstance(item, dict)), key=lambda item: int(item.get("file_size") or 0), default=None)
            if candidate:
                candidates.append(("image", candidate))
        for key, kind in (("document", "file"), ("audio", "audio"), ("voice", "voice"), ("video", "video"), ("animation", "video")):
            value = message.get(key)
            if isinstance(value, dict):
                candidates.append((kind, value))
        results: list[dict[str, Any]] = []
        for index, (kind, item) in enumerate(candidates):
            file_id = str(item.get("file_id") or "")
            name = str(item.get("file_name") or f"{kind}-{update_id}-{index}{self._extension(kind, item)}")
            attachment: dict[str, Any] = {
                "source": "telegram",
                "type": kind,
                "file_id": file_id,
                "file_unique_id": str(item.get("file_unique_id") or ""),
                "file_name": name,
                "size": int(item.get("file_size") or 0),
                "mime_type": str(item.get("mime_type") or ""),
                "quoted": quoted,
            }
            if self.config.media_enabled and self.config.auto_download_media and file_id:
                safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name) or f"telegram-{update_id}-{index}.bin"
                target = Path(self.config.media_dir) / str(update_id) / safe_name
                try:
                    downloaded = await (self.client or self._create_client()).download_file(file_id, target, max_bytes=int(self.config.media_max_bytes))
                    attachment["local_path"] = str(downloaded.resolve())
                except TelegramApiError as exc:
                    attachment["download_error"] = str(exc)
            results.append(attachment)
        return results

    async def _quote(self, value: Any, *, update_id: int) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        sender = value.get("from") if isinstance(value.get("from"), dict) else {}
        return {
            "message_id": str(value.get("message_id") or ""),
            "sender_id": str(sender.get("id") or ""),
            "sender_name": self._display_name(sender, value.get("chat") if isinstance(value.get("chat"), dict) else {}),
            "content": str(value.get("text") or value.get("caption") or ""),
            "attachments": await self._attachments(value, update_id=update_id, quoted=True),
        }

    def _mentions_bot(self, message: dict[str, Any]) -> bool:
        reply = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else {}
        reply_from = reply.get("from") if isinstance(reply.get("from"), dict) else {}
        if self.bot_id and str(reply_from.get("id") or "") == self.bot_id:
            return True
        text = str(message.get("text") or message.get("caption") or "")
        username = self.bot_username.casefold()
        if username and f"@{username}" in text.casefold():
            return True
        entities = message.get("entities") if isinstance(message.get("entities"), list) else []
        return any(str(item.get("type") or "") == "mention" and username and f"@{username}" in text.casefold() for item in entities if isinstance(item, dict))

    @staticmethod
    def _update_message(raw: dict[str, Any]) -> dict[str, Any]:
        for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
            if isinstance(raw.get(key), dict):
                return raw[key]
        return {}

    @staticmethod
    def _message_type(message: dict[str, Any]) -> str:
        if message.get("photo"):
            return "image"
        if message.get("video") or message.get("animation"):
            return "video"
        if message.get("voice"):
            return "voice"
        if message.get("document") or message.get("audio"):
            return "file"
        return "text"

    @staticmethod
    def _display_name(user: dict[str, Any], chat: dict[str, Any]) -> str:
        name = " ".join(str(user.get(key) or "").strip() for key in ("first_name", "last_name")).strip()
        return name or str(user.get("username") or chat.get("title") or chat.get("username") or "")

    @staticmethod
    def _target_from_conversation(conversation_id: str) -> str | None:
        parts = conversation_id.split(":", 2)
        if len(parts) == 3 and parts[0] == "telegram" and parts[2]:
            return parts[2]
        return None

    @staticmethod
    def _telegram_message_id(value: str | None) -> int | None:
        if not value:
            return None
        tail = str(value).rsplit(":", 1)[-1]
        return int(tail) if tail.isdigit() else None

    @staticmethod
    def _inline_keyboard(metadata: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("inline_keyboard") or metadata.get("keyboard")
        if isinstance(value, dict) and isinstance(value.get("inline_keyboard"), list):
            return value
        if isinstance(value, list):
            return {"inline_keyboard": value}
        return None

    @staticmethod
    def _is_markdown_parse_error(exc: TelegramApiError) -> bool:
        message = str(exc).lower()
        return "parse entities" in message or "can't parse" in message or "cant parse" in message

    @staticmethod
    def _split_text(text: str, limit: int) -> list[str]:
        text = str(text or "")
        if not text:
            return [" "]
        return [text[index:index + limit] for index in range(0, len(text), limit)]

    @staticmethod
    def _placeholder(message_type: str) -> str:
        return {"image": "[图片]", "file": "[文件]", "voice": "[语音]", "video": "[视频]", "event": "[交互]"}.get(message_type, "")

    @staticmethod
    def _extension(kind: str, item: dict[str, Any]) -> str:
        mime = str(item.get("mime_type") or "")
        return {"image": ".jpg", "video": ".mp4", "voice": ".ogg", "audio": ".mp3"}.get(kind, Path(str(item.get("file_name") or "")).suffix or (".bin" if not mime else ".bin"))

    def _create_client(self) -> TelegramBotClient:
        return self.client_factory() if self.client_factory else TelegramBotClient(self.config)

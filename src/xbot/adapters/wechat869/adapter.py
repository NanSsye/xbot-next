from __future__ import annotations

import asyncio
import json
from typing import Any

from xbot.adapters.base import BaseAdapter
from xbot.adapters.wechat869.client import Wechat869Client
from xbot.adapters.wechat869.media import Wechat869MediaResolver
from xbot.core.config import Wechat869AdapterConfig
from xbot.core.logging import logger
from xbot.messaging.models import Message, MessageEnvelope, Reply
from xbot.messaging.queue import MessageQueue


TEXT_KEYS = ("Content", "content", "TextContent", "text", "message")
SENDER_KEYS = (
    "FromUserName",
    "from_user_name",
    "FromWxid",
    "from_wxid",
    "sender",
    "fromUserName",
    "Talker",
)
TO_KEYS = ("ToUserName", "to_user_name", "ToWxid", "to_wxid")
MSG_ID_KEYS = ("MsgId", "msg_id", "NewMsgId", "new_msg_id", "message_id", "id")
MSG_TYPE_KEYS = ("MsgType", "msg_type", "msgType", "type")
GROUP_SENDER_KEYS = ("ActualSender", "actual_sender", "SenderWxid", "sender_wxid", "ChatUser")
DISPLAY_NAME_KEYS = (
    "NickName",
    "nick_name",
    "FromNickName",
    "from_nick_name",
    "SenderNickName",
    "sender_nick_name",
    "ActualNickName",
    "actual_nick_name",
    "PushContent",
    "push_content",
)


class Wechat869Adapter(BaseAdapter):
    name = "wechat869"
    platform = "wechat"

    def __init__(
        self,
        config: Wechat869AdapterConfig,
        queue: MessageQueue | None = None,
        client_factory=None,
    ) -> None:
        self.config = config
        self.queue = queue
        self.client_factory = client_factory
        self.client = None
        self.media = None
        self.started = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self.started = True
        self.client = self.client or self._create_client()
        if self.config.token_key:
            self.client.token_key = self.config.token_key
        if self.config.bot_wxid:
            self.client.wxid = self.config.bot_wxid
        if self.config.bot_nickname:
            self.client.nickname = self.config.bot_nickname
        self.media = Wechat869MediaResolver(self.config, self.client)
        if self.queue and self._task is None:
            self._task = asyncio.create_task(self._listen_loop(), name="xbot-wechat869-adapter")

    async def stop(self) -> None:
        self.started = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def send(self, reply: Reply) -> None:
        if reply.type != "text":
            logger.warning("Wechat869Adapter 当前只支持文本回复: {}", reply.type)
            return
        client = self.client or self._create_client()
        conversation_id = self._raw_conversation_id(reply.conversation_id)
        await client.send_text_message(conversation_id, reply.content)

    async def normalize(self, raw: dict) -> Message:
        message = self._unwrap_message(raw)
        msg_type = self._pick_int(message, MSG_TYPE_KEYS, default=1)
        content = self._extract_content(message)
        sender = self._extract_sender(message)
        to_wxid = self._pick_text(message, TO_KEYS)
        is_group = self._is_group_message(message, sender)
        conversation_id = sender if is_group else sender or to_wxid
        sender_id = self._extract_group_sender(message, content) if is_group else sender
        sender_name = self._extract_sender_name(message, sender_id)
        clean_content = self._strip_group_sender_prefix(content) if is_group else content
        raw_id = self._pick_text(message, MSG_ID_KEYS)
        raw_scope = "group" if is_group else "private"
        raw["scope"] = raw_scope
        raw["message_id"] = raw_id
        raw["sender_wxid"] = sender_id or sender or ""
        raw["sender_name"] = sender_name
        raw["conversation_wxid"] = conversation_id or ""
        raw["private_wxid"] = sender_id if raw_scope == "private" else ""
        raw["group_wxid"] = conversation_id if raw_scope == "group" else ""
        raw["group_member_wxid"] = sender_id if raw_scope == "group" else ""
        raw["mentions_bot"] = self._mentions_bot(clean_content)
        raw["bot_wxid"] = self.config.bot_wxid
        raw["bot_nickname"] = self.config.bot_nickname
        media = self.media or Wechat869MediaResolver(self.config, self.client or self._create_client())
        media_info = await media.enrich(
            raw,
            message,
            msg_type=msg_type,
            conversation_id=conversation_id or "unknown_869",
            msg_id=raw_id or "",
        )
        raw["attachments"] = media_info.get("attachments") or []
        if media_info.get("quote"):
            raw["quote"] = media_info["quote"]
        display_content = self._content_with_media_summary(clean_content, msg_type, raw)
        message_data = {
            "platform": self.platform,
            "adapter": self.name,
            "type": self._message_type(msg_type, raw),
            "conversation_id": conversation_id or "unknown_869",
            "sender_id": sender_id or sender or "unknown_869",
            "sender_name": sender_name,
            "content": display_content,
            "raw": raw,
        }
        if raw_id:
            message_data["id"] = raw_id
        return Message(**message_data)

    async def _listen_loop(self) -> None:
        while self.started:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Wechat869Adapter WS 监听异常，{} 秒后重连: {}", self.config.reconnect_seconds, exc)
                await asyncio.sleep(self.config.reconnect_seconds)

    async def _listen_once(self) -> None:
        import aiohttp

        ws_url = self._ws_url()
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                ws_url,
                heartbeat=30,
                timeout=self.config.connect_timeout_seconds,
            ) as ws:
                logger.info("Wechat869Adapter 已连接 WS: {}", self._mask_url(ws_url))
                async for event in ws:
                    if event.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_ws_text(event.data)
                    elif event.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                        break

    async def _handle_ws_text(self, payload: str) -> None:
        logger.info("Wechat869Adapter 收到 WS 文本: {}", self._preview(payload))
        data = self._loads_json(payload)
        messages = self._extract_messages(data)
        logger.info("Wechat869Adapter 提取到 {} 条候选消息", len(messages))
        for raw in messages:
            message = await self.normalize(raw)
            if self._should_ignore_message(message):
                logger.info(
                    "Wechat869Adapter 丢弃自身或系统消息: id={} sender={} type={} content={}",
                    message.id,
                    message.sender_id,
                    message.type,
                    self._preview(message.content),
                )
                continue
            if self.config.text_only and message.type != "text":
                logger.info(
                    "Wechat869Adapter 丢弃非文本消息: id={} type={} raw_type={}",
                    message.id,
                    message.type,
                    raw.get("MsgType") or raw.get("msg_type") or raw.get("type"),
                )
                continue
            if not message.content:
                logger.info(
                    "Wechat869Adapter 丢弃空内容消息: id={} raw={}",
                    message.id,
                    self._preview(raw),
                )
                continue
            if self.queue is None:
                logger.warning("Wechat869Adapter 未配置消息队列，消息不会进入框架: {}", message.id)
                continue
            logger.info(
                "Wechat869Adapter 发布消息到队列: id={} scope={} conversation={} sender={} attachments={} quote_attachments={} content={}",
                message.id,
                message.raw.get("scope"),
                message.conversation_id,
                message.sender_id,
                len(message.raw.get("attachments") or []),
                len((message.raw.get("quote") or {}).get("attachments") or []) if isinstance(message.raw.get("quote"), dict) else 0,
                self._preview(message.content),
            )
            await self.queue.publish(MessageEnvelope.from_message(message))

    def _should_ignore_message(self, message: Message) -> bool:
        bot_wxid = self.config.bot_wxid or getattr(self.client, "wxid", "")
        if bot_wxid and message.sender_id == bot_wxid:
            return True
        raw_type = self._pick_int(message.raw, MSG_TYPE_KEYS, default=1)
        if message.raw.get("scope") == "private" and message.sender_id == message.conversation_id and message.sender_id == bot_wxid:
            return True
        if raw_type in {51, 10000, 10002}:
            return True
        return False

    def _loads_json(self, payload: Any) -> Any:
        if isinstance(payload, (dict, list)):
            return payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        if not isinstance(payload, str):
            return payload
        text = payload.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Wechat869Adapter 收到非 JSON WS 文本: {}", self._preview(text))
            return {"content": text}

    def _extract_messages(self, data: Any) -> list[dict]:
        data = self._loads_json(data)
        if not isinstance(data, dict):
            return []
        for key in ("AddMsgs", "addMsgs", "messages", "Messages"):
            value = self._loads_json(data.get(key))
            if isinstance(value, list):
                return [item for item in (self._loads_json(item) for item in value) if isinstance(item, dict)]
        nested = self._loads_json(data.get("Data") or data.get("data") or data.get("payload"))
        if isinstance(nested, dict):
            nested_messages = self._extract_messages(nested)
            if nested_messages:
                return nested_messages
        single = self._loads_json(data.get("message") or data.get("Message"))
        if isinstance(single, dict):
            return [single]
        return [data]

    def _preview(self, value: Any, limit: int = 500) -> str:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        value = value.replace("\r", "\\r").replace("\n", "\\n")
        if len(value) <= limit:
            return value
        return value[:limit] + f"...({len(value)} chars)"

    def _create_client(self):
        if self.client_factory:
            return self.client_factory()
        return Wechat869Client(
            host=self.config.host,
            port=self.config.port,
            admin_key=self.config.admin_key,
            token_key=self.config.token_key,
            ws_url=self.config.ws_url,
            timeout_seconds=self.config.connect_timeout_seconds,
        )

    def _ws_url(self) -> str:
        ws_url = self.config.ws_url or f"ws://{self.config.host}:{self.config.port}/ws/GetSyncMsg"
        key = self.config.token_key or self.config.admin_key
        if self.client and hasattr(self.client, "append_key_to_ws_url"):
            return self.client.append_key_to_ws_url(ws_url, key)
        if key and "key=" not in ws_url:
            separator = "&" if "?" in ws_url else "?"
            return f"{ws_url}{separator}key={key}"
        return ws_url

    def _mask_url(self, url: str) -> str:
        if "key=" not in url:
            return url
        prefix, key = url.split("key=", 1)
        return prefix + "key=" + (key[:4] + "***" if key else "")

    def _unwrap_message(self, raw: dict) -> dict:
        value = raw.get("message") or raw.get("Message")
        return value if isinstance(value, dict) else raw

    def _extract_content(self, raw: dict) -> str:
        return self._pick_text(raw, TEXT_KEYS)

    def _message_type(self, msg_type: int, raw: dict) -> str:
        if msg_type == 1:
            return "text"
        if msg_type == 3:
            return "image"
        quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
        if msg_type == 49 and (raw.get("attachments") or quote.get("attachments")):
            return "file"
        return "event"

    def _content_with_media_summary(self, content: str, msg_type: int, raw: dict) -> str:
        content = content.strip() if content else ""
        lines = [content] if content and (msg_type == 1 or not content.lstrip().startswith("<")) else []
        for attachment in raw.get("attachments") or []:
            lines.append(self._attachment_line(attachment))
        quote = raw.get("quote")
        if isinstance(quote, dict):
            quote_content = str(quote.get("content") or "").strip()
            sender = str(quote.get("sender_name") or quote.get("sender_wxid") or "").strip()
            prefix = f"[引用] {sender}: {quote_content}" if sender and quote_content else f"[引用] {quote_content or sender}".strip()
            if prefix and prefix != "[引用]":
                lines.append(prefix)
            for attachment in quote.get("attachments") or []:
                lines.append("[引用" + self._attachment_line(attachment).lstrip("["))
        if not lines:
            if msg_type == 3:
                lines.append("[图片]")
            elif msg_type == 49:
                lines.append("[文件/应用消息]")
            else:
                lines.append(f"[非文本消息 MsgType={msg_type}]")
        return "\n".join(lines)

    def _attachment_line(self, attachment: dict) -> str:
        kind = "图片" if attachment.get("kind") == "image" else "文件"
        filename = str(attachment.get("filename") or "")
        status = str(attachment.get("download_status") or "")
        local_path = str(attachment.get("local_path") or "")
        size = attachment.get("size") or 0
        parts = [f"[{kind}]"]
        if filename:
            parts.append(f"filename={filename}")
        if size:
            parts.append(f"size={size}")
        if local_path:
            parts.append(f"local_path={local_path}")
        elif status:
            parts.append(f"status={status}")
        return " ".join(parts)

    def _extract_sender(self, raw: dict) -> str:
        return self._pick_text(raw, SENDER_KEYS)

    def _extract_group_sender(self, raw: dict, content: str) -> str:
        direct = self._pick_text(raw, GROUP_SENDER_KEYS)
        if direct:
            return direct
        if ":\n" in content:
            return content.split(":\n", 1)[0].strip()
        return ""

    def _extract_sender_name(self, raw: dict, sender_id: str) -> str | None:
        direct = self._pick_text(raw, DISPLAY_NAME_KEYS)
        name = self._name_from_push_content(direct)
        if name and name != sender_id:
            return name
        return None

    def _name_from_push_content(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        for separator in (" : ", ": ", "："):
            if separator in text:
                return text.split(separator, 1)[0].strip()
        return text

    def _strip_group_sender_prefix(self, content: str) -> str:
        if ":\n" in content:
            return content.split(":\n", 1)[1]
        return content

    def _mentions_bot(self, content: str) -> bool:
        candidates = [self.config.bot_wxid, self.config.bot_nickname]
        return any(candidate and candidate in content for candidate in candidates)

    def _is_group_message(self, raw: dict, sender: str) -> bool:
        if sender.endswith("@chatroom"):
            return True
        value = raw.get("IsGroup") if "IsGroup" in raw else raw.get("is_group")
        return bool(value)

    def _pick_text(self, raw: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            if key not in raw:
                continue
            value = raw.get(key)
            if isinstance(value, dict):
                for nested_key in ("str", "Str", "string", "String", "value", "Value", "text", "Text"):
                    nested = value.get(nested_key)
                    if nested not in (None, ""):
                        return str(nested)
            if value not in (None, ""):
                return str(value)
        return ""

    def _pick_int(self, raw: dict, keys: tuple[str, ...], default: int = 0) -> int:
        text = self._pick_text(raw, keys)
        try:
            return int(text)
        except (TypeError, ValueError):
            return default

    def _raw_conversation_id(self, conversation_id: str) -> str:
        marker = f"{self.platform}:{self.name}:"
        if conversation_id.startswith(marker):
            return conversation_id.split(":", 3)[-1]
        return conversation_id

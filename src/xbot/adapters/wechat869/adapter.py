from __future__ import annotations

import asyncio
import base64
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
CREATE_TIME_KEYS = ("CreateTime", "create_time", "createTime", "Createtime")
MSG_SOURCE_KEYS = ("MsgSource", "msg_source", "msgSource", "message_source")
GROUP_SENDER_KEYS = ("ActualSender", "actual_sender", "SenderWxid", "sender_wxid", "ChatUser")
AT_USER_KEYS = ("beAtUser", "BeAtUser", "atUser", "AtUser", "at_user", "AtWxidList", "at_wxid_list")
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
SYSTEM_CONVERSATION_IDS = {
    "newsapp",
    "fmessage",
    "weixin",
    "medianote",
    "floatbottle",
    "qqmail",
    "notifymessage",
    "notification_messages",
    "officialaccounts",
    "feedsapp",
}


class Wechat869Adapter(BaseAdapter):
    name = "wechat869"
    platform = "wechat"

    def __init__(
        self,
        config: Wechat869AdapterConfig,
        queue: MessageQueue | None = None,
        client_factory=None,
        repository_provider=None,
    ) -> None:
        self.config = config
        self.queue = queue
        self.client_factory = client_factory
        self.repository_provider = repository_provider
        self.client = None
        self.media = None
        self.started = False
        self._task: asyncio.Task | None = None
        self._login_qrcode: str = ""
        self._login_qr_url: str = ""
        self._login_status: str = ""

    async def start(self) -> None:
        self.started = True
        await self._restore_state()
        self.client = self.client or self._create_client()
        await self._restore_client_state(self.client)
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
        client = self.client or self._create_client()
        conversation_id = self._raw_conversation_id(reply.conversation_id)
        if reply.type == "text":
            await client.send_text_message(conversation_id, reply.content)
            return
        if reply.type == "image":
            await client.send_image_message(conversation_id, reply.content)
            return
        if reply.type == "file":
            await client.send_file_message(conversation_id, reply.content)
            return
        if reply.type == "voice":
            voice_path = Path(reply.content)
            await client.send_voice_message(
                conversation_id,
                voice_path.read_bytes(),
                format=str(reply.metadata.get("format") or voice_path.suffix.lstrip(".") or "wav"),
                seconds=int(reply.metadata.get("seconds") or 0),
            )
            return
        if reply.type == "video":
            await client.send_video_message(conversation_id, reply.content)
            return
        if reply.type in {"link", "music_card"}:
            await client.send_app_message(
                conversation_id,
                str(reply.metadata["content_xml"]),
                content_type=int(reply.metadata["content_type"]),
            )
            return
        logger.warning("Wechat869Adapter 不支持回复类型: {}", reply.type)

    def public_status(self) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "platform": self.platform,
            "started": self.started,
            "host": self.config.host,
            "port": self.config.port,
            "ws_url": self._ws_url(),
            "admin_key_configured": bool(self.config.admin_key),
            "admin_key": self.config.admin_key,
            "token_key_configured": bool(self.config.token_key),
            "token_key": self.config.token_key,
            "auth_key": getattr(self.client, "auth_key", ""),
            "poll_key": getattr(self.client, "poll_key", ""),
            "display_uuid": getattr(self.client, "display_uuid", ""),
            "login_tx_id": getattr(self.client, "login_tx_id", ""),
            "device_id": getattr(self.client, "device_id", ""),
            "device_type": getattr(self.client, "device_type", ""),
            "data62_set": bool(getattr(self.client, "data62", "")),
            "ticket_set": bool(getattr(self.client, "ticket", "")),
            "login_status": self._login_status,
            "login_qrcode_cached": bool(self._login_qrcode or self._login_qr_url),
            "bot_wxid": self.config.bot_wxid,
            "bot_nickname": self.config.bot_nickname,
            "media_enabled": self.config.media_enabled,
            "text_only": self.config.text_only,
            "login_supported": True,
        }

    async def refreshed_public_status(self) -> dict[str, Any]:
        client = self.client or self._create_client()
        self.client = client
        await self._restore_client_state(client)
        if self.config.token_key and not getattr(client, "token_key", ""):
            client.token_key = self.config.token_key
        status: dict[str, Any] = {}
        if getattr(client, "token_key", "") or getattr(client, "poll_key", "") or getattr(client, "auth_key", ""):
            status = await client.get_login_status()
            self._apply_client_login_state(client)
            self._login_status = str(status.get("status") or self._login_status)
            if status.get("logged_in"):
                await self._persist_state()
        return {**self.public_status(), **status}

    async def start_login(self, *, device_type: str = "ipad", proxy: str = "") -> dict[str, Any]:
        client = self.client or self._create_client()
        self.client = client
        await self._restore_client_state(client)
        if await client.try_wakeup_login():
            self._apply_client_login_state(client)
            self._login_status = "online"
            await self._persist_state()
            return {**self.public_status(), "logged_in": True, "status": "online", "message": "已从现有 key 恢复登录。"}
        payload = await client.get_login_qrcode(
            device_type=device_type,
            device_id=getattr(client, "device_id", "") or "",
            proxy=proxy,
        )
        self._apply_client_login_state(client)
        self._login_qrcode = str(payload.get("qrcode") or payload.get("uuid") or "")
        self._login_qr_url = str(payload.get("qr_url") or "")
        self._login_status = "waiting_login"
        await self._persist_state()
        return {
            **self.public_status(),
            **payload,
            "logged_in": False,
            "qr_image_url": self._qr_data_url(self._login_qr_url or self._login_qrcode),
            "message": "869 登录二维码已生成，请用微信扫码。",
        }

    async def poll_login_status(self) -> dict[str, Any]:
        client = self.client or self._create_client()
        self.client = client
        await self._restore_client_state(client)
        payload = await client.poll_login_status()
        self._apply_client_login_state(client)
        if payload.get("logged_in"):
            self._login_status = "online"
            self._login_qrcode = ""
            self._login_qr_url = ""
        else:
            self._login_status = str(payload.get("status") or "waiting_login")
        await self._persist_state()
        return {**self.public_status(), **payload}

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
        raw["Content"] = content
        raw["content"] = clean_content
        raw["raw_content"] = content
        raw["sender_wxid"] = sender_id or sender or ""
        raw["sender_name"] = sender_name
        raw["conversation_wxid"] = conversation_id or ""
        raw["private_wxid"] = sender_id if raw_scope == "private" else ""
        raw["group_wxid"] = conversation_id if raw_scope == "group" else ""
        raw["group_member_wxid"] = sender_id if raw_scope == "group" else ""
        raw["at_user_list"] = self._extract_at_user_list(message)
        raw["mentions_bot"] = self._mentions_bot(message, clean_content, to_wxid=to_wxid)
        raw["bot_wxid"] = self.config.bot_wxid or to_wxid
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
        created_at = self._extract_message_time(message)
        if created_at is not None:
            message_data["timestamp"] = created_at
        return Message(**message_data)

    def _extract_message_time(self, message: dict[str, Any]) -> datetime | None:
        raw_value = self._pick_text(message, CREATE_TIME_KEYS)
        if not raw_value:
            return None
        try:
            ts = float(raw_value)
            if ts > 10_000_000_000:
                ts = ts / 1000
            # 业务要求：数据库直接保存北京时间的无时区 datetime。
            return datetime.utcfromtimestamp(ts) + timedelta(hours=8)
        except (TypeError, ValueError, OSError):
            return None

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
        bot_wxid = (
            self.config.bot_wxid
            or str(message.raw.get("bot_wxid") or "")
            or getattr(self.client, "wxid", "")
        )
        if bot_wxid and message.sender_id == bot_wxid:
            return True
        if self._is_ignored_conversation(message):
            return True
        raw_type = self._pick_int(message.raw, MSG_TYPE_KEYS, default=1)
        if message.raw.get("scope") == "private" and message.sender_id == message.conversation_id and message.sender_id == bot_wxid:
            return True
        if raw_type in {10000, 10002} and message.raw.get("scope") == "group":
            return False
        if raw_type in {51, 10000, 10002}:
            return True
        return False

    def _is_ignored_conversation(self, message: Message) -> bool:
        ids = {
            str(message.sender_id or ""),
            str(message.conversation_id or ""),
            str(message.raw.get("conversation_wxid") or ""),
            str(message.raw.get("private_wxid") or ""),
            str(message.raw.get("sender_wxid") or ""),
        }
        for value in ids:
            if not value:
                continue
            if value.startswith("gh_"):
                return True
            if value in SYSTEM_CONVERSATION_IDS:
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
        client = Wechat869Client(
            host=self.config.host,
            port=self.config.port,
            admin_key=self.config.admin_key,
            token_key=self.config.token_key,
            ws_url=self.config.ws_url,
            timeout_seconds=self.config.connect_timeout_seconds,
        )
        return client

    async def _restore_state(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            state = await repo.get_state(self.name)
        if not state:
            return
        self.config.token_key = str(self.config.token_key or state.get("token_key") or "")
        self.config.bot_wxid = str(state.get("bot_wxid") or self.config.bot_wxid)
        self.config.bot_nickname = str(state.get("bot_nickname") or self.config.bot_nickname)
        self._login_qrcode = str(state.get("qrcode") or "")
        self._login_qr_url = str(state.get("qr_url") or "")
        self._login_status = str(state.get("login_status") or self._login_status)

    async def _restore_client_state(self, client: Any) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            state = await repo.get_state(self.name)
        if not state:
            return
        client.token_key = str(self.config.token_key or client.token_key or state.get("token_key") or "")
        client.auth_key = str(state.get("auth_key") or getattr(client, "auth_key", ""))
        auth_keys = state.get("auth_keys") or []
        client.auth_keys = [str(item).strip() for item in auth_keys if str(item).strip()] if isinstance(auth_keys, list) else []
        client.poll_key = str(state.get("poll_key") or getattr(client, "poll_key", ""))
        client.display_uuid = str(state.get("display_uuid") or getattr(client, "display_uuid", ""))
        client.login_tx_id = str(state.get("login_tx_id") or getattr(client, "login_tx_id", ""))
        client.data62 = str(state.get("data62") or getattr(client, "data62", ""))
        client.ticket = str(state.get("ticket") or getattr(client, "ticket", ""))
        client.device_id = str(state.get("device_id") or getattr(client, "device_id", ""))
        client.device_type = str(state.get("device_type") or getattr(client, "device_type", "ipad") or "ipad")
        client.wxid = str(state.get("bot_wxid") or client.wxid or self.config.bot_wxid)
        client.nickname = str(state.get("bot_nickname") or client.nickname or self.config.bot_nickname)

    def _apply_client_login_state(self, client: Any) -> None:
        self.config.token_key = str(getattr(client, "token_key", "") or self.config.token_key)
        self.config.bot_wxid = str(getattr(client, "wxid", "") or self.config.bot_wxid)
        self.config.bot_nickname = str(getattr(client, "nickname", "") or self.config.bot_nickname)

    async def _persist_state(self) -> None:
        if not self.repository_provider:
            return
        client = self.client
        state = {
            "token_key": self.config.token_key,
            "bot_wxid": self.config.bot_wxid,
            "bot_nickname": self.config.bot_nickname,
            "qrcode": self._login_qrcode,
            "qr_url": self._login_qr_url,
            "login_status": self._login_status,
        }
        if client is not None:
            state.update(
                {
                    "auth_key": str(getattr(client, "auth_key", "") or ""),
                    "auth_keys": list(getattr(client, "auth_keys", []) or []),
                    "poll_key": str(getattr(client, "poll_key", "") or ""),
                    "display_uuid": str(getattr(client, "display_uuid", "") or ""),
                    "login_tx_id": str(getattr(client, "login_tx_id", "") or ""),
                    "data62": str(getattr(client, "data62", "") or ""),
                    "ticket": str(getattr(client, "ticket", "") or ""),
                    "device_id": str(getattr(client, "device_id", "") or ""),
                    "device_type": str(getattr(client, "device_type", "") or ""),
                }
            )
        async with self.repository_provider() as repo:
            previous = await repo.get_state(self.name)
            previous.update(state)
            await repo.set_state(self.name, previous)

    def _qr_data_url(self, value: str) -> str:
        if not value:
            return ""
        try:
            import qrcode

            image = qrcode.make(value)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except Exception as exc:
            logger.warning("Wechat869Adapter 生成二维码图片失败: {}", exc)
            return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote(value, safe='')}"

    def _ws_url(self) -> str:
        ws_url = self.config.ws_url or f"ws://{self.config.host}:{self.config.port}/ws/GetSyncMsg"
        key = (
            str(getattr(self.client, "token_key", "") or "")
            or str(getattr(self.client, "poll_key", "") or "")
            or str(getattr(self.client, "auth_key", "") or "")
            or self.config.token_key
            or self.config.admin_key
        )
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
        lines = []
        if content and (msg_type == 1 or not content.lstrip().startswith("<")):
            lines.append(content)
        elif content and content.lstrip().startswith("<"):
            title = self._extract_xml_display_text(content)
            if title:
                lines.append(title)
        # 直接发送图片/文件只作为附件保存，不拼进文本，避免普通媒体自动进入 OpenClaw。
        quote = raw.get("quote")
        if isinstance(quote, dict):
            quote_attachments = [a for a in quote.get("attachments") or [] if isinstance(a, dict)]
            quote_content = str(quote.get("content") or "").strip()
            sender = str(quote.get("sender_name") or quote.get("sender_wxid") or "").strip()
            if quote_attachments:
                for attachment in quote_attachments:
                    lines.append("[引用" + self._attachment_line(attachment, include_local_path=False).lstrip("["))
            else:
                prefix = f"[引用] {sender}: {quote_content}" if sender and quote_content else f"[引用] {quote_content or sender}".strip()
                if prefix and prefix != "[引用]":
                    lines.append(prefix)
        if not lines:
            if msg_type == 3:
                lines.append("[图片]")
            elif msg_type == 49:
                lines.append("[文件/应用消息]")
            else:
                lines.append(f"[非文本消息 MsgType={msg_type}]")
        return "\n".join(lines)

    def _extract_xml_display_text(self, content: str) -> str:
        text = str(content or "")
        for tag in ("title", "des", "content"):
            match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            value = re.sub(r"<[^>]+>", " ", match.group(1))
            value = value.replace("<![CDATA[", "").replace("]]>", "")
            value = " ".join(value.split()).strip()
            if value and not value.startswith("<?xml") and len(value) <= 500:
                return value
        return ""

    def _attachment_line(self, attachment: dict, *, include_local_path: bool = True) -> str:
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
        if local_path and include_local_path:
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

    def _mentions_bot(self, raw: dict, content: str, *, to_wxid: str = "") -> bool:
        at_users = self._extract_at_user_list(raw)
        if at_users:
            candidates = {item for item in (self.config.bot_wxid, to_wxid) if item}
            return bool(candidates.intersection(at_users))
        candidates = [self.config.bot_wxid or to_wxid, self.config.bot_nickname]
        return any(candidate and candidate in content for candidate in candidates)

    def _extract_at_user_list(self, raw: dict) -> list[str]:
        values: list[str] = []
        for key in AT_USER_KEYS:
            value = raw.get(key)
            values.extend(self._split_wxid_list(value))
        source = self._pick_text(raw, MSG_SOURCE_KEYS)
        if source:
            for match in re.findall(r"<atuserlist>(.*?)</atuserlist>", source, flags=re.IGNORECASE | re.DOTALL):
                values.extend(self._split_wxid_list(self._strip_xml_cdata(match)))
        seen = set()
        result = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _split_wxid_list(self, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, dict):
            items = []
            for nested_key in ("str", "Str", "string", "String", "value", "Value", "text", "Text"):
                items.extend(self._split_wxid_list(value.get(nested_key)))
            return items
        if isinstance(value, (list, tuple, set)):
            items = []
            for item in value:
                items.extend(self._split_wxid_list(item))
            return items
        text = str(value)
        text = self._strip_xml_cdata(text)
        return [item.strip() for item in re.split(r"[,;，；\s]+", text) if item.strip()]

    def _strip_xml_cdata(self, value: str) -> str:
        text = str(value or "").strip()
        match = re.fullmatch(r"<!\[CDATA\[(.*?)\]\]>", text, flags=re.DOTALL)
        return match.group(1).strip() if match else text

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

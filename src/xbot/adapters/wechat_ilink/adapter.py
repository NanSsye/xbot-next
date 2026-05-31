from __future__ import annotations

import asyncio
import json
from typing import Any

from xbot.adapters.base import BaseAdapter
from xbot.adapters.wechat_ilink.client import WechatIlinkClient, WechatIlinkError
from xbot.adapters.wechat_ilink.media import WechatIlinkMediaResolver
from xbot.core.config import WechatIlinkAdapterConfig
from xbot.core.logging import logger
from xbot.messaging.models import Message, MessageEnvelope, Reply
from xbot.messaging.queue import MessageQueue


class WechatIlinkAdapter(BaseAdapter):
    name = "wechat_ilink"
    platform = "wechat"

    def __init__(
        self,
        config: WechatIlinkAdapterConfig,
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
        self.cursor = config.cursor
        self._task: asyncio.Task | None = None
        self._login_task: asyncio.Task | None = None
        self._reply_targets: dict[str, dict[str, str]] = {}
        self._login_qrcode: str = ""
        self._login_base_url: str = ""

    async def start(self) -> None:
        self.started = True
        await self._restore_state()
        self.client = self.client or self._create_client()
        self.media = self.media or self._create_media_resolver()
        if not self.config.token:
            await self._print_login_qrcode()
            return
        if self.queue and self._task is None:
            self._task = asyncio.create_task(self._poll_loop(), name="xbot-wechat-ilink-adapter")

    async def stop(self) -> None:
        self.started = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._login_task:
            self._login_task.cancel()
            try:
                await self._login_task
            except asyncio.CancelledError:
                pass
            self._login_task = None

    async def send(self, reply: Reply) -> None:
        target = self._reply_targets.get(reply.conversation_id)
        if not target:
            logger.warning("WechatIlinkAdapter 找不到回发目标: conversation={}", reply.conversation_id)
            return
        client = self.client or self._create_client()
        if reply.type == "text":
            await client.send_text(
                to_user_id=target["to_user_id"],
                context_token=target["context_token"],
                text=reply.content,
            )
            return
        if reply.type == "image":
            await client.send_image(
                to_user_id=target["to_user_id"],
                context_token=target["context_token"],
                path=reply.content,
            )
            return
        if reply.type == "file":
            await client.send_file(
                to_user_id=target["to_user_id"],
                context_token=target["context_token"],
                path=reply.content,
            )
            return
        logger.warning("WechatIlinkAdapter 不支持回复类型: {}", reply.type)

    async def normalize(self, raw: dict) -> Message:
        from_user_id = str(raw.get("from_user_id") or raw.get("fromUserId") or "unknown_ilink")
        context_token = str(raw.get("context_token") or "")
        raw_id = str(raw.get("msg_id") or raw.get("message_id") or raw.get("client_id") or "")
        conversation_id = f"ilink:{from_user_id}"
        message_type, content, attachments, quote = await self._parse_items(
            raw.get("item_list") or [],
            conversation_id=conversation_id,
            msg_id=raw_id,
        )
        raw["scope"] = "private"
        raw["message_id"] = raw_id
        raw["sender_wxid"] = from_user_id
        raw["private_wxid"] = from_user_id
        raw["conversation_wxid"] = from_user_id
        raw["mentions_bot"] = True
        raw["bot_wxid"] = self.config.bot_wxid
        raw["bot_nickname"] = self.config.bot_nickname
        raw["context_token"] = context_token
        raw["attachments"] = attachments
        if quote:
            raw["quote"] = quote
        self._remember_reply_target(conversation_id, from_user_id, context_token)
        data = {
            "platform": self.platform,
            "adapter": self.name,
            "type": message_type,
            "conversation_id": conversation_id,
            "sender_id": from_user_id,
            "sender_name": str(raw.get("from_nickname") or raw.get("nickname") or ""),
            "content": content,
            "raw": raw,
        }
        if raw_id:
            data["id"] = raw_id
        return Message(**data)

    async def get_login_qrcode(self) -> dict[str, str]:
        client = self.client or self._create_client()
        payload = await client.get_qr_code()
        self._login_qrcode = str(payload.get("qrcode") or "")
        self._login_base_url = self.config.base_url
        return {
            "qrcode": self._login_qrcode,
            "qr_url": str(payload.get("qrcode_img_content") or payload.get("qr_url") or ""),
            "base_url": self._login_base_url,
        }

    def public_status(self) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "platform": self.platform,
            "started": self.started,
            "logged_in": bool(self.config.token),
            "token_configured": bool(self.config.token),
            "base_url": self.config.base_url,
            "bot_wxid": self.config.bot_wxid,
            "bot_nickname": self.config.bot_nickname,
            "cursor_set": bool(self.cursor),
            "login_qrcode_cached": bool(self._login_qrcode),
            "polling": bool(self._task and not self._task.done()),
        }

    async def poll_login_status(self, qrcode: str | None = None) -> dict[str, Any]:
        ticket = qrcode or self._login_qrcode
        if not ticket:
            raise WechatIlinkError("请先获取 iLink 登录二维码")
        client = self.client or self._create_client()
        payload = await client.poll_qr_status(ticket, base_url=self._login_base_url or self.config.base_url)
        status = str(payload.get("status") or "")
        token = str(payload.get("bot_token") or "")
        if token:
            self.config.token = token
            self.config.base_url = str(payload.get("baseurl") or self.config.base_url)
            self.config.bot_wxid = str(payload.get("ilink_bot_id") or self.config.bot_wxid)
            self.client = self._create_client()
            self.media = self._create_media_resolver()
            await self._persist_state()
            logger.info("WechatIlinkAdapter 扫码登录成功: bot={} base_url={}", self.config.bot_wxid, self.config.base_url)
            await self._ensure_polling()
        return {
            "status": status,
            "logged_in": bool(token),
            "account_id": payload.get("ilink_bot_id"),
            "ilink_user_id": payload.get("ilink_user_id"),
            "bot_wxid": self.config.bot_wxid,
            "bot_nickname": self.config.bot_nickname,
            "token_configured": bool(self.config.token),
            "base_url": payload.get("baseurl") or self.config.base_url,
        }

    async def _poll_loop(self) -> None:
        while self.started:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except WechatIlinkError as exc:
                if exc.code == -408:
                    logger.info(
                        "WechatIlinkAdapter 长轮询超时，{} 秒后继续等待消息: {}",
                        self.config.poll_interval_seconds,
                        exc,
                    )
                else:
                    logger.warning(
                        "WechatIlinkAdapter 轮询失败，{} 秒后重试: {}",
                        self.config.poll_interval_seconds,
                        exc,
                    )
                await asyncio.sleep(self.config.poll_interval_seconds)
            except Exception as exc:
                logger.warning("WechatIlinkAdapter 轮询异常，{} 秒后重试: {}", self.config.poll_interval_seconds, exc)
                await asyncio.sleep(self.config.poll_interval_seconds)

    async def _poll_once(self) -> None:
        client = self.client or self._create_client()
        payload = await client.get_updates(self.cursor)
        self.cursor = str(payload.get("get_updates_buf") or self.cursor)
        await self._persist_state()
        messages = [item for item in payload.get("msgs", []) if isinstance(item, dict)]
        for raw in messages:
            if raw.get("message_type") != 1:
                continue
            message = await self.normalize(raw)
            if not message.content:
                continue
            if self._should_defer_media_message(message):
                logger.info(
                    "WechatIlinkAdapter 暂存媒体消息但不触发 Agent: id={} type={} conversation={} content={}",
                    message.id,
                    message.type,
                    message.conversation_id,
                    self._preview(message.content),
                )
                continue
            if self.queue is None:
                logger.warning("WechatIlinkAdapter 未配置消息队列，消息不会进入框架: {}", message.id)
                continue
            logger.info(
                "WechatIlinkAdapter 发布消息到队列: id={} conversation={} sender={} type={} content={}",
                message.id,
                message.conversation_id,
                message.sender_id,
                message.type,
                self._preview(message.content),
            )
            await self.queue.publish(MessageEnvelope.from_message(message))

    async def _ensure_polling(self) -> None:
        if not self.started or not self.queue or self._task is not None:
            return
        if not self.config.token:
            return
        self._task = asyncio.create_task(self._poll_loop(), name="xbot-wechat-ilink-adapter")

    async def _print_login_qrcode(self) -> None:
        try:
            data = await self.get_login_qrcode()
        except Exception as exc:
            logger.warning("WechatIlinkAdapter 未配置 token，且获取扫码登录二维码失败: {}", exc)
            return
        qr_url = data.get("qr_url") or ""
        qrcode = data.get("qrcode") or ""
        if qr_url:
            logger.info("WechatIlinkAdapter 等待扫码登录，请打开二维码链接: {}", qr_url)
        elif qrcode:
            logger.info("WechatIlinkAdapter 等待扫码登录，qrcode={}", qrcode)
        else:
            logger.warning("WechatIlinkAdapter 未配置 token，且扫码接口未返回二维码链接")
            return
        if self._login_task is None:
            self._login_task = asyncio.create_task(
                self._login_status_loop(),
                name="xbot-wechat-ilink-login",
            )

    async def _login_status_loop(self) -> None:
        last_status = ""
        while self.started and not self.config.token and self._login_qrcode:
            try:
                result = await self.poll_login_status()
                status = str(result.get("status") or "")
                if status and status != last_status:
                    logger.info("WechatIlinkAdapter 扫码登录状态: {}", status)
                    last_status = status
                if result.get("logged_in"):
                    logger.info("WechatIlinkAdapter 扫码登录态已保存，开始轮询消息")
                    self._login_task = None
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("WechatIlinkAdapter 检查扫码登录状态失败: {}", exc)
            await asyncio.sleep(max(1.0, float(self.config.poll_interval_seconds or 1.0)))
        self._login_task = None

    def _create_client(self):
        if self.client_factory:
            return self.client_factory()
        return WechatIlinkClient(
            base_url=self.config.base_url,
            token=self.config.token,
            timeout_seconds=self.config.connect_timeout_seconds,
            cdn_base_url=self.config.cdn_base_url,
        )

    def _create_media_resolver(self):
        return WechatIlinkMediaResolver(self.config, client=self.client or self._create_client())

    async def _restore_state(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            state = await repo.get_state(self.name)
        if not state:
            return
        self.config.token = str(state.get("token") or self.config.token)
        self.config.base_url = str(state.get("base_url") or self.config.base_url)
        self.config.bot_wxid = str(state.get("bot_wxid") or self.config.bot_wxid)
        self.config.bot_nickname = str(state.get("bot_nickname") or self.config.bot_nickname)
        self.cursor = str(state.get("cursor") or self.cursor)
        logger.info("WechatIlinkAdapter 已从持久化状态恢复登录态: bot={} cursor={}", self.config.bot_wxid, bool(self.cursor))

    async def _persist_state(self) -> None:
        if not self.repository_provider:
            return
        state = {
            "base_url": self.config.base_url,
            "token": self.config.token,
            "cursor": self.cursor,
            "bot_wxid": self.config.bot_wxid,
            "bot_nickname": self.config.bot_nickname,
        }
        async with self.repository_provider() as repo:
            await repo.set_state(self.name, state)

    def _remember_reply_target(self, conversation_id: str, to_user_id: str, context_token: str) -> None:
        if not to_user_id or not context_token:
            return
        self._reply_targets[conversation_id] = {
            "to_user_id": to_user_id,
            "context_token": context_token,
        }

    async def _parse_items(
        self,
        items: list[dict],
        *,
        conversation_id: str,
        msg_id: str,
    ) -> tuple[str, str, list[dict], dict | None]:
        parts: list[str] = []
        attachments: list[dict] = []
        quote = None
        message_type = "text"
        for item in items:
            item_quote = await self._quote_from_item(item, conversation_id=conversation_id)
            if item_quote and not quote:
                quote = item_quote
            item_type = item.get("type")
            if item_type == 1:
                text = str((item.get("text_item") or {}).get("text") or "")
                if text:
                    parts.append(text)
            elif item_type == 2:
                message_type = "image"
                parts.append("[图片]")
                attachment = await self._attachment_from_item(
                    item,
                    conversation_id=conversation_id,
                    msg_id=msg_id,
                    quoted=False,
                )
                if attachment:
                    attachments.append(attachment)
            elif item_type == 3:
                message_type = "event"
                voice_text = str((item.get("voice_item") or {}).get("text") or "")
                parts.append(voice_text or "[语音]")
            elif item_type == 4:
                message_type = "file"
                file_item = item.get("file_item") or {}
                filename = str(file_item.get("file_name") or "[文件]")
                parts.append(filename)
                attachment = await self._attachment_from_item(
                    item,
                    conversation_id=conversation_id,
                    msg_id=msg_id,
                    quoted=False,
                )
                if attachment:
                    attachments.append(attachment)
            elif item_type == 5:
                message_type = "event"
                parts.append("[视频]")
        return message_type, "\n".join(part for part in parts if part).strip(), attachments, quote

    def _should_defer_media_message(self, message: Message) -> bool:
        if message.adapter != self.name or message.type not in {"image", "file"}:
            return False
        return not isinstance(message.raw.get("quote"), dict)

    async def _quote_from_item(self, item: dict, *, conversation_id: str) -> dict | None:
        ref = item.get("ref_msg")
        if not isinstance(ref, dict):
            return None
        message_item = ref.get("message_item")
        if not isinstance(message_item, dict):
            return None
        quote_type, quote_content, quote_attachments = await self._media_item_summary(
            message_item,
            conversation_id=conversation_id,
            msg_id=str(ref.get("message_id") or ref.get("msg_id") or ""),
        )
        return {
            "message_id": str(ref.get("message_id") or ref.get("msg_id") or ""),
            "sender_wxid": str(ref.get("from_user_id") or ""),
            "sender_name": str(ref.get("from_nickname") or ""),
            "msg_type": quote_type,
            "content": quote_content,
            "attachments": quote_attachments,
            "raw": ref,
        }

    async def _media_item_summary(self, item: dict, *, conversation_id: str, msg_id: str) -> tuple[str, str, list[dict]]:
        item_type = item.get("type")
        if item_type == 2:
            image_item = item.get("image_item") or {}
            filename = str(image_item.get("file_name") or image_item.get("filename") or "image")
            attachment = await self._attachment_from_item(
                item,
                conversation_id=conversation_id,
                msg_id=msg_id,
                quoted=True,
            )
            return "image", "[图片]", [attachment] if attachment else [{"kind": "image", "filename": filename, "raw": image_item}]
        if item_type == 4:
            file_item = item.get("file_item") or {}
            filename = str(file_item.get("file_name") or file_item.get("filename") or "[文件]")
            attachment = await self._attachment_from_item(
                item,
                conversation_id=conversation_id,
                msg_id=msg_id,
                quoted=True,
            )
            return "file", filename, [attachment] if attachment else [{"kind": "file", "filename": filename, "raw": file_item}]
        if item_type == 5:
            video_item = item.get("video_item") or {}
            filename = str(video_item.get("file_name") or video_item.get("filename") or "video")
            attachment = await self._attachment_from_item(
                item,
                conversation_id=conversation_id,
                msg_id=msg_id,
                quoted=True,
            )
            return "video", "[视频]", [attachment] if attachment else [{"kind": "video", "filename": filename, "raw": video_item}]
        if item_type == 3:
            voice_item = item.get("voice_item") or {}
            return "voice", str(voice_item.get("text") or "[语音]"), [{"kind": "voice", "raw": voice_item}]
        return str(item_type or ""), "", []

    async def _attachment_from_item(
        self,
        item: dict,
        *,
        conversation_id: str,
        msg_id: str,
        quoted: bool,
    ) -> dict | None:
        resolver = self.media or self._create_media_resolver()
        self.media = resolver
        return await resolver.attachment_from_item(
            item,
            conversation_id=conversation_id,
            msg_id=msg_id,
            quoted=quoted,
        )

    def _preview(self, value: Any, limit: int = 500) -> str:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        value = value.replace("\r", "\\r").replace("\n", "\\n")
        return value if len(value) <= limit else value[:limit] + f"...({len(value)} chars)"

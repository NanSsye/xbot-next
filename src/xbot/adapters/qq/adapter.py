from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import aiohttp

from xbot.adapters.base import BaseAdapter
from xbot.adapters.qq.client import QQBotApiError, QQBotClient, _assert_public_url
from xbot.core.config import QQAdapterConfig
from xbot.core.logging import logger
from xbot.messaging.models import Message, MessageEnvelope, Reply
from xbot.messaging.queue import MessageQueue


class _ReconnectGatewayError(RuntimeError):
    pass


class QQAdapter(BaseAdapter):
    name = "qq"
    platform = "qq"
    MESSAGE_EVENTS: ClassVar[set[str]] = {
        "C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE",
        "AT_MESSAGE_CREATE", "MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE",
    }
    AUXILIARY_EVENTS: ClassVar[set[str]] = {
        "INTERACTION_CREATE", "MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE",
        "PUBLIC_GUILD_MESSAGES", "AUDIT_PASS", "AUDIT_FAIL", "GUILD_CREATE",
        "GROUP_MSG_RECEIVE", "GROUP_MSG_REJECT",
    }
    INVALID_SESSION_CLOSE_CODES: ClassVar[set[int]] = {4006, 4007}
    PASSIVE_REPLY_LIMITS: ClassVar[dict[str, int]] = {"c2c": 4, "group": 5}

    def __init__(
        self,
        config: QQAdapterConfig,
        queue: MessageQueue | None = None,
        client_factory=None,
        repository_provider=None,
    ) -> None:
        self.config = config
        self.queue = queue
        self.client_factory = client_factory
        self.repository_provider = repository_provider
        self.client: QQBotClient | None = None
        self.started = False
        self.connected = False
        self.session_id = ""
        self.sequence: int | None = None
        self.bot_id = ""
        self.bot_name = ""
        self.last_error = ""
        self.last_event_type = ""
        self._gateway_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._reply_targets: dict[str, dict[str, str]] = {}
        self._reply_sequences: dict[str, int] = {}
        self._sent_message_ids: dict[str, set[str]] = {}
        self._recall_tasks: set[asyncio.Task] = set()
        self._stream_ids: dict[str, str] = {}
        self._stream_indexes: dict[str, int] = {}
        # Keep the triggering message id alongside the sequence.  A stream is
        # scoped to the message that opened it; reusing only the conversation
        # key would let an unfinished stream consume a later message's
        # passive-reply quota.
        self._stream_reply_sequences: dict[str, tuple[str, int]] = {}

    async def start(self) -> None:
        if self.started:
            return
        self.started = False
        self.last_error = ""
        if not self.config.app_id or not self.config.client_secret:
            self.last_error = "请配置 QQ AppID 与 AppSecret"
            logger.warning("QQAdapter 未启动 Gateway: {}", self.last_error)
            return
        await self._restore_state()
        self.client = self.client or self._create_client()
        self.started = True
        if self.queue and self._gateway_task is None:
            self._gateway_task = asyncio.create_task(
                self._gateway_loop(),
                name="xbot-qq-gateway",
            )

    async def stop(self) -> None:
        self.started = False
        self.connected = False
        recall_tasks = list(self._recall_tasks)
        for task in recall_tasks:
            task.cancel()
        if recall_tasks:
            await asyncio.gather(*recall_tasks, return_exceptions=True)
        self._recall_tasks.clear()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._gateway_task:
            self._gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gateway_task
            self._gateway_task = None
        if self.client:
            await self.client.close()
            self.client = None

    async def send(self, reply: Reply) -> dict[str, Any] | None:
        target = self._reply_targets.get(reply.conversation_id) or self._target_from_conversation(
            reply.conversation_id
        )
        if not target:
            logger.warning("QQAdapter 找不到回发目标")
            return
        if target["target_type"] in {"channel", "dms", "dm"} and not self.config.channel_enabled:
            raise QQBotApiError("QQ 频道能力未启用")
        metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
        current_conversation = str(metadata.get("current_conversation_id") or "")
        if current_conversation and current_conversation != reply.conversation_id:
            # An admin may intentionally target another QQ conversation, but
            # the current turn's passive reference must never follow it.
            metadata = {
                key: value
                for key, value in metadata.items()
                if key not in {"event_id", "msg_id", "msg_seq", "message_reference", "quote_message_id"}
            }
            reply = reply.model_copy(update={"metadata": metadata, "quote_message_id": None})
        # Normalize the public quote field and low-level metadata reference so
        # the passive gate, msg_seq allocation and platform limits agree.
        reference_message_id = str(reply.quote_message_id or metadata.get("msg_id") or "") or None
        if reference_message_id and metadata.get("event_id"):
            raise QQBotApiError("QQ 回复不能同时携带 msg_id 与 event_id")
        if metadata.get("msg_seq") is not None and not reference_message_id:
            raise QQBotApiError("QQ msg_seq 必须随 msg_id 被动回复")
        if metadata.get("event_id") and metadata.get("msg_seq") is not None:
            raise QQBotApiError("QQ event_id 被动回复不能携带 msg_seq")
        if metadata.get("is_wakeup") and (reference_message_id or metadata.get("event_id")):
            raise QQBotApiError("QQ is_wakeup 主动消息不能携带消息引用")
        has_passive_reference = bool(reference_message_id or metadata.get("event_id"))
        if not has_passive_reference and not self.config.allow_active_messages:
            logger.warning("QQAdapter 拒绝未携带触发消息引用的主动消息")
            return
        client = self.client or self._create_client()
        self.client = client
        reference = {
            "msg_id": reference_message_id,
            "event_id": metadata.get("event_id"),
            "msg_seq": metadata.get("msg_seq"),
            "is_wakeup": metadata.get("is_wakeup"),
            "message_reference": metadata.get("message_reference"),
        }
        reference = {key: value for key, value in reference.items() if value is not None}
        if reply.type == "reaction":
            metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
            if target["target_type"] != "channel":
                raise QQBotApiError("QQ reaction 仅支持频道")
            message_id = str(metadata.get("message_id") or reply.quote_message_id or "").strip()
            reaction_id = str(metadata.get("reaction_id") or "").strip()
            reaction_type = str(metadata.get("reaction_type") or "emoji").strip()
            method = str(metadata.get("method") or "PUT").upper()
            if not message_id or not reaction_id:
                raise QQBotApiError("QQ reaction 缺少 message_id/reaction_id")
            if method not in {"PUT", "DELETE"}:
                raise QQBotApiError("QQ reaction method 只支持 PUT 或 DELETE")
            result = await client.react(
                channel_id=target["target_id"], message_id=message_id,
                reaction_type=reaction_type, reaction_id=reaction_id, method=method,
            )
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        # Channel and DM APIs have a different request schema (no msg_type and
        # no C2C/group file_info).  Route them before the v2 user/group paths.
        if target["target_type"] in {"channel", "dms", "dm"}:
            metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
            if reply.type in {"file", "voice", "video", "card", "stream", "input_notify"}:
                raise QQBotApiError("QQ 频道/私信不支持该普通机器人消息类型")
            if reply.type == "image" and not self.config.media_enabled:
                raise QQBotApiError("QQ 媒体能力未启用")
            channel_image = None
            if reply.type == "image":
                # Reply.content is user-visible text and must not be silently
                # treated as an image URL.  Explicit metadata sources are
                # validated/uploaded by the channel client.
                channel_image = metadata.get("image") or metadata.get("url") or metadata.get("path")
                if not channel_image:
                    raise QQBotApiError("QQ 频道图片回复缺少 image/url/path")
            result = await client.send_channel(
                target_type=target["target_type"], target_id=target["target_id"],
                content=reply.content if reply.type == "text" else str(metadata.get("content") or ""),
                markdown=metadata.get("markdown") if reply.type in {"markdown", "keyboard"} else None,
                embed=metadata.get("embed") if reply.type == "embed" else None,
                ark=metadata.get("ark") if reply.type == "ark" else None,
                image=channel_image,
                **reference,
            )
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        if reply.type == "text":
            return await self._send_text_reply(client, target, reply, reference)
        if reply.type in {"markdown", "keyboard"}:
            markdown = reply.metadata.get("markdown", reply.content)
            keyboard = reply.metadata.get("keyboard") if isinstance(reply.metadata, dict) else None
            if reply.type == "keyboard" and keyboard is None:
                raise QQBotApiError("keyboard 回复缺少 metadata.keyboard")
            reference = self._prepare_passive_reference(target, reference)
            try:
                result = await client.send_markdown(
                    target_type=target["target_type"], target_id=target["target_id"],
                    content=markdown, keyboard=keyboard, **reference,
                )
            except QQBotApiError as exc:
                fallback_text = str(reply.metadata.get("fallback_text") or "").strip()
                can_fallback = bool(fallback_text) and (
                    exc.status in {400, 403} or exc.err_code not in {None, "", 0, "0"}
                )
                if not can_fallback:
                    raise
                logger.warning(
                    "QQ Markdown 不可用，自动回退文本: status={} err_code={} trace_id={}",
                    exc.status,
                    exc.err_code,
                    exc.trace_id,
                )
                result = await client.send_text(
                    target_type=target["target_type"],
                    target_id=target["target_id"],
                    content=fallback_text[: max(100, int(self.config.max_reply_chars))],
                    **reference,
                )
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        if reply.type in {"image", "file", "voice", "video"}:
            if not self.config.media_enabled:
                raise QQBotApiError("QQ 媒体能力未启用")
            metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
            file_info = metadata.get("file_info")
            if not file_info:
                source = metadata.get("url") or metadata.get("path") or reply.content
                if not source:
                    raise QQBotApiError("QQ 媒体回复缺少 url/path/file_info")
                upload = await client.upload_media(
                    target_type=target["target_type"], target_id=target["target_id"],
                    source=source, media_type=reply.type, file_name=str(metadata.get("file_name") or ""),
                )
                file_info = upload.get("file_info")
            reference = self._prepare_passive_reference(target, reference)
            result = await client.send_media(
                target_type=target["target_type"], target_id=target["target_id"],
                file_info=file_info, **reference,
            )
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        if reply.type == "stream":
            if target["target_type"] not in {"c2c", "user"}:
                raise QQBotApiError("QQ 流式消息仅支持单聊")
            metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
            input_state = int(metadata.get("input_state", metadata.get("state", 1)) or 1)
            reference = self._prepare_stream_reference(
                target, reference, reply.conversation_id,
            )
            stream_msg_id = str(metadata.get("stream_msg_id") or self._stream_ids.get(reply.conversation_id) or "") or None
            explicit_index = metadata.get("index")
            index = (
                int(explicit_index)
                if explicit_index is not None
                else self._stream_indexes.get(reply.conversation_id, 0)
            )
            if index < 0:
                raise QQBotApiError("QQ 流式消息 index 不能为负数")
            try:
                result = await client.stream_message(
                    target_id=target["target_id"], content=reply.content,
                    input_mode=str(metadata.get("input_mode") or "append"),
                    input_state=input_state, index=index,
                    content_type=str(metadata.get("content_type") or "text"),
                    stream_msg_id=stream_msg_id, **reference,
                )
            except Exception:
                self._clear_stream_state(reply.conversation_id)
                raise
            returned_stream_id = str(result.get("stream_msg_id") or result.get("streamMsgId") or result.get("id") or stream_msg_id or "") if isinstance(result, dict) else ""
            if input_state == 10:
                self._clear_stream_state(reply.conversation_id)
            elif returned_stream_id:
                self._stream_ids[reply.conversation_id] = returned_stream_id
                self._stream_indexes[reply.conversation_id] = index + 1
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        if reply.type == "input_notify":
            if target["target_type"] not in {"c2c", "user"}:
                raise QQBotApiError("QQ 输入中状态仅支持单聊")
            seconds = int((reply.metadata or {}).get("input_second") or reply.content or 5)
            reference = self._prepare_passive_reference(target, reference)
            result = await client.input_notify(target_id=target["target_id"], input_second=seconds, **reference)
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        if reply.type in {"embed", "ark"}:
            metadata = reply.metadata if isinstance(reply.metadata, dict) else {}
            result = await client.send_channel(
                target_type=target["target_type"], target_id=target["target_id"],
                content=reply.content if reply.type == "text" else str(metadata.get("content") or reply.content or ""),
                markdown=metadata.get("markdown") if reply.type == "markdown" else None,
                embed=metadata.get("embed") if reply.type == "embed" else None,
                ark=metadata.get("ark") if reply.type == "ark" else None,
                image=metadata.get("image"), **reference,
            )
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            return result
        raise QQBotApiError(f"不支持的 QQ Reply 类型: {reply.type}")

    async def _send_text_reply(self, client, target: dict[str, str], reply: Reply, reference: dict[str, Any]) -> dict[str, Any]:
        chunk_limit = max(100, int(self.config.max_reply_chars))
        chunks = self._split_text(reply.content, chunk_limit)
        reference_message_id = str(reference.get("msg_id") or "") or None
        has_passive_reference = bool(reference_message_id or reference.get("event_id"))
        if has_passive_reference and target["target_type"] in self.PASSIVE_REPLY_LIMITS:
            passive_limit = self.PASSIVE_REPLY_LIMITS[target["target_type"]]
            explicit_seq = reference.get("msg_seq")
            if reference.get("event_id") and explicit_seq is not None:
                raise QQBotApiError("QQ event_id 被动回复不能携带 msg_seq")
            if reference_message_id:
                current_seq = self._reply_sequences.get(reference_message_id, 0)
                if explicit_seq is not None:
                    try:
                        start_seq = int(explicit_seq)
                    except (TypeError, ValueError) as exc:
                        raise QQBotApiError("QQ msg_seq 必须是正整数") from exc
                    if start_seq < 1 or start_seq <= current_seq:
                        raise QQBotApiError("QQ msg_seq 必须递增且从 1 开始")
                else:
                    start_seq = current_seq + 1
                if start_seq > passive_limit:
                    raise QQBotApiError("QQ 被动回复次数已达到平台限制")
                remaining = passive_limit - start_seq + 1
            else:
                # Interaction event_id references do not use msg_seq, but are
                # still subject to the per-call platform chunk cap.
                start_seq = None
                remaining = passive_limit
            if len(chunks) > remaining:
                logger.warning(
                    "QQAdapter 被动回复超过平台次数限制，内容将截断: target_type={} chunks={} limit={}",
                    target["target_type"],
                    len(chunks),
                    remaining,
                )
                chunks = self._truncate_reply_chunks(chunks, remaining, chunk_limit)
        elif reference.get("event_id") and reference.get("msg_seq") is not None:
            raise QQBotApiError("QQ event_id 被动回复不能携带 msg_seq")
        message_ids: list[str] = []
        for offset, chunk in enumerate(chunks):
            params = dict(reference)
            sent_seq = None
            if reference_message_id:
                if reference.get("msg_seq") is not None:
                    sent_seq = int(reference["msg_seq"]) + offset
                    params["msg_seq"] = sent_seq
                else:
                    sent_seq = self._next_reply_sequence(reference_message_id)
                    params["msg_seq"] = sent_seq
            result = await client.send_text(
                target_type=target["target_type"],
                target_id=target["target_id"],
                content=chunk,
                **params,
            )
            if reference_message_id and sent_seq is not None:
                self._reply_sequences[reference_message_id] = max(
                    self._reply_sequences.get(reference_message_id, 0), sent_seq
                )
            self._record_sent(reply.conversation_id, result, self._recall_delay(reply))
            if isinstance(result, dict):
                message_id = str(result.get("id") or result.get("message_id") or "")
                if message_id:
                    message_ids.append(message_id)
        return {
            "message_id": message_ids[-1] if message_ids else "",
            "message_ids": message_ids,
        }

    def _prepare_passive_reference(
        self,
        target: dict[str, str],
        reference: dict[str, Any],
    ) -> dict[str, Any]:
        """Assign one safe msg_seq for a non-text passive message.

        QQ's c2c/group passive quota is shared by all message types.  The
        sequence cache therefore spans text, rich media, streams and
        input-notify calls for the same triggering msg_id.
        """
        if reference.get("event_id") and reference.get("msg_seq") is not None:
            raise QQBotApiError("QQ event_id 被动回复不能携带 msg_seq")
        message_id = str(reference.get("msg_id") or "") or None
        if not message_id or target["target_type"] not in self.PASSIVE_REPLY_LIMITS:
            return reference
        passive_limit = self.PASSIVE_REPLY_LIMITS[target["target_type"]]
        current_seq = self._reply_sequences.get(message_id, 0)
        explicit_seq = reference.get("msg_seq")
        if explicit_seq is None:
            next_seq = current_seq + 1
        else:
            try:
                next_seq = int(explicit_seq)
            except (TypeError, ValueError) as exc:
                raise QQBotApiError("QQ msg_seq 必须是正整数") from exc
            if next_seq < 1 or next_seq <= current_seq:
                raise QQBotApiError("QQ msg_seq 必须递增且从 1 开始")
        if next_seq > passive_limit:
            raise QQBotApiError("QQ 被动回复次数已达到平台限制")
        updated = dict(reference)
        updated["msg_seq"] = next_seq
        self._reply_sequences[message_id] = next_seq
        return updated

    def _prepare_stream_reference(
        self,
        target: dict[str, str],
        reference: dict[str, Any],
        conversation_id: str,
    ) -> dict[str, Any]:
        message_id = str(reference.get("msg_id") or "") or None
        if not message_id or target["target_type"] not in self.PASSIVE_REPLY_LIMITS:
            return self._prepare_passive_reference(target, reference)
        cached = self._stream_reply_sequences.get(conversation_id)
        if cached is not None and cached[0] != message_id:
            # A new incoming message starts a new stream even if the previous
            # stream did not send its terminal state yet.  Drop its stream id,
            # index and sequence binding before allocating the new sequence.
            self._clear_stream_state(conversation_id)
            cached = None
        cached_seq = cached[1] if cached is not None else None
        if cached_seq is not None:
            explicit_seq = reference.get("msg_seq")
            if explicit_seq is not None:
                try:
                    if int(explicit_seq) != cached_seq:
                        raise QQBotApiError("QQ 流式分片必须复用首片 msg_seq")
                except (TypeError, ValueError) as exc:
                    raise QQBotApiError("QQ msg_seq 必须是正整数") from exc
            updated = dict(reference)
            updated["msg_seq"] = cached_seq
            return updated
        updated = self._prepare_passive_reference(target, reference)
        if updated.get("msg_seq") is not None:
            self._stream_reply_sequences[conversation_id] = (
                message_id,
                int(updated["msg_seq"]),
            )
        return updated

    def _clear_stream_state(self, conversation_id: str) -> None:
        self._stream_ids.pop(conversation_id, None)
        self._stream_indexes.pop(conversation_id, None)
        self._stream_reply_sequences.pop(conversation_id, None)

    async def recall(self, conversation_id: str, message_id: str) -> dict[str, Any]:
        """Recall only a message previously sent and recorded by this adapter."""
        target = self._reply_targets.get(conversation_id) or self._target_from_conversation(conversation_id)
        if not target:
            raise QQBotApiError("找不到 QQ 会话目标")
        if message_id not in self._sent_message_ids.get(conversation_id, set()):
            raise QQBotApiError("QQAdapter 只允许撤回本次适配器记录的机器人消息")
        client = self.client or self._create_client()
        self.client = client
        result = await client.delete_message(target_type=target["target_type"], target_id=target["target_id"], message_id=message_id)
        self._sent_message_ids.get(conversation_id, set()).discard(message_id)
        return result

    async def react(self, conversation_id: str, *, message_id: str, reaction_type: str, reaction_id: str, method: str = "PUT") -> dict[str, Any]:
        target = self._reply_targets.get(conversation_id) or self._target_from_conversation(conversation_id)
        if not target or target["target_type"] != "channel":
            raise QQBotApiError("QQ reaction 仅支持频道会话")
        client = self.client or self._create_client()
        self.client = client
        return await client.react(
            channel_id=target["target_id"], message_id=message_id,
            reaction_type=reaction_type, reaction_id=reaction_id, method=method,
        )

    @staticmethod
    def _recall_delay(reply: Reply) -> float:
        try:
            return max(0.0, min(float((reply.metadata or {}).get("auto_recall_seconds") or 0), 120.0))
        except (TypeError, ValueError):
            return 0.0

    def _record_sent(
        self,
        conversation_id: str,
        result: Any,
        recall_after: float = 0.0,
    ) -> None:
        if not isinstance(result, dict):
            return
        message_id = str(result.get("id") or result.get("message_id") or "")
        if not message_id:
            return
        bucket = self._sent_message_ids.setdefault(conversation_id, set())
        bucket.add(message_id)
        if len(bucket) > 2000:
            bucket.pop()
        if recall_after > 0:
            task = asyncio.create_task(
                self._recall_later(conversation_id, message_id, recall_after),
                name=f"xbot-qq-recall-{message_id[:16]}",
            )
            self._recall_tasks.add(task)
            task.add_done_callback(self._recall_tasks.discard)

    async def _recall_later(
        self,
        conversation_id: str,
        message_id: str,
        delay_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            await self.recall(conversation_id, message_id)
            logger.info("QQAdapter 已自动撤回机器人消息: conversation={}", conversation_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "QQAdapter 自动撤回失败: conversation={} error={}",
                conversation_id,
                exc,
            )

    async def normalize(self, raw: dict) -> Message:
        event_type = str(raw.get("_event_type") or raw.get("t") or "")
        payload = raw.get("d") if isinstance(raw.get("d"), dict) else raw
        payload = dict(payload)
        author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        interaction_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        resolved = interaction_data.get("resolved") if isinstance(interaction_data.get("resolved"), dict) else payload.get("resolved") if isinstance(payload.get("resolved"), dict) else {}
        scene_value = payload.get("scene")
        scene = scene_value if isinstance(scene_value, dict) else {}
        scene_name = str(scene_value or "").strip().lower() if isinstance(scene_value, str) else ""
        button_data = str(resolved.get("button_data") or interaction_data.get("button_data") or payload.get("button_data") or "")
        button_id = str(resolved.get("button_id") or interaction_data.get("button_id") or payload.get("button_id") or "")
        if event_type == "INTERACTION_CREATE":
            # Interaction payloads use top-level OpenIDs rather than the
            # message ``author`` object.  Keep the event readable and avoid
            # inventing a group/channel target when none was supplied.
            interaction_user = payload.get("user") if isinstance(payload.get("user"), dict) else interaction_data.get("user") if isinstance(interaction_data.get("user"), dict) else {}
            sender_id = str(
                payload.get("user_openid")
                or payload.get("group_member_openid")
                or payload.get("user_id")
                or scene.get("user_openid")
                or resolved.get("user_id")
                or interaction_user.get("openid")
                or interaction_user.get("id")
                or author.get("id")
                or "unknown_qq_user"
            )
            group_id = payload.get("group_openid") or interaction_data.get("group_openid") or scene.get("group_openid")
            channel_id = payload.get("channel_id") or interaction_data.get("channel_id") or scene.get("channel_id")
            guild_id = payload.get("guild_id") or interaction_data.get("guild_id") or scene.get("guild_id")
            if scene_name == "group" and not group_id:
                group_id = payload.get("openid") or interaction_data.get("openid")
            interaction_event_id = str(
                raw.get("event_id")
                or raw.get("id")
                or payload.get("event_id")
                or payload.get("id")
                or ""
            )
            if group_id:
                target_id, conversation_id, scope, target_type = str(group_id), f"qq:group:{group_id}", "group", "group"
            elif channel_id:
                target_id, conversation_id, scope, target_type = str(channel_id), f"qq:channel:{channel_id}", "channel", "channel"
            elif guild_id:
                target_id, conversation_id, scope, target_type = str(guild_id), f"qq:dms:{guild_id}", "private", "dms"
            else:
                target_id, conversation_id, scope, target_type = sender_id, f"qq:c2c:{sender_id}", "private", "c2c"
            event_content = str(payload.get("content") or interaction_data.get("content") or button_data or button_id or payload.get("command") or "interaction")
            try:
                normalized_interaction_type = int(payload.get("type") or interaction_data.get("type") or 0)
            except (TypeError, ValueError):
                normalized_interaction_type = 0
            payload.update({
                "scope": scope, "message_id": interaction_event_id,
                "sender_openid": sender_id, "conversation_openid": target_id,
                "group_openid": target_id if scope == "group" else "",
                "user_openid": sender_id if scope == "private" else "",
                "member_openid": sender_id if scope == "group" else "",
                "mentions_bot": False, "bot_id": self.bot_id, "bot_name": self.bot_name,
                "attachments": [], "qq_event_type": event_type,
                "gateway_event_id": str(raw.get("id") or ""), "event_id": interaction_event_id,
                "interaction_type": normalized_interaction_type,
                "button_data": button_data, "button_id": button_id,
                "agent_route": normalized_interaction_type in {11, 12},
            })
            self._remember_reply_target(conversation_id, target_type, target_id)
            return Message(
                id=str(payload.get("message_id") or interaction_event_id), platform=self.platform, adapter=self.name,
                type="event", conversation_id=conversation_id, sender_id=sender_id,
                sender_name=str(author.get("username") or ""), content=event_content, raw=payload,
                timestamp=self._parse_timestamp(payload.get("timestamp")) or datetime.now(UTC).replace(tzinfo=None),
            )
        is_channel = bool(payload.get("channel_id")) or event_type in {
            "AT_MESSAGE_CREATE", "MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE"
        }
        is_dm = event_type == "DIRECT_MESSAGE_CREATE" or bool(payload.get("guild_id") and author.get("id") and not payload.get("channel_id"))
        is_group = not is_channel and (event_type in {"GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"} or bool(payload.get("group_openid")))
        sender_id = str(
            author.get("member_openid")
            or author.get("user_openid")
            or author.get("id")
            or "unknown_qq_user"
        )
        if is_channel and is_dm:
            target_id = str(payload.get("guild_id") or payload.get("channel_id") or sender_id)
            conversation_id = f"qq:dms:{target_id}"
            scope = "private"
            target_type = "dms"
        elif is_channel:
            target_id = str(payload.get("channel_id") or "unknown_qq_channel")
            conversation_id = f"qq:channel:{target_id}"
            scope = "channel"
            target_type = "channel"
        elif is_group:
            target_id = str(payload.get("group_openid") or "unknown_qq_group")
            conversation_id = f"qq:group:{target_id}"
            scope = "group"
            target_type = "group"
        else:
            target_id = str(author.get("user_openid") or author.get("id") or sender_id)
            conversation_id = f"qq:c2c:{target_id}"
            scope = "private"
            target_type = "c2c"
        message_id = str(payload.get("id") or raw.get("id") or "")
        attachments = await self._normalize_attachments(
            payload.get("attachments"), message_id=message_id, conversation_id=conversation_id,
        )
        quoted_raw_attachments: list[dict[str, Any]] = []
        message_scene = payload.get("message_scene")
        scene_ext = message_scene.get("ext") if isinstance(message_scene, dict) else []
        has_reference = str(payload.get("message_type") or "") == "103" or any(
            str(item).startswith("ref_msg_idx=") for item in scene_ext or []
        )
        if has_reference and isinstance(payload.get("msg_elements"), list):
            for element in payload["msg_elements"]:
                if not isinstance(element, dict) or not isinstance(element.get("attachments"), list):
                    continue
                quoted_raw_attachments.extend(
                    item for item in element["attachments"] if isinstance(item, dict)
                )
        quote_attachments = await self._normalize_attachments(
            quoted_raw_attachments,
            message_id=f"{message_id}-quote",
            conversation_id=conversation_id,
        )
        for item in quote_attachments:
            item["quoted"] = True
        content = str(payload.get("content") or "").strip()
        message_type = "text"
        if attachments:
            kinds = {str(item.get("kind") or "") for item in attachments}
            if "image" in kinds:
                message_type = "image"
            elif "video" in kinds:
                message_type = "video"
            elif "voice" in kinds:
                message_type = "voice"
            elif "file" in kinds:
                message_type = "file"
            if not content:
                content = "\n".join(
                    {"image": "[图片]", "video": "[视频]", "voice": "[语音]"}.get(
                        str(item.get("kind") or ""), str(item.get("filename") or "[文件]")
                    )
                    for item in attachments
                )
        mentions = payload.get("mentions") if isinstance(payload.get("mentions"), list) else []
        mentioned_bot = event_type in {"GROUP_AT_MESSAGE_CREATE", "AT_MESSAGE_CREATE"}
        bot_mention_ids: set[str] = set()
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            mention_ids = {
                str(value)
                for value in (
                    mention.get("id"),
                    mention.get("user_openid"),
                    mention.get("member_openid"),
                )
                if value
            }
            is_current_bot = (
                mention.get("bot") is True
                and mention.get("is_you") is True
                and str(mention.get("scope") or "single") != "all"
            )
            matches_gateway_id = bool(self.bot_id and self.bot_id in mention_ids)
            if is_current_bot or matches_gateway_id:
                mentioned_bot = True
                bot_mention_ids.update(mention_ids)
        for mention_id in bot_mention_ids:
            content = content.replace(f"<@{mention_id}>", "").replace(
                f"<@!{mention_id}>", ""
            )
        content = content.strip()
        payload.update(
            {
                "scope": scope,
                "message_id": message_id,
                "sender_openid": sender_id,
                "conversation_openid": target_id,
                "group_openid": target_id if is_group else "",
                "user_openid": target_id if not is_group and not is_channel else "",
                "member_openid": sender_id if is_group else "",
                "channel_id": target_id if is_channel and not is_dm else str(payload.get("channel_id") or ""),
                "guild_id": str(payload.get("guild_id") or "") if is_channel else "",
                "mentions_bot": mentioned_bot,
                "bot_id": self.bot_id,
                "bot_name": self.bot_name,
                "attachments": attachments,
                "quote_attachments": quote_attachments,
                "qq_event_type": event_type,
                "gateway_event_id": str(raw.get("id") or ""),
                "event_id": str(payload.get("event_id") or raw.get("id") or ""),
                "msg_seq": payload.get("seq") or payload.get("msg_seq"),
                "is_wakeup": bool(payload.get("is_wakeup")),
                "agent_route": event_type not in self.AUXILIARY_EVENTS,
            }
        )
        self._remember_reply_target(conversation_id, target_type, target_id)
        data: dict[str, Any] = {
            "platform": self.platform,
            "adapter": self.name,
            "type": message_type,
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "sender_name": str(author.get("username") or ""),
            "content": content,
            "raw": payload,
        }
        if message_id:
            data["id"] = message_id
        timestamp = self._parse_timestamp(payload.get("timestamp"))
        if timestamp is not None:
            data["timestamp"] = timestamp
        return Message(**data)

    def public_status(self) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "platform": self.platform,
            "started": self.started,
            "connected": self.connected,
            "configured": bool(self.config.app_id and self.config.client_secret),
            "app_id_configured": bool(self.config.app_id),
            "client_secret_configured": bool(self.config.client_secret),
            "gateway_running": bool(self._gateway_task and not self._gateway_task.done()),
            "session_ready": bool(self.session_id),
            "last_sequence": self.sequence,
            "bot_id": self.bot_id,
            "bot_name": self.bot_name,
            "last_event_type": self.last_event_type,
            "last_error": self.last_error,
            "intents": self.config.intents,
        }

    async def _gateway_loop(self) -> None:
        while self.started:
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)
                logger.warning(
                    "QQAdapter Gateway 连接失败，{} 秒后重试: {}",
                    self.config.reconnect_seconds,
                    exc,
                )
            if self.started:
                await asyncio.sleep(max(1.0, float(self.config.reconnect_seconds)))

    async def _connect_once(self) -> None:
        client = self.client or self._create_client()
        self.client = client
        access_token = await client.access_token()
        gateway_url = await client.gateway_url()
        websocket = await client.websocket(gateway_url)
        heartbeat_interval = 45.0
        close_code: int | None = None
        self.connected = True
        self.last_error = ""
        logger.info("QQAdapter 已连接 Gateway: {}", gateway_url)
        try:
            hello = await websocket.receive_json(timeout=max(5.0, self.config.connect_timeout_seconds))
            if int(hello.get("op", -1)) != 10:
                raise QQBotApiError(f"QQ Gateway 首帧不是 Hello: op={hello.get('op')}")
            heartbeat_interval = max(
                1.0,
                float((hello.get("d") or {}).get("heartbeat_interval") or 45000) / 1000.0,
            )
            token = f"QQBot {access_token}"
            if self.session_id and self.sequence is not None:
                await websocket.send_json(
                    {
                        "op": 6,
                        "d": {
                            "token": token,
                            "session_id": self.session_id,
                            "seq": self.sequence,
                        },
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "op": 2,
                        "d": {
                            "token": token,
                            "intents": int(self.config.intents),
                            "shard": [0, 1],
                            "properties": {
                                "$os": "python",
                                "$browser": "xbot-next",
                                "$device": "xbot-next",
                            },
                        },
                    }
                )
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(websocket, heartbeat_interval),
                name="xbot-qq-heartbeat",
            )
            async for frame in websocket:
                if frame.type == aiohttp.WSMsgType.TEXT:
                    payload = frame.json()
                    await self._handle_gateway_payload(websocket, payload)
                elif frame.type in {
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                }:
                    if isinstance(frame.data, int):
                        close_code = frame.data
                    break
        finally:
            self.connected = False
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
                self._heartbeat_task = None
            if close_code is None:
                websocket_close_code = getattr(websocket, "close_code", None)
                if isinstance(websocket_close_code, int):
                    close_code = websocket_close_code
            await websocket.close()
        if close_code is None:
            websocket_close_code = getattr(websocket, "close_code", None)
            if isinstance(websocket_close_code, int):
                close_code = websocket_close_code
        if close_code in self.INVALID_SESSION_CLOSE_CODES:
            await self._clear_gateway_session()
            raise _ReconnectGatewayError(
                f"QQ Gateway 关闭码 {close_code} 表示 Session 已失效，将改用 Identify"
            )

    async def _handle_gateway_payload(
        self,
        websocket: aiohttp.ClientWebSocketResponse,
        payload: dict[str, Any],
    ) -> None:
        previous_sequence = self.sequence
        if payload.get("s") is not None:
            self.sequence = int(payload["s"])
        op = int(payload.get("op", -1))
        if op == 0:
            event_type = str(payload.get("t") or "")
            self.last_event_type = event_type
            if event_type == "READY":
                data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
                self.session_id = str(data.get("session_id") or self.session_id)
                user = data.get("user") if isinstance(data.get("user"), dict) else {}
                self.bot_id = str(user.get("id") or self.bot_id)
                self.bot_name = str(user.get("username") or self.bot_name)
                await self._commit_gateway_sequence(previous_sequence)
                logger.info("QQAdapter Gateway READY: bot={} session={}", self.bot_name, bool(self.session_id))
                return
            if event_type == "RESUMED":
                await self._commit_gateway_sequence(previous_sequence)
                logger.info("QQAdapter Gateway 会话恢复成功")
                return
            if event_type in self.MESSAGE_EVENTS:
                if event_type in {"AT_MESSAGE_CREATE", "MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE"} and not self.config.channel_enabled:
                    await self._commit_gateway_sequence(previous_sequence)
                    return
                raw = dict(payload)
                raw["_event_type"] = event_type
                message = await self.normalize(raw)
                if not message.content:
                    await self._commit_gateway_sequence(previous_sequence)
                    return
                await self._publish_gateway_message(message, previous_sequence)
                return
            if event_type == "INTERACTION_CREATE":
                # Discord/QQ require an interaction ACK within three seconds.
                # ACK before queueing any Agent work; a missing/failed ACK must
                # never be hidden by the eventual plugin response.
                interaction = payload.get("d") if isinstance(payload.get("d"), dict) else {}
                interaction_data = interaction.get("data") if isinstance(interaction.get("data"), dict) else {}
                interaction_id = str(
                    interaction.get("id")
                    or interaction.get("event_id")
                    or interaction_data.get("id")
                    or payload.get("id")
                    or payload.get("event_id")
                    or ""
                )
                try:
                    interaction_type = int(
                        interaction.get("type")
                        or interaction_data.get("type")
                        or 0
                    )
                except (TypeError, ValueError):
                    interaction_type = 0
                if interaction_id and interaction_type in {11, 12}:
                    try:
                        await self._interaction_ack(interaction_id)
                    except Exception as exc:
                        self.last_error = f"QQ interaction ACK 失败: {exc}"
                        logger.warning("QQAdapter interaction ACK 失败: {}", exc)
                interaction_scene = interaction.get("scene")
                interaction_scene_channel = (
                    interaction_scene.get("channel_id")
                    if isinstance(interaction_scene, dict)
                    else None
                )
                if not self.config.channel_enabled and (
                    interaction.get("channel_id")
                    or interaction.get("guild_id")
                    or interaction_scene_channel
                ):
                    await self._commit_gateway_sequence(previous_sequence)
                    return
                if interaction_type not in {11, 12}:
                    # Other interaction payloads are platform events only;
                    # they are recorded by Gateway status/logging but must not
                    # be dispatched into the auto-reply Agent route.
                    logger.info("QQAdapter 忽略非消息交互事件: type={}", interaction_type)
                    await self._commit_gateway_sequence(previous_sequence)
                    return
                message = await self.normalize({**payload, "_event_type": event_type})
                await self._publish_gateway_message(message, previous_sequence)
                return
            if event_type in self.AUXILIARY_EVENTS:
                # Reactions/audit/authorization events are represented as a
                # safe, readable event for Agent consumers.  We intentionally
                # do not issue a response for those events.
                message = await self.normalize({**payload, "_event_type": event_type})
                await self._publish_gateway_message(message, previous_sequence)
                return
            # Unknown dispatches are intentionally ignored, but their cursor
            # is still safe to commit because no framework work was dropped.
            await self._commit_gateway_sequence(previous_sequence)
            return
        if op == 1:
            await websocket.send_json({"op": 1, "d": self.sequence})
            return
        if op == 7:
            raise _ReconnectGatewayError("QQ Gateway 要求重新连接")
        if op == 9:
            await self._clear_gateway_session()
            raise _ReconnectGatewayError("QQ Gateway Session 已失效，将重新鉴权")

    async def _interaction_ack(self, interaction_id: str) -> None:
        client = self.client or self._create_client()
        self.client = client
        await client.request("PUT", f"/interactions/{interaction_id}", json={"code": 0})

    async def _publish_message(self, message: Message) -> None:
        if self.queue is None:
            logger.warning("QQAdapter 未配置消息队列，消息不会进入框架")
            return
        await self.queue.publish(MessageEnvelope.from_message(message))
        # Advance the persisted Gateway cursor only after the event is safely
        # accepted by the durable queue.  A crash before this point may replay
        # the event (at-least-once), but never silently skip it on Resume.
        await self._persist_state()
        logger.info(
            "QQAdapter 发布消息到队列: type={}",
            message.type,
        )

    async def _publish_gateway_message(
        self,
        message: Message,
        previous_sequence: int | None,
    ) -> None:
        """Queue a Gateway event and commit its cursor only on success.

        A dispatch sequence is assigned to ``self.sequence`` before event
        routing so heartbeat/resume state can see it.  If queue publication
        fails (or no queue is configured), restore the previous in-memory
        cursor so reconnecting cannot Resume past an unqueued event.
        """
        if self.queue is None:
            self.sequence = previous_sequence
            logger.warning("QQAdapter 未配置消息队列，消息不会进入框架")
            return
        try:
            await self._publish_message(message)
        except Exception:
            self.sequence = previous_sequence
            raise

    async def _commit_gateway_sequence(self, previous_sequence: int | None) -> None:
        """Persist an intentionally ignored or control dispatch cursor."""
        try:
            await self._persist_state()
        except Exception:
            self.sequence = previous_sequence
            raise

    async def _heartbeat_loop(
        self,
        websocket: aiohttp.ClientWebSocketResponse,
        interval_seconds: float,
    ) -> None:
        while self.started and not websocket.closed:
            await asyncio.sleep(interval_seconds)
            await websocket.send_json({"op": 1, "d": self.sequence})

    def _create_client(self) -> QQBotClient:
        if self.client_factory:
            return self.client_factory()
        return QQBotClient(self.config)

    async def _restore_state(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            state = await repo.get_state(self.name)
        self.session_id = str(state.get("session_id") or "")
        sequence = state.get("sequence")
        self.sequence = int(sequence) if isinstance(sequence, int) or str(sequence).isdigit() else None
        self.bot_id = str(state.get("bot_id") or "")
        self.bot_name = str(state.get("bot_name") or "")

    async def _persist_state(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            state = await repo.get_state(self.name)
            state.update(
                {
                    "session_id": self.session_id,
                    "sequence": self.sequence,
                    "bot_id": self.bot_id,
                    "bot_name": self.bot_name,
                }
            )
            await repo.set_state(self.name, state)

    async def _clear_gateway_session(self) -> None:
        self.session_id = ""
        self.sequence = None
        await self._persist_state()

    def _remember_reply_target(self, conversation_id: str, target_type: str, target_id: str) -> None:
        if len(self._reply_targets) >= 5000:
            self._reply_targets.pop(next(iter(self._reply_targets)))
        self._reply_targets[conversation_id] = {
            "target_type": target_type,
            "target_id": target_id,
        }

    def _target_from_conversation(self, conversation_id: str) -> dict[str, str] | None:
        if conversation_id.startswith("qq:group:"):
            return {"target_type": "group", "target_id": conversation_id.removeprefix("qq:group:")}
        if conversation_id.startswith("qq:c2c:"):
            return {"target_type": "c2c", "target_id": conversation_id.removeprefix("qq:c2c:")}
        if conversation_id.startswith("qq:channel:"):
            return {"target_type": "channel", "target_id": conversation_id.removeprefix("qq:channel:")}
        if conversation_id.startswith("qq:dms:"):
            return {"target_type": "dms", "target_id": conversation_id.removeprefix("qq:dms:")}
        return None

    def _next_reply_sequence(self, message_id: str) -> int:
        value = self._reply_sequences.get(message_id, 0) + 1
        self._reply_sequences[message_id] = value
        if len(self._reply_sequences) > 10000:
            self._reply_sequences.pop(next(iter(self._reply_sequences)))
        return value

    async def _normalize_attachments(self, raw_attachments: Any, *, message_id: str = "", conversation_id: str = "") -> list[dict[str, Any]]:
        if not isinstance(raw_attachments, list):
            return []
        items: list[dict[str, Any]] = []
        for item in raw_attachments:
            if not isinstance(item, dict):
                continue
            content_type = str(item.get("content_type") or "").strip().lower()
            normalized_type = content_type
            if item.get("voice_wav_url"):
                kind = "voice"
            elif normalized_type == "image" or normalized_type.startswith("image/"):
                kind = "image"
            elif normalized_type == "voice" or normalized_type.startswith("audio/"):
                kind = "voice"
            elif normalized_type == "video" or normalized_type.startswith("video/"):
                kind = "video"
            else:
                kind = "file"
            if kind == "file" and Path(str(item.get("filename") or "")).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
                kind = "image"
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            size = max(0, size)
            url = str(item.get("voice_wav_url") or item.get("url") or item.get("resource_url") or item.get("file_url") or "")
            url_name = Path(urlparse(url).path).name if url else ""
            supplied_name = str(item.get("filename") or "").strip()
            # QQ voice events commonly provide only voice_wav_url.  Prefer a
            # meaningful URL suffix over the generic ``*.bin`` fallback so
            # downstream ASR/media tooling receives a real filename.
            if (not supplied_name or Path(supplied_name).suffix.lower() in {"", ".bin"}) and url_name:
                supplied_name = url_name
            if not supplied_name and kind == "voice" and item.get("voice_wav_url"):
                supplied_name = "voice.wav"
            filename = self._safe_filename(supplied_name, kind)
            mime = self._attachment_mime(content_type, kind, filename, url)
            normalized: dict[str, Any] = {
                "kind": kind,
                "filename": filename,
                "mime": mime,
                "size": size,
                "url": url,
                "remote_url": url,
                "download_status": "remote",
                "metadata": {
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "asr_refer_text": item.get("asr_refer_text"),
                },
            }
            if item.get("asr_refer_text"):
                normalized["asr_refer_text"] = str(item.get("asr_refer_text"))
            if size > int(self.config.media_max_bytes):
                normalized["download_status"] = "rejected"
                normalized["download_error"] = "媒体超过大小硬限制"
            elif self.config.auto_download_media and self.config.media_enabled and url:
                try:
                    await self._download_attachment(normalized, message_id=message_id, conversation_id=conversation_id)
                except Exception as exc:
                    # Keep the remote attachment usable for the Agent.  The
                    # status is explicit; a failed download is never reported
                    # as a local success.
                    normalized["download_status"] = "failed"
                    normalized["download_error"] = str(exc)[:200]
            items.append(normalized)
        return items

    @staticmethod
    def _attachment_mime(content_type: str, kind: str, filename: str, url: str) -> str:
        """Infer a concrete MIME type when QQ omits media metadata."""
        if "/" in content_type and content_type != "application/octet-stream":
            return content_type
        suffix = Path(filename or urlparse(url).path).suffix.lower()
        if kind == "image":
            return {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
            }.get(suffix, "image/jpeg")
        if kind == "voice":
            return {
                ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".silk": "audio/silk",
            }.get(suffix, "audio/wav")
        if kind == "video":
            return {".mp4": "video/mp4"}.get(suffix, "video/mp4")
        return content_type or "application/octet-stream"

    @staticmethod
    def _safe_filename(value: str, kind: str) -> str:
        name = Path(value).name
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
        if not name:
            name = {"image": "image.bin", "video": "video.bin", "voice": "voice.bin"}.get(kind, "file.bin")
        return name[:180]

    async def _download_attachment(self, attachment: dict[str, Any], *, message_id: str = "", conversation_id: str = "") -> None:
        url = _assert_public_url(str(attachment.get("url") or ""))
        safe_conversation = re.sub(r"[^A-Za-z0-9._-]+", "_", conversation_id).strip("._")[:120] or "conversation"
        safe_message = re.sub(r"[^A-Za-z0-9._-]+", "_", message_id).strip("._")[:160] or "message"
        target_root = (
            Path(self.config.media_dir).expanduser().resolve()  # noqa: ASYNC240
            / datetime.now(UTC).strftime("%Y-%m-%d")
            / safe_conversation
            / safe_message
        )
        target_root.mkdir(parents=True, exist_ok=True)
        filename = self._safe_filename(str(attachment.get("filename") or "file.bin"), str(attachment.get("kind") or "file"))
        target = (target_root / filename).resolve()
        if target.parent != target_root:
            raise QQBotApiError("QQ 媒体文件名越界")
        client = self.client or self._create_client()
        self.client = client
        # QQBotClient exposes the bounded downloader internally; adapters also
        # accept test clients implementing a small ``download_to_file`` hook.
        downloader = getattr(client, "download_to_file", None)
        if downloader is not None:
            await downloader(url, target, max_bytes=int(self.config.media_max_bytes))
        else:
            data, _ = await client._download_bytes(url)
            if len(data) > int(self.config.media_max_bytes):
                raise QQBotApiError("QQ 媒体超过大小硬限制")
            target.write_bytes(data)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        attachment.update({
            "local_path": str(target),
            "sha256": digest,
            "size": target.stat().st_size,
            "download_status": "downloaded",
        })

    def _split_text(self, content: str, limit: int) -> list[str]:
        text = (content or "").strip()
        if not text:
            raise QQBotApiError("QQ 文本消息内容不能为空")
        chunks: list[str] = []
        while len(text) > limit:
            split_at = max(text.rfind("\n", 0, limit + 1), text.rfind("。", 0, limit + 1))
            if split_at < limit // 2:
                split_at = limit
            else:
                split_at += 1
            chunks.append(text[:split_at].strip())
            text = text[split_at:].strip()
        if text:
            chunks.append(text)
        return chunks

    def _truncate_reply_chunks(self, chunks: list[str], count: int, limit: int) -> list[str]:
        kept = chunks[:count]
        suffix = "\n\n[回复内容过长，已截断]"
        available = max(1, limit - len(suffix))
        kept[-1] = f"{kept[-1][:available].rstrip()}{suffix}"
        return kept

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed

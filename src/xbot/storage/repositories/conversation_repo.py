from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.conversations.models import Conversation, ConversationSummary
from xbot.messaging.models import Message
from xbot.storage.models import (
    ContactRecord,
    ConversationMemberRecord,
    ConversationMessageRecord,
    ConversationRecord,
    ConversationSummaryRecord,
    ConversationStateRecord,
    MessageAttachmentRecord,
    UserProfileRecord,
)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_conversation(self, conversation: Conversation) -> None:
        existing = await self.session.get(ConversationRecord, conversation.id)
        if existing:
            existing.updated_at = conversation.updated_at
            if conversation.title and conversation.title != conversation.raw_id:
                existing.title = conversation.title
            if conversation.avatar_url:
                existing.avatar_url = conversation.avatar_url
            return
        record = ConversationRecord(
            id=conversation.id,
            platform=conversation.platform,
            adapter=conversation.adapter,
            scope=conversation.scope,
            raw_id=conversation.raw_id,
            title=conversation.title,
            avatar_url=conversation.avatar_url,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        await self.session.merge(record)

    async def append_message(self, conversation_id: str, message: Message) -> None:
        self.session.add(
            ConversationMessageRecord(
                conversation_id=conversation_id,
                message_id=message.id,
                platform=message.platform,
                adapter=message.adapter,
                sender_id=message.sender_id,
                sender_name=message.sender_name,
                type=message.type,
                content=message.content,
                raw_json=json.dumps(message.raw, ensure_ascii=False),
                created_at=message.timestamp,
            )
        )
        await self.upsert_contact_from_message(message)
        await self.upsert_conversation_member(conversation_id, message)
        await self.save_message_attachments(conversation_id, message)

    async def upsert_contact_from_message(self, message: Message) -> None:
        user_id = str(message.sender_id or "").strip()
        if not user_id:
            return
        now = message.timestamp
        result = await self.session.execute(
            select(ContactRecord).where(
                ContactRecord.platform == message.platform,
                ContactRecord.adapter == message.adapter,
                ContactRecord.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()
        avatar_url = self._extract_avatar_url(message.raw)
        raw_json = json.dumps(self._compact_contact_raw(message.raw), ensure_ascii=False)
        if record:
            record.nickname = message.sender_name or record.nickname
            if avatar_url:
                record.avatar_url = avatar_url
            record.raw_json = raw_json
            record.last_seen_at = now
            return
        self.session.add(
            ContactRecord(
                platform=message.platform,
                adapter=message.adapter,
                user_id=user_id,
                nickname=message.sender_name,
                avatar_url=avatar_url or None,
                raw_json=raw_json,
                first_seen_at=now,
                last_seen_at=now,
            )
        )

    async def upsert_conversation_member(self, conversation_id: str, message: Message) -> None:
        user_id = str(message.sender_id or "").strip()
        if not user_id:
            return
        result = await self.session.execute(
            select(ConversationMemberRecord).where(
                ConversationMemberRecord.conversation_id == conversation_id,
                ConversationMemberRecord.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()
        if record:
            if message.sender_name:
                record.display_name = message.sender_name
            return
        self.session.add(
            ConversationMemberRecord(
                conversation_id=conversation_id,
                user_id=user_id,
                display_name=message.sender_name,
                role="member",
                joined_at=message.timestamp,
            )
        )

    async def save_message_attachments(self, conversation_id: str, message: Message) -> None:
        for item in self._iter_attachments(message.raw):
            self.session.add(
                MessageAttachmentRecord(
                    message_id=message.id,
                    conversation_id=conversation_id,
                    sender_id=message.sender_id,
                    kind=str(item.get("kind") or item.get("type") or "file")[:32],
                    filename=str(item.get("filename") or item.get("name") or "")[:512] or None,
                    mime=str(item.get("mime") or "")[:128] or None,
                    size=self._safe_int(item.get("size"), 0),
                    local_path=str(item.get("local_path") or "") or None,
                    url=str(item.get("url") or item.get("path") or self._url_for_local_path(item.get("local_path")) or "") or None,
                    sha256=str(item.get("sha256") or "")[:128] or None,
                    download_status=str(item.get("download_status") or item.get("status") or "metadata_only")[:64],
                    quoted=bool(item.get("quoted")),
                    metadata_json=json.dumps(item.get("metadata") or item, ensure_ascii=False),
                    created_at=message.timestamp,
                )
            )

    async def list_conversations(self, limit: int = 100) -> list[Conversation]:
        result = await self.session.execute(
            select(ConversationRecord).order_by(ConversationRecord.updated_at.desc()).limit(limit)
        )
        return [self._to_conversation(record) for record in result.scalars().all()]

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        record = await self.session.get(ConversationRecord, conversation_id)
        return self._to_conversation(record) if record else None

    async def delete_conversation(self, conversation_id: str) -> bool:
        record = await self.session.get(ConversationRecord, conversation_id)
        if record is None:
            return False
        for model in (
            ConversationMessageRecord,
            ConversationSummaryRecord,
            ConversationStateRecord,
        ):
            result = await self.session.execute(
                select(model).where(model.conversation_id == conversation_id)
            )
            for item in result.scalars().all():
                await self.session.delete(item)
        await self.session.delete(record)
        return True

    async def get_messages(self, conversation_id: str, limit: int = 20) -> list[Message]:
        stmt = (
            select(ConversationMessageRecord)
            .where(ConversationMessageRecord.conversation_id == conversation_id)
            .order_by(ConversationMessageRecord.created_at.desc())
        )
        if limit > 0:
            stmt = stmt.limit(limit)
        records = list((await self.session.execute(stmt)).scalars().all())
        return [self._to_message(record) for record in reversed(records)]

    async def count_messages(self, conversation_id: str) -> int:
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count(ConversationMessageRecord.id)).where(
                ConversationMessageRecord.conversation_id == conversation_id
            )
        )
        return int(result.scalar_one() or 0)

    async def save_summary(self, summary: ConversationSummary) -> ConversationSummary:
        record = ConversationSummaryRecord(
            conversation_id=summary.conversation_id,
            summary=summary.summary,
            from_message_id=summary.from_message_id,
            to_message_id=summary.to_message_id,
            created_at=summary.created_at,
        )
        self.session.add(record)
        await self.session.flush()
        return summary.model_copy(update={"id": record.id})

    async def get_summaries(
        self, conversation_id: str, limit: int = 10
    ) -> list[ConversationSummary]:
        stmt = (
            select(ConversationSummaryRecord)
            .where(ConversationSummaryRecord.conversation_id == conversation_id)
            .order_by(ConversationSummaryRecord.created_at.desc())
        )
        if limit > 0:
            stmt = stmt.limit(limit)
        records = list((await self.session.execute(stmt)).scalars().all())
        return [self._to_summary(record) for record in reversed(records)]

    async def get_state(self, conversation_id: str, namespace: str) -> dict:
        result = await self.session.execute(
            select(ConversationStateRecord).where(
                ConversationStateRecord.conversation_id == conversation_id,
                ConversationStateRecord.namespace == namespace,
            )
        )
        record = result.scalar_one_or_none()
        return json.loads(record.value_json) if record else {}

    async def set_state(self, conversation_id: str, namespace: str, value: dict) -> None:
        result = await self.session.execute(
            select(ConversationStateRecord).where(
                ConversationStateRecord.conversation_id == conversation_id,
                ConversationStateRecord.namespace == namespace,
            )
        )
        record = result.scalar_one_or_none()
        value_json = json.dumps(value, ensure_ascii=False)
        if record:
            record.value_json = value_json
        else:
            self.session.add(
                ConversationStateRecord(
                    conversation_id=conversation_id,
                    namespace=namespace,
                    value_json=value_json,
                )
            )

    def _to_conversation(self, record: ConversationRecord) -> Conversation:
        return Conversation(
            id=record.id,
            platform=record.platform,
            adapter=record.adapter,
            scope=record.scope,
            raw_id=record.raw_id,
            title=record.title,
            avatar_url=getattr(record, "avatar_url", None),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _to_message(self, record: ConversationMessageRecord) -> Message:
        return Message(
            id=record.message_id,
            platform=record.platform,
            adapter=record.adapter,
            conversation_id=record.conversation_id,
            sender_id=record.sender_id,
            sender_name=record.sender_name,
            type=record.type,
            content=record.content,
            raw=json.loads(record.raw_json or "{}"),
            timestamp=record.created_at,
        )

    def _to_summary(self, record: ConversationSummaryRecord) -> ConversationSummary:
        return ConversationSummary(
            id=record.id,
            conversation_id=record.conversation_id,
            summary=record.summary,
            from_message_id=record.from_message_id,
            to_message_id=record.to_message_id,
            created_at=record.created_at,
        )

    def _extract_avatar_url(self, raw: dict | None) -> str:
        if not isinstance(raw, dict):
            return ""
        keys = (
            "avatar_url",
            "avatar",
            "head_img_url",
            "headimgurl",
            "big_head_img_url",
            "small_head_img_url",
            "BigHeadImgUrl",
            "SmallHeadImgUrl",
            "bigHeadImgUrl",
            "smallHeadImgUrl",
        )
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in raw.values():
            if isinstance(value, dict):
                found = self._extract_avatar_url(value)
                if found:
                    return found
        return ""

    def _compact_contact_raw(self, raw: dict | None) -> dict:
        if not isinstance(raw, dict):
            return {}
        keep = (
            "sender_wxid",
            "sender_name",
            "conversation_wxid",
            "avatar_url",
            "avatar",
            "BigHeadImgUrl",
            "SmallHeadImgUrl",
            "big_head_img_url",
            "small_head_img_url",
        )
        return {k: raw.get(k) for k in keep if raw.get(k)}

    def _iter_attachments(self, raw: dict | None) -> list[dict]:
        if not isinstance(raw, dict):
            return []
        items: list[dict] = []
        for key, quoted in (("attachments", False), ("quote_attachments", True), ("quoted_attachments", True)):
            value = raw.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        copied = dict(item)
                        copied.setdefault("quoted", quoted)
                        items.append(copied)
        quote = raw.get("quote")
        if isinstance(quote, dict):
            value = quote.get("attachments")
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        copied = dict(item)
                        copied.setdefault("quoted", True)
                        items.append(copied)
        return items

    def _url_for_local_path(self, path: object) -> str:
        value = str(path or "").replace("\\", "/").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://", "/files/", "/media/")):
            return value
        marker = "/files/"
        if marker in value:
            return value[value.index(marker):]
        marker = "/data/"
        if marker in value:
            return "/media/" + value[value.index(marker) + len(marker):]
        if value.startswith("files/"):
            return "/" + value
        if value.startswith("data/"):
            return "/media/" + value[len("data/"):]
        return ""

    def _safe_int(self, value: object, default: int = 0) -> int:
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

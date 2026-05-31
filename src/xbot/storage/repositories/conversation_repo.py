from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.conversations.models import Conversation, ConversationSummary
from xbot.messaging.models import Message
from xbot.storage.models import (
    ConversationMessageRecord,
    ConversationRecord,
    ConversationSummaryRecord,
    ConversationStateRecord,
)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_conversation(self, conversation: Conversation) -> None:
        record = ConversationRecord(
            id=conversation.id,
            platform=conversation.platform,
            adapter=conversation.adapter,
            scope=conversation.scope,
            raw_id=conversation.raw_id,
            title=conversation.title,
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

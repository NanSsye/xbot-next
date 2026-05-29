from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.messaging.models import Message, MessageEnvelope, Reply
from xbot.storage.models import MessageEnvelopeRecord, MessageRecord, ReplyRecord


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_message(self, message: Message) -> None:
        record = MessageRecord(
            id=message.id,
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            type=message.type,
            content=message.content,
            raw_json=json.dumps(message.raw, ensure_ascii=False),
            created_at=message.timestamp,
        )
        await self.session.merge(record)

    async def save_envelope(self, envelope: MessageEnvelope) -> None:
        record = MessageEnvelopeRecord(
            id=envelope.id,
            trace_id=envelope.trace_id,
            dedupe_key=envelope.dedupe_key,
            message_id=envelope.message.id,
            delivery_attempts=envelope.delivery_attempts,
            available_at=envelope.available_at,
            headers_json=json.dumps(envelope.headers, ensure_ascii=False),
            created_at=envelope.created_at,
        )
        await self.session.merge(record)

    async def save_reply(self, reply: Reply) -> None:
        self.session.add(
            ReplyRecord(
                platform=reply.platform,
                adapter=reply.adapter,
                conversation_id=reply.conversation_id,
                type=reply.type,
                content=reply.content,
                quote_message_id=reply.quote_message_id,
            )
        )

    async def recent_messages(self, limit: int = 50) -> list[Message]:
        result = await self.session.execute(
            select(MessageRecord).order_by(MessageRecord.created_at.desc()).limit(limit)
        )
        return [self._to_message(record) for record in reversed(result.scalars().all())]

    async def recent_replies(self, limit: int = 50) -> list[Reply]:
        result = await self.session.execute(
            select(ReplyRecord).order_by(ReplyRecord.created_at.desc()).limit(limit)
        )
        return [self._to_reply(record) for record in reversed(result.scalars().all())]

    def _to_message(self, record: MessageRecord) -> Message:
        return Message(
            id=record.id,
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

    def _to_reply(self, record: ReplyRecord) -> Reply:
        return Reply(
            platform=record.platform,
            adapter=record.adapter,
            conversation_id=record.conversation_id,
            type=record.type,
            content=record.content,
            quote_message_id=record.quote_message_id,
        )

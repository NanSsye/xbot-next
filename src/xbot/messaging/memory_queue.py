from __future__ import annotations

import asyncio

from xbot.core.logging import logger
from xbot.messaging.models import MessageEnvelope
from xbot.messaging.queue import MessageQueue


class MemoryMessageQueue(MessageQueue):
    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[MessageEnvelope] = (
            asyncio.Queue(maxsize=maxsize) if maxsize > 0 else asyncio.Queue()
        )

    async def publish(self, envelope: MessageEnvelope) -> None:
        await self._queue.put(envelope)

    async def consume(self) -> MessageEnvelope:
        return await self._queue.get()

    async def ack(self, envelope: MessageEnvelope) -> None:
        self._queue.task_done()

    async def requeue(self, envelope: MessageEnvelope) -> None:
        await self._queue.put(envelope)

    async def dead_letter(self, envelope: MessageEnvelope) -> None:
        logger.error(
            "内存队列消息进入死信(丢弃): message_id={} conversation={} attempts={}",
            envelope.message.id,
            envelope.message.conversation_id,
            envelope.delivery_attempts,
        )

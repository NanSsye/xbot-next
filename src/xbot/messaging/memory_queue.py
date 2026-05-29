from __future__ import annotations

import asyncio

from xbot.messaging.models import MessageEnvelope
from xbot.messaging.queue import MessageQueue


class MemoryMessageQueue(MessageQueue):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[MessageEnvelope] = asyncio.Queue()

    async def publish(self, envelope: MessageEnvelope) -> None:
        await self._queue.put(envelope)

    async def consume(self) -> MessageEnvelope:
        return await self._queue.get()

    async def ack(self, envelope: MessageEnvelope) -> None:
        self._queue.task_done()

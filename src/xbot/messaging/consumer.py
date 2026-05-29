from __future__ import annotations

from xbot.core.logging import logger
from xbot.messaging.dedupe import DedupeService
from xbot.messaging.models import MessageEnvelope
from xbot.messaging.pipeline import MessagePipeline
from xbot.messaging.queue import MessageQueue


class MessageConsumer:
    def __init__(
        self,
        dedupe: DedupeService,
        pipeline: MessagePipeline,
        conversations,
        engine,
        message_store=None,
    ) -> None:
        self.dedupe = dedupe
        self.pipeline = pipeline
        self.conversations = conversations
        self.engine = engine
        self.message_store = message_store

    async def handle(self, envelope: MessageEnvelope) -> bool:
        if self.message_store:
            await self.message_store.add_envelope(envelope)
            await self.message_store.add_message(envelope.message)
        if await self.dedupe.is_duplicate(envelope.dedupe_key):
            return False
        message = await self.pipeline.process(envelope.message)
        await self.conversations.touch(message)
        await self.conversations.append_message(message.conversation_id, message)
        await self.engine.dispatch_message(message)
        return True

    async def run(self, queue: MessageQueue) -> None:
        while True:
            envelope = await queue.consume()
            try:
                await self.handle(envelope)
            except Exception as exc:
                logger.exception(
                    "MessageConsumer 处理消息失败: message_id={} error={}",
                    envelope.message.id,
                    exc,
                )
            finally:
                await queue.ack(envelope)

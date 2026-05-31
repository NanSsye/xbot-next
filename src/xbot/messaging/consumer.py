from __future__ import annotations

import asyncio
from contextlib import suppress

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
        max_message_tasks: int = 1,
        per_conversation_serial: bool = True,
        max_active_conversations: int = 1000,
    ) -> None:
        self.dedupe = dedupe
        self.pipeline = pipeline
        self.conversations = conversations
        self.engine = engine
        self.message_store = message_store
        self.max_message_tasks = max(1, int(max_message_tasks or 1))
        self.per_conversation_serial = per_conversation_serial
        self.max_active_conversations = max(1, int(max_active_conversations or 1000))
        self._semaphore = asyncio.Semaphore(self.max_message_tasks)
        self._tasks: set[asyncio.Task] = set()
        self._conversation_locks: dict[str, asyncio.Lock] = {}

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
        try:
            while True:
                await self._semaphore.acquire()
                try:
                    envelope = await queue.consume()
                except asyncio.CancelledError:
                    self._semaphore.release()
                    raise
                except Exception as exc:
                    self._semaphore.release()
                    logger.exception("MessageConsumer 消费队列失败，1 秒后重试: {}", exc)
                    await asyncio.sleep(1)
                    continue
                task = asyncio.create_task(
                    self._handle_and_ack(queue, envelope),
                    name=f"xbot-message-{envelope.message.id}",
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except asyncio.CancelledError:
            await self._cancel_active_tasks()
            raise

    async def _handle_and_ack(self, queue: MessageQueue, envelope: MessageEnvelope) -> None:
        try:
            if self.per_conversation_serial:
                lock = self._lock_for_conversation(envelope)
                async with lock:
                    await self.handle(envelope)
            else:
                await self.handle(envelope)
        except Exception as exc:
            logger.exception(
                "MessageConsumer 处理消息失败: message_id={} error={}",
                envelope.message.id,
                exc,
            )
        finally:
            try:
                await queue.ack(envelope)
            finally:
                self._semaphore.release()

    def _lock_for_conversation(self, envelope: MessageEnvelope) -> asyncio.Lock:
        message = envelope.message
        key = f"{message.platform}:{message.adapter}:{message.raw.get('scope') or ''}:{message.conversation_id}"
        lock = self._conversation_locks.get(key)
        if lock is None:
            if len(self._conversation_locks) >= self.max_active_conversations:
                idle = [item for item in self._conversation_locks.items() if not item[1].locked()]
                if idle:
                    self._conversation_locks.pop(idle[0][0], None)
            lock = self._conversation_locks.setdefault(key, asyncio.Lock())
        return lock

    async def _cancel_active_tasks(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

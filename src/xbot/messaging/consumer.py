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
        event_bus=None,
        message_timeout_seconds: float = 0,
        max_attempts: int = 3,
        backoff_initial_seconds: float = 2,
        backoff_max_seconds: float = 60,
        backoff_exponential: bool = True,
    ) -> None:
        self.dedupe = dedupe
        self.pipeline = pipeline
        self.conversations = conversations
        self.engine = engine
        self.message_store = message_store
        self.max_message_tasks = max(1, int(max_message_tasks or 1))
        self.per_conversation_serial = per_conversation_serial
        self.max_active_conversations = max(1, int(max_active_conversations or 1000))
        self.message_timeout_seconds = max(0, float(message_timeout_seconds or 0))
        self.max_attempts = max(1, int(max_attempts or 1))
        self.backoff_initial_seconds = max(0.0, float(backoff_initial_seconds or 0))
        self.backoff_max_seconds = max(0.0, float(backoff_max_seconds or 0))
        self.backoff_exponential = bool(backoff_exponential)
        self._semaphore = asyncio.Semaphore(self.max_message_tasks)
        self._tasks: set[asyncio.Task] = set()
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self.event_bus = event_bus

    async def handle(self, envelope: MessageEnvelope) -> bool:
        if await self.dedupe.is_duplicate(envelope.dedupe_key):
            return False
        try:
            message = await self.pipeline.process(envelope.message)
            if self.message_store:
                await self.message_store.add_envelope(envelope)
                await self.message_store.add_message(message)
            await self.conversations.touch(message)
            await self.conversations.append_message(message.conversation_id, message)
        except Exception:
            await self.dedupe.forget(envelope.dedupe_key)
            raise
        self._publish_event_async("message.created", {"message": message.model_dump(mode="json")})
        try:
            await self.engine.dispatch_message(message)
        except Exception as exc:
            logger.exception(
                "消息已入库，但插件分发失败: message_id={} conversation={} error={}",
                message.id,
                message.conversation_id,
                exc,
            )
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
                    await self._handle_with_timeout(envelope)
            else:
                await self._handle_with_timeout(envelope)
        except TimeoutError:
            logger.error(
                "MessageConsumer 处理消息超时: message_id={} conversation={} timeout={}s",
                envelope.message.id,
                envelope.message.conversation_id,
                self.message_timeout_seconds,
            )
            await self._requeue_or_dead_letter(queue, envelope)
        except Exception as exc:
            logger.exception(
                "MessageConsumer 处理消息失败: message_id={} conversation={} error={}",
                envelope.message.id,
                envelope.message.conversation_id,
                exc,
            )
            await self._requeue_or_dead_letter(queue, envelope)
        finally:
            self._semaphore.release()

    async def _handle_with_timeout(self, envelope: MessageEnvelope) -> None:
        if self.message_timeout_seconds > 0:
            await asyncio.wait_for(self.handle(envelope), timeout=self.message_timeout_seconds)
        else:
            await self.handle(envelope)

    async def _requeue_or_dead_letter(self, queue: MessageQueue, envelope: MessageEnvelope) -> None:
        await self.dedupe.forget(envelope.dedupe_key)
        retried = envelope.model_copy(
            update={"delivery_attempts": envelope.delivery_attempts + 1}
        )
        if retried.delivery_attempts < self.max_attempts:
            delay = self._backoff_delay(retried.delivery_attempts)
            logger.warning(
                "MessageConsumer 重投消息: message_id={} attempt={}/{} delay={:.1f}s",
                envelope.message.id,
                retried.delivery_attempts,
                self.max_attempts,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await queue.requeue(retried)
            except Exception as exc:
                logger.exception("MessageConsumer 重投队列失败: message_id={} error={}", envelope.message.id, exc)
        else:
            logger.error(
                "MessageConsumer 消息尝试耗尽，进入死信: message_id={} conversation={}",
                envelope.message.id,
                envelope.message.conversation_id,
            )
            try:
                await queue.dead_letter(retried)
            except Exception as exc:
                logger.exception("MessageConsumer 死信投递失败: message_id={} error={}", envelope.message.id, exc)

    def _backoff_delay(self, attempt: int) -> float:
        if not self.backoff_exponential:
            return min(self.backoff_initial_seconds, self.backoff_max_seconds)
        return min(self.backoff_initial_seconds * (2 ** (attempt - 1)), self.backoff_max_seconds)

    def _publish_event_async(self, event_type: str, payload: dict) -> None:
        if not self.event_bus:
            return
        bus = self.event_bus

        async def _fire() -> None:
            with suppress(Exception):
                await bus.publish(event_type, payload)

        task = asyncio.create_task(_fire(), name=f"xbot-event-{event_type}")
        task.add_done_callback(self._on_event_task_done)

    def _on_event_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("EventBus 事件发布失败: error={}", exc)

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

import asyncio

import pytest

from xbot.messaging.consumer import MessageConsumer
from xbot.messaging.dedupe import DedupeService
from xbot.messaging.memory_queue import MemoryMessageQueue
from xbot.messaging.models import Message, MessageEnvelope


class FakePipeline:
    async def process(self, message):
        return message


class FlakyConversations:
    def __init__(self, fail_times: int = 1):
        self.fail_times = fail_times
        self.calls = 0

    async def touch(self, message):
        return None

    async def append_message(self, conversation_id, message):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("db boom")


class OkConversations:
    def __init__(self):
        self.appended = []

    async def touch(self, message):
        return None

    async def append_message(self, conversation_id, message):
        self.appended.append((conversation_id, message.id))


class OkEngine:
    def __init__(self):
        self.dispatched = []

    async def dispatch_message(self, message):
        self.dispatched.append(message.id)


class HangingEngine:
    async def dispatch_message(self, message):
        await asyncio.sleep(60)


class TrackingDedupe(DedupeService):
    def __init__(self):
        super().__init__()
        self.forgotten: list[str] = []

    async def forget(self, dedupe_key):
        self.forgotten.append(dedupe_key)
        await super().forget(dedupe_key)


def _message(message_id: str, conversation_id: str = "room-a") -> Message:
    return Message(
        id=message_id,
        platform="wechat",
        adapter="wechat869",
        conversation_id=conversation_id,
        sender_id="sender",
        content=message_id,
        raw={"id": message_id, "scope": "group"},
    )


def _envelope(message: Message) -> MessageEnvelope:
    return MessageEnvelope.from_message(message)


async def _until(predicate):
    while not predicate():  # noqa: ASYNC110 - polling predicate, not busy-wait
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_consumer_requeues_after_storage_failure_then_succeeds():
    queue = MemoryMessageQueue()
    dedupe = TrackingDedupe()
    conversations = FlakyConversations(fail_times=1)
    engine = OkEngine()
    consumer = MessageConsumer(
        dedupe=dedupe,
        pipeline=FakePipeline(),
        conversations=conversations,
        engine=engine,
        max_message_tasks=1,
        per_conversation_serial=False,
        max_attempts=3,
        backoff_initial_seconds=0,
    )
    task = asyncio.create_task(consumer.run(queue))
    try:
        await queue.publish(_envelope(_message("retry-ok")))
        await asyncio.wait_for(_until(lambda: engine.dispatched == ["retry-ok"]), timeout=2)
        await asyncio.wait_for(queue._queue.join(), timeout=1)
        assert conversations.calls == 2
        assert dedupe.forgotten == ["wechat:wechat869:retry-ok", "wechat:wechat869:retry-ok"]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_consumer_dead_letters_after_max_attempts():
    queue = MemoryMessageQueue()
    dead_lettered = []

    async def track_dead_letter(envelope):
        dead_lettered.append(envelope)

    queue.dead_letter = track_dead_letter
    dedupe = TrackingDedupe()
    conversations = FlakyConversations(fail_times=999)
    consumer = MessageConsumer(
        dedupe=dedupe,
        pipeline=FakePipeline(),
        conversations=conversations,
        engine=OkEngine(),
        max_message_tasks=1,
        per_conversation_serial=False,
        max_attempts=2,
        backoff_initial_seconds=0,
    )
    task = asyncio.create_task(consumer.run(queue))
    try:
        await queue.publish(_envelope(_message("dead-letter")))
        await asyncio.wait_for(_until(lambda: dead_lettered), timeout=2)
        assert conversations.calls == 2
        assert len(dead_lettered) == 1
        assert dead_lettered[0].message.id == "dead-letter"
        assert dead_lettered[0].delivery_attempts == 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_consumer_skips_duplicate_without_processing():
    MemoryMessageQueue()
    dedupe = DedupeService()
    engine = OkEngine()
    conversations = OkConversations()
    consumer = MessageConsumer(
        dedupe=dedupe,
        pipeline=FakePipeline(),
        conversations=conversations,
        engine=engine,
        max_message_tasks=1,
        per_conversation_serial=False,
    )
    first = await consumer.handle(_envelope(_message("dup")))
    second = await consumer.handle(_envelope(_message("dup")))
    assert first is True
    assert second is False
    assert engine.dispatched == ["dup"]
    assert len(conversations.appended) == 1


@pytest.mark.anyio
async def test_consumer_acknowledges_processed_and_duplicate_messages():
    class TrackingQueue:
        def __init__(self):
            self.acked = []

        async def ack(self, envelope):
            self.acked.append(envelope.id)

    queue = TrackingQueue()
    consumer = MessageConsumer(
        dedupe=DedupeService(),
        pipeline=FakePipeline(),
        conversations=OkConversations(),
        engine=OkEngine(),
        per_conversation_serial=False,
    )
    envelope = _envelope(_message("ack-once"))

    await consumer._handle_and_ack(queue, envelope)
    await consumer._handle_and_ack(queue, envelope)

    assert queue.acked == [envelope.id, envelope.id]


@pytest.mark.anyio
async def test_memory_queue_dead_letter_completes_consumed_item():
    queue = MemoryMessageQueue()
    envelope = _envelope(_message("dead-letter-accounting"))
    await queue.publish(envelope)

    consumed = await queue.consume()
    await queue.dead_letter(consumed)

    await asyncio.wait_for(queue._queue.join(), timeout=1)


@pytest.mark.anyio
async def test_consumer_timeout_requeues_message():
    queue = MemoryMessageQueue()
    requeued = []

    async def track_requeue(envelope):
        requeued.append(envelope)

    queue.requeue = track_requeue
    dedupe = DedupeService()
    consumer = MessageConsumer(
        dedupe=dedupe,
        pipeline=FakePipeline(),
        conversations=OkConversations(),
        engine=HangingEngine(),
        max_message_tasks=1,
        per_conversation_serial=False,
        message_timeout_seconds=0.05,
        max_attempts=3,
        backoff_initial_seconds=0,
    )
    envelope = _envelope(_message("slow"))
    await consumer._handle_and_ack(queue, envelope)
    assert len(requeued) == 1
    assert requeued[0].message.id == "slow"
    assert requeued[0].delivery_attempts == 1


@pytest.mark.anyio
async def test_consumer_event_publish_does_not_block_dispatch():
    MemoryMessageQueue()
    engine = OkEngine()
    slow = asyncio.Event()

    class SlowBus:
        async def publish(self, event_type, payload):
            await slow.wait()

    consumer = MessageConsumer(
        dedupe=DedupeService(),
        pipeline=FakePipeline(),
        conversations=OkConversations(),
        engine=engine,
        max_message_tasks=1,
        per_conversation_serial=False,
        event_bus=SlowBus(),
    )
    envelope = _envelope(_message("event-not-blocking"))
    await consumer.handle(envelope)
    assert engine.dispatched == ["event-not-blocking"]
    assert not slow.is_set()
    await consumer._cancel_active_tasks()
    assert consumer._event_tasks == set()

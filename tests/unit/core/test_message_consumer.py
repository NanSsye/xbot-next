import asyncio

import pytest

from xbot.messaging.consumer import MessageConsumer
from xbot.messaging.memory_queue import MemoryMessageQueue
from xbot.messaging.models import Message, MessageEnvelope


class FakeDedupe:
    async def is_duplicate(self, key):
        return False


class FakePipeline:
    async def process(self, message):
        return message


class FakeConversations:
    async def touch(self, message):
        return None

    async def append_message(self, conversation_id, message):
        return None


class BlockingEngine:
    def __init__(self):
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.processed = []

    async def dispatch_message(self, message):
        self.processed.append(f"start:{message.id}")
        if message.id == "first":
            self.first_started.set()
            await self.release_first.wait()
        self.processed.append(f"done:{message.id}")


def _message(message_id: str, conversation_id: str) -> Message:
    return Message(
        id=message_id,
        platform="wechat",
        adapter="wechat869",
        conversation_id=conversation_id,
        sender_id="sender",
        content=message_id,
        raw={"id": message_id, "scope": "group"},
    )


@pytest.mark.anyio
async def test_message_consumer_processes_different_conversations_concurrently():
    queue = MemoryMessageQueue()
    engine = BlockingEngine()
    consumer = MessageConsumer(
        dedupe=FakeDedupe(),
        pipeline=FakePipeline(),
        conversations=FakeConversations(),
        engine=engine,
        max_message_tasks=2,
        per_conversation_serial=True,
    )
    task = asyncio.create_task(consumer.run(queue))
    try:
        await queue.publish(MessageEnvelope.from_message(_message("first", "room-a")))
        await queue.publish(MessageEnvelope.from_message(_message("second", "room-b")))
        await asyncio.wait_for(engine.first_started.wait(), timeout=1)
        await asyncio.wait_for(_until(lambda: "done:second" in engine.processed), timeout=1)

        assert "done:first" not in engine.processed
    finally:
        engine.release_first.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_message_consumer_serializes_same_conversation_by_default():
    queue = MemoryMessageQueue()
    engine = BlockingEngine()
    consumer = MessageConsumer(
        dedupe=FakeDedupe(),
        pipeline=FakePipeline(),
        conversations=FakeConversations(),
        engine=engine,
        max_message_tasks=2,
        per_conversation_serial=True,
    )
    task = asyncio.create_task(consumer.run(queue))
    try:
        await queue.publish(MessageEnvelope.from_message(_message("first", "room-a")))
        await queue.publish(MessageEnvelope.from_message(_message("second", "room-a")))
        await asyncio.wait_for(engine.first_started.wait(), timeout=1)
        await asyncio.sleep(0.05)

        assert "start:second" not in engine.processed
    finally:
        engine.release_first.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def _until(predicate):
    while not predicate():
        await asyncio.sleep(0.01)

import pytest

from xbot.messaging.memory_queue import MemoryMessageQueue
from xbot.messaging.models import Message, MessageEnvelope


@pytest.mark.anyio
async def test_memory_queue_uses_envelopes():
    queue = MemoryMessageQueue()
    message = Message(
        platform="web",
        adapter="web",
        conversation_id="test",
        sender_id="tester",
        content="queued",
        raw={"id": "queue-msg-1"},
    )
    envelope = MessageEnvelope.from_message(message)

    await queue.publish(envelope)
    consumed = await queue.consume()
    await queue.ack(consumed)

    assert consumed.dedupe_key == "web:web:queue-msg-1"
    assert consumed.message.content == "queued"

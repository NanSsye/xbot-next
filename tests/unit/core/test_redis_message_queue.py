from __future__ import annotations

import pytest

from xbot.messaging.models import Message, MessageEnvelope
from xbot.messaging.redis_queue import RedisMessageQueue


class FakePipeline:
    def __init__(self) -> None:
        self.commands = []
        self.executed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def xadd(self, queue_name, fields):
        self.commands.append(("xadd", queue_name, fields))

    def xack(self, queue_name, group_name, redis_id):
        self.commands.append(("xack", queue_name, group_name, redis_id))

    async def execute(self):
        self.executed = True


class FakeRedis:
    def __init__(self) -> None:
        self.pipelines = []

    def pipeline(self, *, transaction):
        assert transaction is True
        pipeline = FakePipeline()
        self.pipelines.append(pipeline)
        return pipeline


def _envelope(message_id: str = "redis-message") -> MessageEnvelope:
    return MessageEnvelope.from_message(
        Message(
            id=message_id,
            platform="qq",
            adapter="qq",
            conversation_id="qq:group:test",
            sender_id="user-1",
            content="hello",
            raw={"scope": "group"},
        )
    )


@pytest.mark.anyio
async def test_redis_requeue_adds_retry_and_acks_original_atomically():
    queue = RedisMessageQueue("redis://unused", "xbot:messages")
    fake_redis = FakeRedis()
    queue._redis = fake_redis
    queue._groups_ready = True
    envelope = _envelope()
    queue._pending_ids[envelope.id] = "1-0"

    await queue.requeue(envelope)

    pipeline = fake_redis.pipelines[0]
    assert pipeline.executed is True
    assert [command[0] for command in pipeline.commands] == ["xadd", "xack"]
    assert pipeline.commands[0][1] == "xbot:messages"
    assert envelope.id not in queue._pending_ids


@pytest.mark.anyio
async def test_redis_dead_letter_adds_copy_and_acks_original_atomically():
    queue = RedisMessageQueue(
        "redis://unused",
        "xbot:messages",
        dead_letter_queue="xbot:dead_letters",
    )
    fake_redis = FakeRedis()
    queue._redis = fake_redis
    queue._groups_ready = True
    envelope = _envelope("dead-letter")
    queue._pending_ids[envelope.id] = "2-0"

    await queue.dead_letter(envelope)

    pipeline = fake_redis.pipelines[0]
    assert pipeline.executed is True
    assert [command[0] for command in pipeline.commands] == ["xadd", "xack"]
    assert pipeline.commands[0][1] == "xbot:dead_letters"
    assert envelope.id not in queue._pending_ids

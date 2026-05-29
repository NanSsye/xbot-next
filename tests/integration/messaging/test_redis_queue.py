from __future__ import annotations

from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from xbot.core.config import load_settings
from xbot.messaging.models import Message, MessageEnvelope
from xbot.messaging.redis_queue import RedisMessageQueue


async def _redis_or_skip(redis_url: str) -> Redis:
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        await redis.ping()
    except RedisError as exc:
        await redis.aclose()
        pytest.skip(f"Redis integration tests skipped: {exc}")
    return redis


@pytest.mark.anyio
async def test_redis_stream_queue_publish_consume_ack() -> None:
    settings = load_settings("configs/xbot.toml")
    redis = await _redis_or_skip(settings.queue.redis_url)
    stream = f"xbot:test:messages:{uuid4().hex}"
    group = f"xbot-test-{uuid4().hex}"
    queue = RedisMessageQueue(
        redis_url=settings.queue.redis_url,
        queue_name=stream,
        group_name=group,
        consumer_name="pytest-worker",
        block_ms=100,
    )
    try:
        message = Message(
            platform="web",
            adapter="web",
            conversation_id="redis-test",
            sender_id="pytest",
            content="redis queued",
            raw={"id": f"redis-msg-{uuid4().hex}"},
        )
        envelope = MessageEnvelope.from_message(message)

        await queue.publish(envelope)
        consumed = await queue.consume()
        pending_before_ack = await redis.xpending_range(stream, group, "-", "+", 10)
        await queue.ack(consumed)
        pending_after_ack = await redis.xpending_range(stream, group, "-", "+", 10)

        assert consumed.id == envelope.id
        assert consumed.message.content == "redis queued"
        assert pending_before_ack
        assert pending_after_ack == []
    finally:
        await queue.close()
        await redis.delete(stream)
        await redis.aclose()

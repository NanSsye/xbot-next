from __future__ import annotations

import json

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from xbot.messaging.models import MessageEnvelope
from xbot.messaging.queue import MessageQueue


class RedisMessageQueue(MessageQueue):
    def __init__(
        self,
        redis_url: str,
        queue_name: str,
        group_name: str = "xbot",
        consumer_name: str = "worker-1",
        block_ms: int = 5000,
    ) -> None:
        self.redis_url = redis_url
        self.queue_name = queue_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.block_ms = block_ms
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._groups_ready = False
        self._pending_ids: dict[str, str] = {}

    async def publish(self, envelope: MessageEnvelope) -> None:
        await self._redis.xadd(
            self.queue_name,
            {
                "id": envelope.id,
                "payload": envelope.model_dump_json(),
            },
        )

    async def consume(self) -> MessageEnvelope:
        await self._ensure_group()
        while True:
            result = await self._redis.xreadgroup(
                groupname=self.group_name,
                consumername=self.consumer_name,
                streams={self.queue_name: ">"},
                count=1,
                block=self.block_ms,
            )
            if not result:
                continue
            _, messages = result[0]
            redis_id, fields = messages[0]
            envelope = MessageEnvelope.model_validate_json(fields["payload"])
            self._pending_ids[envelope.id] = redis_id
            return envelope

    async def ack(self, envelope: MessageEnvelope) -> None:
        redis_id = self._pending_ids.pop(envelope.id, None)
        if redis_id:
            await self._redis.xack(self.queue_name, self.group_name, redis_id)

    async def close(self) -> None:
        await self._redis.aclose()

    async def _ensure_group(self) -> None:
        if self._groups_ready:
            return
        try:
            await self._redis.xgroup_create(
                name=self.queue_name,
                groupname=self.group_name,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._groups_ready = True

from __future__ import annotations

from xbot.core.config import QueueSettings
from xbot.messaging.memory_queue import MemoryMessageQueue
from xbot.messaging.queue import MessageQueue
from xbot.messaging.redis_queue import RedisMessageQueue


def create_message_queue(config: QueueSettings) -> MessageQueue:
    if config.type == "redis":
        return RedisMessageQueue(
            redis_url=config.redis_url,
            queue_name=config.main_queue,
            consumer_name=config.consumer_name,
            dead_letter_queue=config.dead_letter_queue,
        )
    return MemoryMessageQueue(maxsize=config.maxsize)

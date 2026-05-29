from __future__ import annotations

from xbot.messaging.models import Message


class MessagePipeline:
    async def process(self, message: Message) -> Message:
        return message


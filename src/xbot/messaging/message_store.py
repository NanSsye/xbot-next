from __future__ import annotations

from xbot.messaging.models import Message, MessageEnvelope, Reply


class InMemoryMessageStore:
    def __init__(self, max_items: int = 500, repository_provider=None) -> None:
        self.max_items = max_items
        self.repository_provider = repository_provider
        self.messages: list[Message] = []
        self.replies: list[Reply] = []

    async def add_message(self, message: Message) -> None:
        self.messages = [item for item in self.messages if item.id != message.id]
        self.messages.append(message)
        self.messages = self.messages[-self.max_items :]
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.save_message(message)

    async def add_envelope(self, envelope: MessageEnvelope) -> None:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.save_envelope(envelope)

    async def add_reply(self, reply: Reply) -> None:
        self.replies.append(reply)
        self.replies = self.replies[-self.max_items :]
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.save_reply(reply)

    async def recent_messages(self, limit: int = 50) -> list[Message]:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.recent_messages(limit)
        return self.messages[-limit:]

    async def recent_replies(self, limit: int = 50) -> list[Reply]:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.recent_replies(limit)
        return self.replies[-limit:]

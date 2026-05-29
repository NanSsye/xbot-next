from __future__ import annotations

from datetime import datetime

from xbot.conversations.models import (
    Conversation,
    ConversationScope,
    ConversationSummary,
    build_conversation_id,
)
from xbot.messaging.models import Message


class InMemoryConversationStore:
    def __init__(self, max_messages_per_conversation: int = 200) -> None:
        self.max_messages_per_conversation = max_messages_per_conversation
        self.conversations: dict[str, Conversation] = {}
        self.messages: dict[str, list[Message]] = {}
        self.states: dict[str, dict[str, dict]] = {}
        self.summaries: dict[str, list[ConversationSummary]] = {}

    async def touch(
        self,
        *,
        platform: str,
        adapter: str,
        scope: ConversationScope,
        raw_id: str,
        title: str | None = None,
    ) -> Conversation:
        conversation_id = build_conversation_id(platform, adapter, scope, raw_id)
        existing = self.conversations.get(conversation_id)
        if existing:
            existing.updated_at = datetime.utcnow()
            if title:
                existing.title = title
            return existing
        conversation = Conversation(
            id=conversation_id,
            platform=platform,
            adapter=adapter,
            scope=scope,
            raw_id=raw_id,
            title=title,
        )
        self.conversations[conversation_id] = conversation
        self.messages.setdefault(conversation_id, [])
        self.states.setdefault(conversation_id, {})
        self.summaries.setdefault(conversation_id, [])
        return conversation

    async def append_message(self, conversation_id: str, message: Message) -> None:
        bucket = self.messages.setdefault(conversation_id, [])
        bucket.append(message)
        self.messages[conversation_id] = bucket[-self.max_messages_per_conversation :]

    async def list_conversations(self) -> list[Conversation]:
        return list(self.conversations.values())

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def get_messages(self, conversation_id: str, limit: int = 20) -> list[Message]:
        messages = self.messages.get(conversation_id, [])
        return messages if limit <= 0 else messages[-limit:]

    async def count_messages(self, conversation_id: str) -> int:
        return len(self.messages.get(conversation_id, []))

    async def save_summary(self, summary: ConversationSummary) -> ConversationSummary:
        bucket = self.summaries.setdefault(summary.conversation_id, [])
        stored = summary.model_copy(update={"id": len(bucket) + 1})
        bucket.append(stored)
        return stored

    async def get_summaries(self, conversation_id: str, limit: int = 10) -> list[ConversationSummary]:
        summaries = self.summaries.get(conversation_id, [])
        return summaries if limit <= 0 else summaries[-limit:]

    async def get_state(self, conversation_id: str, namespace: str) -> dict:
        return self.states.setdefault(conversation_id, {}).setdefault(namespace, {})

    async def set_state(self, conversation_id: str, namespace: str, value: dict) -> None:
        self.states.setdefault(conversation_id, {})[namespace] = value

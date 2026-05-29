from contextlib import asynccontextmanager

import pytest

from xbot.conversations.manager import ConversationManager
from xbot.conversations.context_window import ContextWindow
from xbot.core.config import ConversationConfig
from xbot.messaging.models import Message


class FakeConversationRepository:
    def __init__(self):
        self.conversations = {}
        self.messages = {}
        self.states = {}
        self.summaries = {}

    async def save_conversation(self, conversation):
        self.conversations[conversation.id] = conversation

    async def append_message(self, conversation_id, message):
        self.messages.setdefault(conversation_id, []).append(message)

    async def list_conversations(self, limit=100):
        return list(self.conversations.values())[-limit:]

    async def get_conversation(self, conversation_id):
        return self.conversations.get(conversation_id)

    async def get_messages(self, conversation_id, limit=20):
        messages = self.messages.get(conversation_id, [])
        return messages if limit <= 0 else messages[-limit:]

    async def count_messages(self, conversation_id):
        return len(self.messages.get(conversation_id, []))

    async def save_summary(self, summary):
        self.summaries.setdefault(summary.conversation_id, []).append(summary)
        return summary

    async def get_summaries(self, conversation_id, limit=10):
        summaries = self.summaries.get(conversation_id, [])
        return summaries if limit <= 0 else summaries[-limit:]

    async def get_state(self, conversation_id, namespace):
        return self.states.get(conversation_id, {}).get(namespace, {})

    async def set_state(self, conversation_id, namespace, value):
        self.states.setdefault(conversation_id, {})[namespace] = value


@pytest.mark.anyio
async def test_conversation_manager_uses_repository_provider_for_reads_and_writes():
    repo = FakeConversationRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    manager = ConversationManager(ConversationConfig(), repository_provider=provider)
    message = Message(
        platform="web",
        adapter="web",
        conversation_id="repo-user",
        sender_id="tester",
        content="persisted",
    )

    conversation = await manager.touch(message)
    await manager.append_message(message.conversation_id, message)
    await manager.set_state(conversation.id, "agent", {"active": True})

    assert await manager.get_conversation(conversation.id) == conversation
    assert (await manager.get_messages(conversation.id))[-1].content == "persisted"
    assert await manager.get_state(conversation.id, "agent") == {"active": True}
    assert (await manager.list_conversations())[0].id == conversation.id


def test_context_window_uses_all_messages_when_recent_messages_is_zero():
    messages = [
        Message(platform="web", adapter="web", conversation_id="c", sender_id="u", content=str(i))
        for i in range(30)
    ]
    window = ContextWindow(recent_messages=0, max_chars=1000)

    assert len(window.trim(messages)) == 30


@pytest.mark.anyio
async def test_conversation_manager_auto_summarizes_at_threshold():
    config = ConversationConfig()
    config.context.summary_every_messages = 3
    config.context.auto_summarize = True
    manager = ConversationManager(config)

    conversation_id = None
    for index in range(3):
        message = Message(
            platform="web",
            adapter="web",
            conversation_id="summary-user",
            sender_id="tester",
            content=f"message {index}",
        )
        conversation = await manager.touch(message)
        conversation_id = conversation.id
        await manager.append_message(message.conversation_id, message)

    summaries = await manager.get_summaries(conversation_id)

    assert len(summaries) == 1
    assert "Conversation summary after 3 messages" in summaries[0].summary
    assert summaries[0].from_message_id
    assert summaries[0].to_message_id

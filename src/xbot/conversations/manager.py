from __future__ import annotations

from xbot.conversations.context_window import ContextWindow
from xbot.conversations.models import (
    Conversation,
    ConversationContext,
    ConversationScope,
    ConversationSummary,
)
from xbot.conversations.session_store import InMemoryConversationStore
from xbot.core.config import ConversationConfig
from xbot.messaging.models import Message


class ConversationManager:
    def __init__(self, config: ConversationConfig, repository_provider=None) -> None:
        self.config = config
        self.store = InMemoryConversationStore()
        self.repository_provider = repository_provider
        self.context_window = ContextWindow(
            recent_messages=config.context.recent_messages,
            max_chars=config.context.max_chars,
        )

    async def touch(self, message: Message) -> Conversation:
        scope = self._scope_from_message(message)
        raw_id = message.conversation_id
        conversation = await self.store.touch(
            platform=message.platform,
            adapter=message.adapter,
            scope=scope,
            raw_id=raw_id,
            title=None,
        )
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.save_conversation(conversation)
        return conversation

    async def append_message(self, conversation_id: str, message: Message) -> None:
        normalized_id = self._normalize_conversation_id(message, conversation_id)
        await self.store.append_message(normalized_id, message)
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.append_message(normalized_id, message)
        await self._auto_summarize_if_needed(normalized_id)

    async def list_conversations(self, limit: int = 100) -> list[Conversation]:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.list_conversations(limit)
        return (await self.store.list_conversations())[-limit:]

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.get_conversation(conversation_id)
        return await self.store.get_conversation(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> bool:
        self.store.conversations.pop(conversation_id, None)
        self.store.messages.pop(conversation_id, None)
        self.store.summaries.pop(conversation_id, None)
        self.store.states.pop(conversation_id, None)
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.delete_conversation(conversation_id)
        return True

    async def get_messages(self, conversation_id: str, limit: int = 20) -> list[Message]:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.get_messages(conversation_id, limit)
        return await self.store.get_messages(conversation_id, limit)

    async def get_context(self, conversation_id: str, limit: int | None = None) -> ConversationContext | None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return None
        message_limit = self.config.context.recent_messages if limit is None else limit
        messages = await self.get_messages(conversation_id, message_limit)
        summaries = await self.get_summaries(conversation_id, limit=5)
        return ConversationContext(
            conversation=conversation,
            messages=self.context_window.trim(messages),
            summaries=summaries,
            state=self.store.states.get(conversation_id, {}),
        )

    async def get_summaries(
        self, conversation_id: str, limit: int = 10
    ) -> list[ConversationSummary]:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.get_summaries(conversation_id, limit)
        return await self.store.get_summaries(conversation_id, limit)

    async def get_state(self, conversation_id: str, namespace: str) -> dict:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.get_state(conversation_id, namespace)
        return await self.store.get_state(conversation_id, namespace)

    async def set_state(self, conversation_id: str, namespace: str, value: dict) -> None:
        await self.store.set_state(conversation_id, namespace, value)
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.set_state(conversation_id, namespace, value)

    def _scope_from_message(self, message: Message) -> ConversationScope:
        raw_scope = message.raw.get("scope") or self.config.default_scope
        if raw_scope in {"private", "group", "channel", "agent_task", "system"}:
            return raw_scope
        return self.config.default_scope

    def _normalize_conversation_id(self, message: Message, conversation_id: str) -> str:
        if ":" in conversation_id:
            return conversation_id
        scope = self._scope_from_message(message)
        return f"{message.platform}:{message.adapter}:{scope}:{conversation_id}"

    async def _auto_summarize_if_needed(self, conversation_id: str) -> None:
        if not self.config.context.auto_summarize:
            return
        threshold = self.config.context.summary_every_messages
        if threshold <= 0:
            return
        total = await self._count_messages(conversation_id)
        if total == 0 or total % threshold != 0:
            return
        messages = await self.get_messages(conversation_id, limit=threshold)
        if not messages:
            return
        summary = ConversationSummary(
            conversation_id=conversation_id,
            from_message_id=messages[0].id,
            to_message_id=messages[-1].id,
            summary=self._summarize_messages(messages, total),
        )
        await self._save_summary(summary)

    async def _count_messages(self, conversation_id: str) -> int:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.count_messages(conversation_id)
        return await self.store.count_messages(conversation_id)

    async def _save_summary(self, summary: ConversationSummary) -> ConversationSummary:
        await self.store.save_summary(summary)
        if self.repository_provider:
            async with self.repository_provider() as repo:
                return await repo.save_summary(summary)
        return summary

    def _summarize_messages(self, messages: list[Message], total: int) -> str:
        lines = [
            f"Conversation summary after {total} messages.",
            f"Covered message ids: {messages[0].id} -> {messages[-1].id}.",
            "Recent facts:",
        ]
        for message in messages[-20:]:
            content = (message.content or "").replace("\r", " ").replace("\n", " ").strip()
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(
                f"- sender={message.sender_id} type={message.type} at={message.timestamp.isoformat()} content={content}"
            )
        return "\n".join(lines)

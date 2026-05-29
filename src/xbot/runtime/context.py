from __future__ import annotations

from dataclasses import dataclass
from contextlib import asynccontextmanager

from xbot.adapters.registry import AdapterRegistry
from xbot.agent.runtime import AgentRuntime
from xbot.conversations.manager import ConversationManager
from xbot.core.config import Settings
from xbot.core.events import EventBus
from xbot.messaging.consumer import MessageConsumer
from xbot.messaging.dedupe import DedupeService
from xbot.messaging.message_store import InMemoryMessageStore
from xbot.messaging.pipeline import MessagePipeline
from xbot.messaging.queue import MessageQueue
from xbot.messaging.queue_factory import create_message_queue
from xbot.plugins.manager import PluginManager
from xbot.runtime.engine import XBotEngine
from xbot.skills.manager import SkillManager
from xbot.storage.session import Storage


@dataclass(slots=True)
class AppContext:
    settings: Settings
    events: EventBus
    storage: Storage
    plugins: PluginManager
    skills: SkillManager
    adapters: AdapterRegistry
    message_queue: MessageQueue
    messages: InMemoryMessageStore
    conversations: ConversationManager
    consumer: MessageConsumer
    agent: AgentRuntime
    engine: XBotEngine


def build_context(settings: Settings) -> AppContext:
    events = EventBus()
    storage = Storage(settings.storage)
    message_queue = create_message_queue(settings.queue)
    @asynccontextmanager
    async def message_repository_provider():
        async with storage.session_factory() as session:
            async with session.begin():
                yield storage.messages(session)

    @asynccontextmanager
    async def conversation_repository_provider():
        async with storage.session_factory() as session:
            async with session.begin():
                yield storage.conversations(session)

    @asynccontextmanager
    async def plugin_repository_provider():
        async with storage.session_factory() as session:
            async with session.begin():
                yield storage.plugins(session)

    @asynccontextmanager
    async def skill_repository_provider():
        async with storage.session_factory() as session:
            async with session.begin():
                yield storage.skills(session)

    @asynccontextmanager
    async def agent_repository_provider():
        async with storage.session_factory() as session:
            async with session.begin():
                yield storage.agent(session)

    messages = InMemoryMessageStore(
        repository_provider=message_repository_provider
        if settings.storage.persist_runtime_events
        else None,
    )
    conversations = ConversationManager(
        settings.conversation,
        repository_provider=conversation_repository_provider
        if settings.storage.persist_runtime_events
        else None,
    )
    plugins = PluginManager(
        settings.plugins,
        repository_provider=plugin_repository_provider
        if settings.storage.persist_runtime_events
        else None,
    )
    skills = SkillManager(
        settings.skills,
        repository_provider=skill_repository_provider
        if settings.storage.persist_runtime_events
        else None,
    )
    adapters = AdapterRegistry(settings.adapters, queue=message_queue)
    agent = AgentRuntime(
        settings.agent,
        plugins=plugins,
        skills=skills,
        repository_provider=agent_repository_provider
        if settings.storage.persist_runtime_events
        else None,
    )
    engine = XBotEngine(settings)
    engine.attach_managers(plugins=plugins, skills=skills, adapters=adapters)
    engine.attach_storage(storage=storage, message_store=messages)
    plugins.attach_runtime(
        agent=agent,
        send_reply=engine.send_reply,
        conversations=conversations,
        settings=settings,
    )
    consumer = MessageConsumer(
        dedupe=DedupeService(),
        pipeline=MessagePipeline(),
        conversations=conversations,
        engine=engine,
        message_store=messages,
    )
    engine.attach_messaging(consumer=consumer, queue=message_queue)
    return AppContext(
        settings=settings,
        events=events,
        storage=storage,
        plugins=plugins,
        skills=skills,
        adapters=adapters,
        message_queue=message_queue,
        messages=messages,
        conversations=conversations,
        consumer=consumer,
        agent=agent,
        engine=engine,
    )

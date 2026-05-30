from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from xbot.core.config import StorageConfig
from xbot.storage.repositories.agent_repo import AgentRepository
from xbot.storage.repositories.adapter_repo import AdapterRepository
from xbot.storage.repositories.conversation_repo import ConversationRepository
from xbot.storage.repositories.message_repo import MessageRepository
from xbot.storage.repositories.plugin_repo import PluginRepository
from xbot.storage.repositories.skill_repo import SkillRepository
from xbot.storage.models import Base


class Storage:
    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self.engine: AsyncEngine = create_async_engine(config.url, echo=config.echo)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.engine.dispose()

    async def init_schema(self) -> None:
        # Test/dev helper only. Production schema changes go through Alembic.
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def messages(self, session) -> MessageRepository:
        return MessageRepository(session)

    def conversations(self, session) -> ConversationRepository:
        return ConversationRepository(session)

    def plugins(self, session) -> PluginRepository:
        return PluginRepository(session)

    def skills(self, session) -> SkillRepository:
        return SkillRepository(session)

    def agent(self, session) -> AgentRepository:
        return AgentRepository(session)

    def adapters(self, session) -> AdapterRepository:
        return AdapterRepository(session)

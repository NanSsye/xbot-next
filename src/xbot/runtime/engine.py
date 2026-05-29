from __future__ import annotations

import asyncio
from datetime import datetime

from xbot.core.config import Settings
from xbot.core.logging import logger
from xbot.runtime.status import RuntimeStatus


class XBotEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._status = RuntimeStatus(agent_enabled=settings.agent.enabled)
        self._plugins = None
        self._skills = None
        self._adapters = None
        self._consumer = None
        self._queue = None
        self._storage = None
        self._message_store = None
        self._consumer_task: asyncio.Task | None = None

    def attach_managers(self, plugins, skills, adapters) -> None:
        self._plugins = plugins
        self._skills = skills
        self._adapters = adapters

    def attach_messaging(self, consumer, queue) -> None:
        self._consumer = consumer
        self._queue = queue

    def attach_storage(self, storage, message_store=None) -> None:
        self._storage = storage
        self._message_store = message_store

    async def start(self) -> None:
        if self._status.state == "running":
            return
        self._status.state = "starting"
        if self._plugins and self.settings.plugins.auto_load:
            await self._plugins.load_all()
        if self._skills and self.settings.skills.auto_load:
            await self._skills.load_all()
        if self._adapters:
            await self._adapters.start_enabled()
        if self._consumer and self._queue and self._consumer_task is None:
            self._consumer_task = asyncio.create_task(
                self._consumer.run(self._queue), name="xbot-message-consumer"
            )
        self._status.state = "running"
        self._status.started_at = datetime.utcnow()
        self._refresh_counts()
        logger.info("XBotEngine started")

    async def stop(self) -> None:
        if self._status.state in {"stopped", "created"}:
            self._status.state = "stopped"
            return
        self._status.state = "stopping"
        if self._adapters:
            await self._adapters.stop_all()
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        if self._queue:
            await self._queue.close()
        self._status.state = "stopped"
        self._status.stopped_at = datetime.utcnow()
        self._refresh_counts()
        logger.info("XBotEngine stopped")

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def dispatch_message(self, message) -> None:
        if self._plugins:
            await self._plugins.dispatch_message(message)

    async def send_reply(self, reply) -> None:
        if self._message_store:
            await self._message_store.add_reply(reply)
        elif self._storage and self.settings.storage.persist_runtime_events:
            async with self._storage.session_factory() as session:
                async with session.begin():
                    await self._storage.messages(session).save_reply(reply)
        if self._adapters:
            await self._adapters.send(reply)

    def status(self) -> RuntimeStatus:
        self._refresh_counts()
        return self._status

    def _refresh_counts(self) -> None:
        self._status.plugin_count = len(self._plugins.list_plugins()) if self._plugins else 0
        self._status.skill_count = len(self._skills.list_skills()) if self._skills else 0
        self._status.adapter_count = len(self._adapters.list_adapters()) if self._adapters else 0

from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy import select

from xbot.conversations.models import build_conversation_id
from xbot.core.config import Settings
from xbot.core.events import EventBus
from xbot.core.logging import logger
from xbot.core.timeutils import utc_now
from xbot.messaging.models import Message, Reply
from xbot.runtime.status import RuntimeStatus
from xbot.storage.models import ContactRecord, ConversationRecord


class XBotEngine:
    def __init__(self, settings: Settings, *, events: EventBus | None = None) -> None:
        self.settings = settings
        self._events = events
        self._status = RuntimeStatus(agent_enabled=settings.agent.enabled)
        self._plugins = None
        self._skills = None
        self._adapters = None
        self._consumer = None
        self._queue = None
        self._storage = None
        self._message_store = None
        self._consumer_task: asyncio.Task | None = None
        self._restart_task: asyncio.Task | None = None
        self._agent = None
        self._scheduler = None

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

    def attach_agent(self, agent) -> None:
        self._agent = agent

    def attach_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    async def start(self) -> None:
        if self._status.state == "running":
            return
        self._status.state = "starting"
        if self._plugins and self.settings.plugins.auto_load:
            await self._plugins.load_all()
        if self._skills and self.settings.skills.auto_load:
            await self._skills.load_all()
        if self._agent and self.settings.agent.enabled:
            await self._agent.start()
        if self._adapters:
            await self._adapters.start_enabled()
        if self._scheduler:
            await self._scheduler.start()
        if self._consumer and self._queue and self._consumer_task is None:
            self._start_consumer_task()
        self._status.state = "running"
        self._status.started_at = utc_now()
        self._refresh_counts()
        logger.info("XBotEngine started")

    async def stop(self) -> None:
        if self._status.state in {"stopped", "created"}:
            self._status.state = "stopped"
            return
        self._status.state = "stopping"
        if self._scheduler:
            await self._scheduler.stop()
        if self._adapters:
            await self._adapters.stop_all()
        if self._restart_task:
            self._restart_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._restart_task
            self._restart_task = None
        if self._consumer_task:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
            self._consumer_task = None
        if self._plugins:
            await self._plugins.unload_all()
        if self._agent:
            await self._agent.stop()
        if self._queue:
            await self._queue.close()
        self._status.state = "stopped"
        self._status.stopped_at = utc_now()
        self._refresh_counts()
        logger.info("XBotEngine stopped")

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def dispatch_message(self, message) -> None:
        if self._plugins:
            await self._plugins.dispatch_message(message)

    async def send_reply(self, reply: Reply, *, history_message: Message | None = None) -> object | None:
        if self._message_store:
            await self._message_store.add_reply(reply)
        elif self._storage and self.settings.storage.persist_runtime_events:
            async with self._storage.session_factory() as session, session.begin():
                await self._storage.messages(session).save_reply(reply)
        return await self.deliver_reply(reply, history_message=history_message)

    async def deliver_reply(self, reply: Reply, *, history_message: Message | None = None) -> object | None:
        if not self._adapters:
            return None
        response = await self._adapters.send(reply)
        if self._storage and reply.platform == "wechat" and reply.adapter == "wechat869":
            has_text_receipt = reply.type == "text" and isinstance(response, dict) and response.get("message_id")
            if history_message is not None or (has_text_receipt and self.settings.storage.persist_runtime_events):
                try:
                    await self._record_wechat_reply(reply, history_message)
                except Exception as exc:
                    # A projection failure must not trigger another channel send.
                    logger.error(
                        "WeChat reply sent but workbench update failed: adapter={} error_type={}",
                        reply.adapter, type(exc).__name__,
                    )
        return response

    async def _record_wechat_reply(self, reply: Reply, message: Message | None) -> None:
        scope = "group" if reply.conversation_id.endswith("@chatroom") else "private"
        conversation_id = build_conversation_id(reply.platform, reply.adapter, scope, reply.conversation_id)
        async with self._storage.session_factory() as session, session.begin():
            conversation = await session.get(ConversationRecord, conversation_id)
            if conversation is None or (conversation.platform, conversation.adapter) != (reply.platform, reply.adapter):
                return
            if message is None:
                bot = self.settings.adapters.wechat869
                message = Message(
                    platform=reply.platform, adapter=reply.adapter, conversation_id=conversation_id,
                    sender_id=bot.bot_wxid or "xbot", sender_name=bot.bot_nickname or "AI Bot",
                    content=reply.content, timestamp=utc_now(),
                    raw={"direction": "outgoing", "scope": conversation.scope},
                )
            await self._storage.conversations(session).append_message(conversation_id, message)
            conversation.updated_at = max(conversation.updated_at, message.timestamp)
            avatar = await session.scalar(select(ContactRecord.avatar_url).where(
                ContactRecord.platform == message.platform, ContactRecord.adapter == message.adapter,
                ContactRecord.user_id == message.sender_id,
            ))
        if self._events is not None:
            data = message.model_dump(mode="json")
            data["sender_avatar_url"] = avatar
            data["attachments"] = message.raw.get("attachments", [])
            await self._events.publish("message.created", {"message": data})

    def is_serving(self) -> bool:
        return self._status.state == 'running' and self._consumer_task is not None and not self._consumer_task.done()

    def status(self) -> RuntimeStatus:
        self._refresh_counts()
        return self._status

    def _start_consumer_task(self) -> None:
        if not self._consumer or not self._queue:
            return
        self._consumer_task = asyncio.create_task(
            self._consumer.run(self._queue),
            name="xbot-message-consumer",
        )
        self._consumer_task.add_done_callback(self._on_consumer_done)

    def _on_consumer_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("MessageConsumer 任务异常退出，将自动重启: {}", exc)
        else:
            logger.warning("MessageConsumer 任务已退出，将自动重启")
        self._consumer_task = None
        if self._status.state == "running":
            restart = asyncio.create_task(
                self._restart_consumer_after_delay(), name="xbot-message-consumer-restart"
            )
            self._restart_task = restart
            restart.add_done_callback(lambda _: setattr(self, "_restart_task", None))

    async def _restart_consumer_after_delay(self) -> None:
        await asyncio.sleep(1)
        if self._status.state == "running" and self._consumer_task is None:
            self._start_consumer_task()

    def _refresh_counts(self) -> None:
        self._status.plugin_count = len(self._plugins.list_plugins()) if self._plugins else 0
        self._status.skill_count = len(self._skills.list_skills()) if self._skills else 0
        self._status.adapter_count = len(self._adapters.list_adapters()) if self._adapters else 0

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbot.messaging.models import Message
from xbot.plugins.loader import PluginLoader


def load_agent_chat_plugin():
    path = Path(__file__).resolve().parents[3] / "plugins" / "agent_chat" / "main.py"
    spec = importlib.util.spec_from_file_location("xbot_agent_chat_concurrency", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AgentChatPlugin()


def test_agent_chat_manifest_routes_telegram_messages():
    plugin_dir = Path(__file__).resolve().parents[3] / "plugins" / "agent_chat"
    manifest = PluginLoader().load_manifest(plugin_dir)

    assert "telegram" in manifest.routing.platforms


class ControlledAgent:
    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.started: list[str] = []
        self.finished: list[str] = []
        self._started_events: dict[str, asyncio.Event] = {}
        self._releases: dict[str, asyncio.Event] = {}

    async def run_task(self, input_text: str, source: str = "api"):
        self.inputs.append(input_text)
        marker = next(
            line.removeprefix("content: ")
            for line in reversed(input_text.splitlines())
            if line.startswith("content: ")
        )
        self.started.append(marker)
        self._started_events.setdefault(marker, asyncio.Event()).set()
        release = self._releases.setdefault(marker, asyncio.Event())
        await release.wait()
        self.finished.append(marker)
        return SimpleNamespace(output=f"reply:{marker}")

    def release(self, marker: str) -> None:
        self._releases.setdefault(marker, asyncio.Event()).set()

    def started_event(self, marker: str) -> asyncio.Event:
        return self._started_events.setdefault(marker, asyncio.Event())


def message(message_id: str, content: str, *, mentioned: bool = True) -> Message:
    return Message(
        id=message_id,
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test-group",
        sender_id="member-1",
        content=content,
        raw={"scope": "group", "mentions_bot": mentioned},
    )


@pytest.mark.anyio
async def test_agent_work_runs_in_background_without_blocking_next_message():
    plugin = load_agent_chat_plugin()
    agent = ControlledAgent()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    ctx = SimpleNamespace(agent=agent, send_reply=send_reply, settings=None)
    try:
        handled = await asyncio.wait_for(
            plugin.on_message(message("agent-1", "慢问题"), ctx), timeout=0.2
        )
        await asyncio.wait_for(agent.started_event("慢问题").wait(), timeout=0.2)
        ignored = await asyncio.wait_for(
            plugin.on_message(message("ordinary-1", "普通消息", mentioned=False), ctx),
            timeout=0.2,
        )

        assert handled is True
        assert ignored is False
        assert replies == []

        task = next(iter(plugin._tasks))
        agent.release("慢问题")
        await asyncio.wait_for(task, timeout=0.2)
        assert replies[0].quote_message_id == "agent-1"
    finally:
        await plugin.on_unload()


@pytest.mark.anyio
async def test_wechat_group_persona_is_passed_as_channel_system_context():
    plugin = load_agent_chat_plugin()
    calls = []

    class Agent:
        async def run_task(self, input_text, source="api", channel_context=None):
            calls.append({"input": input_text, "source": source, "channel_context": channel_context})
            return SimpleNamespace(output="done")

    class Conversations:
        async def get_conversation(self, conversation_id):
            assert conversation_id == "wechat:wechat869:group:group-1@chatroom"
            return SimpleNamespace(
                agent_persona_enabled=True,
                agent_persona_prompt="你叫群小助手，只用简短中文回答。",
            )

    settings = SimpleNamespace(
        agent=SimpleNamespace(uses_hermes_runtime=True),
        adapters=SimpleNamespace(wechat869=SimpleNamespace(default_profile="guest")),
    )
    ctx = SimpleNamespace(
        agent=Agent(),
        conversations=Conversations(),
        settings=settings,
        adapters=None,
    )
    message = Message(
        id="wechat-persona-1",
        platform="wechat",
        adapter="wechat869",
        conversation_id="group-1@chatroom",
        sender_id="member-1",
        content="你好",
        raw={"scope": "group", "mentions_bot": True},
    )

    await plugin._run_agent(message, ctx, "你好")

    assert calls[0]["channel_context"]["group_persona_prompt"] == "你叫群小助手，只用简短中文回答。"


@pytest.mark.anyio
async def test_agent_messages_stay_serial_within_one_conversation():
    plugin = load_agent_chat_plugin()
    agent = ControlledAgent()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    ctx = SimpleNamespace(agent=agent, send_reply=send_reply, settings=None)
    try:
        assert await plugin.on_message(message("agent-1", "第一条"), ctx) is True
        await asyncio.wait_for(agent.started_event("第一条").wait(), timeout=0.2)
        assert await plugin.on_message(message("agent-2", "第二条"), ctx) is True
        tasks = list(plugin._tasks)
        await asyncio.sleep(0)
        assert agent.started == ["第一条"]

        agent.release("第一条")
        await asyncio.wait_for(agent.started_event("第二条").wait(), timeout=0.2)
        assert agent.finished == ["第一条"]

        agent.release("第二条")
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.2)
        assert [reply.content for reply in replies] == ["reply:第一条", "reply:第二条"]
        assert [reply.quote_message_id for reply in replies] == ["agent-1", "agent-2"]
    finally:
        await plugin.on_unload()


@pytest.mark.anyio
async def test_telegram_agent_reply_uses_markdown() -> None:
    plugin = load_agent_chat_plugin()
    agent = ControlledAgent()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    ctx = SimpleNamespace(agent=agent, send_reply=send_reply, settings=None)
    incoming = Message(
        id="telegram-1",
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:private:42",
        sender_id="42",
        content="你好",
        raw={"scope": "private", "mentions_bot": True},
    )
    try:
        assert await plugin.on_message(incoming, ctx) is True
        await asyncio.wait_for(agent.started_event("你好").wait(), timeout=0.2)
        task = next(iter(plugin._tasks))
        agent.release("你好")
        await asyncio.wait_for(task, timeout=0.2)

        assert replies[0].type == "markdown"
        assert "telegram_reply_style: Use concise Telegram Markdown" in agent.inputs[0]
    finally:
        await plugin.on_unload()


@pytest.mark.anyio
async def test_telegram_group_xbot_command_sends_only_argument_to_agent() -> None:
    plugin = load_agent_chat_plugin()
    agent = ControlledAgent()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    ctx = SimpleNamespace(agent=agent, send_reply=send_reply, settings=None)
    incoming = Message(
        id="telegram-group-1",
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:group:-123",
        sender_id="42",
        content="/xbot 帮我看看",
        raw={"scope": "group", "mentions_bot": True},
    )
    try:
        assert await plugin.on_message(incoming, ctx) is True
        await asyncio.wait_for(agent.started_event("帮我看看").wait(), timeout=0.2)
        task = next(iter(plugin._tasks))
        agent.release("帮我看看")
        await asyncio.wait_for(task, timeout=0.2)

        assert replies[0].type == "markdown"
    finally:
        await plugin.on_unload()


@pytest.mark.anyio
async def test_telegram_group_help_is_replied_without_agent() -> None:
    plugin = load_agent_chat_plugin()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    ctx = SimpleNamespace(agent=ControlledAgent(), send_reply=send_reply, settings=None)
    incoming = Message(
        id="telegram-group-help",
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:group:-123",
        sender_id="42",
        content="/help",
        raw={"scope": "group", "mentions_bot": True},
    )

    assert await plugin.on_message(incoming, ctx) is True
    assert len(replies) == 1
    assert replies[0].type == "markdown"
    assert "/xbot 内容" in replies[0].content
    assert ctx.agent.inputs == []


@pytest.mark.anyio
async def test_unload_cancels_pending_agent_work():
    plugin = load_agent_chat_plugin()
    agent = ControlledAgent()

    async def send_reply(reply):
        raise AssertionError(f"unexpected reply: {reply}")

    ctx = SimpleNamespace(agent=agent, send_reply=send_reply, settings=None)
    assert await plugin.on_message(message("agent-1", "不会完成"), ctx) is True
    await asyncio.wait_for(agent.started_event("不会完成").wait(), timeout=0.2)

    await asyncio.wait_for(plugin.on_unload(), timeout=0.2)

    assert plugin._tasks == set()
    assert plugin._conversation_locks == {}

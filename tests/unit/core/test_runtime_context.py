import pytest
from contextlib import asynccontextmanager

from xbot.core.config import PluginConfig, load_settings
from xbot.adapters.registry import AdapterRegistry
from xbot.messaging.message_store import InMemoryMessageStore
from xbot.messaging.models import Message, MessageEnvelope, Reply
from xbot.plugins.manager import PluginManager
from xbot.plugins.manifest import PluginManifest, PluginRouting
from xbot.runtime.context import build_context


class FakeAdapterRepository:
    def __init__(self) -> None:
        self.states: dict[str, dict] = {}

    async def get_state(self, adapter: str) -> dict:
        return dict(self.states.get(adapter, {}))

    async def set_state(self, adapter: str, state: dict) -> None:
        self.states[adapter] = dict(state)


@pytest.mark.anyio
async def test_context_start_loads_plugin_skill_and_tools():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    await ctx.engine.start()
    try:
        assert ctx.engine.status().state == "running"
        assert any(plugin["name"] == "echo" for plugin in ctx.plugins.list_plugins())
        assert any(skill["name"] == "code_assistant" for skill in ctx.skills.list_skills())
        assert any(tool["name"] == "read_file" for tool in ctx.agent.tools.list_tools())
        assert any(tool["name"] == "skill_manage" for tool in ctx.agent.tools.list_tools())
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_in_memory_message_store():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    message = Message(
        platform="web",
        adapter="web",
        conversation_id="test",
        sender_id="tester",
        content="hello",
    )
    await ctx.messages.add_message(message)
    recent = await ctx.messages.recent_messages()
    await ctx.storage.close()
    assert recent[-1].content == "hello"


class FakeMessageRepository:
    def __init__(self):
        self.messages = []
        self.envelopes = []
        self.replies = []

    async def save_message(self, message):
        self.messages.append(message)

    async def save_envelope(self, envelope):
        self.envelopes.append(envelope)

    async def save_reply(self, reply):
        self.replies.append(reply)

    async def recent_messages(self, limit=50):
        return self.messages[-limit:]

    async def recent_replies(self, limit=50):
        return self.replies[-limit:]


class FakeAgentResult:
    output = "agent reply"


@pytest.mark.anyio
async def test_exclusive_plugin_blocks_fallback_even_when_it_returns_false():
    calls: list[str] = []

    class ExclusivePlugin:
        async def on_message(self, message, ctx):
            calls.append("exclusive")
            return False

    class FallbackPlugin:
        async def on_message(self, message, ctx):
            calls.append("fallback")
            return True

    manager = PluginManager(PluginConfig())
    manager._plugins = {
        "exclusive": ExclusivePlugin(),
        "fallback": FallbackPlugin(),
    }
    manager._manifests = {
        "exclusive": PluginManifest(
            name="exclusive",
            entry="main:ExclusivePlugin",
            routing=PluginRouting(
                enabled=True,
                priority=10,
                exclusive=True,
                message_types=["text"],
                platforms=["wechat"],
            ),
        ),
        "fallback": PluginManifest(
            name="fallback",
            entry="main:FallbackPlugin",
            routing=PluginRouting(
                enabled=True,
                priority=10000,
                fallback=True,
                message_types=["text"],
                platforms=["wechat"],
            ),
        ),
    }

    await manager.dispatch_message(
        Message(
            platform="wechat",
            adapter="wechat869",
            conversation_id="wxid_user",
            sender_id="wxid_user",
            content="你好",
            raw={"scope": "private"},
        )
    )

    assert calls == ["exclusive"]
    suppress_channel_reply = False


class FakeAgent:
    def __init__(self):
        self.inputs = []

    async def run_task(self, input_text: str, source: str = "api"):
        self.inputs.append((input_text, source))
        return FakeAgentResult()


class AttachmentAwareAgent:
    def __init__(self):
        self.inputs = []

    async def run_task(self, input_text: str, source: str = "api", attachments=None):
        self.inputs.append((input_text, source, attachments or []))
        return FakeAgentResult()


class SuppressingAgent(FakeAgent):
    async def run_task(self, input_text: str, source: str = "api"):
        self.inputs.append((input_text, source))

        class Result:
            output = "已发送。"
            suppress_channel_reply = True
            task_id = "task-1"

        return Result()


class SlowAgent:
    async def run_task(self, input_text: str, source: str = "api"):
        import anyio

        await anyio.sleep(2)
        return FakeAgentResult()


@pytest.mark.anyio
async def test_message_store_uses_repository_provider_for_reads_and_writes():
    repo = FakeMessageRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    store = InMemoryMessageStore(repository_provider=provider)
    message = Message(
        platform="web",
        adapter="web",
        conversation_id="repo-test",
        sender_id="tester",
        content="persisted message",
    )
    envelope = MessageEnvelope.from_message(message)
    reply = Reply(platform="web", adapter="web", conversation_id="repo-test", content="persisted reply")

    await store.add_message(message)
    await store.add_envelope(envelope)
    await store.add_reply(reply)

    assert repo.envelopes[-1].id == envelope.id
    assert (await store.recent_messages())[-1].content == "persisted message"
    assert (await store.recent_replies())[-1].content == "persisted reply"


@pytest.mark.anyio
async def test_context_registers_wechat869_adapter_when_enabled():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    settings.adapters.wechat869.enabled = True
    settings.adapters.wechat869.token_key = "token"
    ctx = build_context(settings)
    try:
        adapters = {item["name"] for item in ctx.adapters.list_adapters()}
        assert "wechat869" in adapters
    finally:
        await ctx.storage.close()


@pytest.mark.anyio
async def test_message_consumer_dedupe_and_conversation_touch():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    await ctx.engine.start()
    try:
        message = Message(
            platform="web",
            adapter="web",
            conversation_id="tester",
            sender_id="tester",
            content="hello conversation",
            raw={"id": "msg-1"},
        )
        envelope = MessageEnvelope.from_message(message)
        assert await ctx.consumer.handle(envelope) is True
        assert await ctx.consumer.handle(envelope) is False

        conversation_id = "web:web:private:tester"
        conversation = await ctx.conversations.get_conversation(conversation_id)
        assert conversation is not None
        messages = await ctx.conversations.get_messages(conversation_id)
        assert messages[-1].content == "hello conversation"
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_plugin_and_skill_enable_disable():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    await ctx.engine.start()
    try:
        assert await ctx.plugins.disable("echo") is True
        assert all(not p["enabled"] for p in ctx.plugins.list_plugins() if p["name"] == "echo")
        assert await ctx.plugins.enable("echo") is True
        assert any(p["enabled"] for p in ctx.plugins.list_plugins() if p["name"] == "echo")

        assert await ctx.skills.disable("code_assistant") is True
        assert ctx.skills.get_instructions("code_assistant") is None
        assert await ctx.skills.enable("code_assistant") is True
        assert ctx.skills.get_instructions("code_assistant")
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_adapter_enabled_state_persists_across_registry_restart():
    settings = load_settings("configs/xbot.toml")
    repo = FakeAdapterRepository()
    repo.states["web"] = {"enabled": False}

    @asynccontextmanager
    async def provider():
        yield repo

    registry = AdapterRegistry(settings.adapters, repository_provider=provider)
    await registry.start_enabled()
    assert registry.get("web") is None
    assert any(item["name"] == "web" and item["persistent_enabled"] is False for item in registry.list_adapters())

    adapter = await registry.enable("web")
    assert adapter is not None
    assert repo.states["web"]["enabled"] is True
    await registry.stop_all()

    restarted = AdapterRegistry(settings.adapters, repository_provider=provider)
    await restarted.start_enabled()
    assert restarted.get("web") is not None
    assert restarted.get("web").started is True
    await restarted.stop_all()


@pytest.mark.anyio
async def test_engine_send_reply_records_and_sends_with_runtime_persistence_disabled():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    await ctx.engine.start()
    try:
        reply = Reply(
            platform="web",
            adapter="web",
            conversation_id="web:web:private:test",
            content="reply",
        )
        await ctx.engine.send_reply(reply)
        replies = await ctx.messages.recent_replies()
        assert replies[-1].content == "reply"
        web_adapter = ctx.adapters._adapters["web"]
        assert web_adapter.sent_replies[-1].content == "reply"
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_handles_private_text_as_fallback():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    fake_agent = FakeAgent()
    ctx.plugins.attach_runtime(agent=fake_agent, send_reply=ctx.engine.send_reply)
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat869",
            conversation_id="wxid_sender",
            sender_id="wxid_sender",
            sender_name="张三",
            content="你是谁",
            raw={
                "id": "private-agent-1",
                "scope": "private",
                "sender_wxid": "wxid_sender",
                "sender_name": "张三",
                "private_wxid": "wxid_sender",
                "conversation_wxid": "wxid_sender",
            },
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        replies = await ctx.messages.recent_replies()
        assert fake_agent.inputs
        assert "你是谁" in fake_agent.inputs[-1][0]
        assert "sender_wxid: wxid_sender" in fake_agent.inputs[-1][0]
        assert "sender_name: 张三" in fake_agent.inputs[-1][0]
        assert "private_wxid: wxid_sender" in fake_agent.inputs[-1][0]
        assert replies[-1].adapter == "wechat869"
        assert replies[-1].conversation_id == "wxid_sender"
        assert replies[-1].content == "agent reply"
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_does_not_auto_reply_after_explicit_wechat_send():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    fake_agent = SuppressingAgent()
    ctx.plugins.attach_runtime(agent=fake_agent, send_reply=ctx.engine.send_reply)
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            sender_id="u1",
            content="什么情况？",
            raw={
                "id": "ilink-explicit-send-1",
                "scope": "private",
                "mentions_bot": True,
            },
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        replies = await ctx.messages.recent_replies()
        assert fake_agent.inputs
        assert replies == []
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_passes_media_attachments_to_agent():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    fake_agent = AttachmentAwareAgent()
    ctx.plugins.attach_runtime(
        agent=fake_agent,
        send_reply=ctx.engine.send_reply,
        conversations=ctx.conversations,
        settings=settings,
    )
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat869",
            type="image",
            conversation_id="wxid_sender",
            sender_id="wxid_sender",
            content="[图片] local_path=data/wechat869/media/img.jpg",
            raw={
                "id": "private-image-1",
                "scope": "private",
                "sender_wxid": "wxid_sender",
                "sender_name": "张三",
                "private_wxid": "wxid_sender",
                "conversation_wxid": "wxid_sender",
                "attachments": [
                    {
                        "kind": "image",
                        "filename": "img.jpg",
                        "mime": "image/jpeg",
                        "size": 10,
                        "download_status": "downloaded",
                        "local_path": "data/wechat869/media/img.jpg",
                        "sha256": "abc",
                    }
                ],
                "quote": {
                    "message_id": "quoted-1",
                    "sender_wxid": "wxid_other",
                    "sender_name": "李四",
                    "msg_type": 3,
                    "content": "quoted image",
                    "attachments": [
                        {
                            "kind": "image",
                            "filename": "quoted.jpg",
                            "mime": "image/jpeg",
                            "size": 20,
                            "download_status": "downloaded",
                            "local_path": "data/wechat869/media/quoted.jpg",
                        }
                    ],
                },
            },
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        agent_input = fake_agent.inputs[-1][0]
        agent_attachments = fake_agent.inputs[-1][2]
        assert "message_attachments:" in agent_input
        assert "local_path=data/wechat869/media/img.jpg" in agent_input
        assert "quoted_message:" in agent_input
        assert "local_path=data/wechat869/media/quoted.jpg" in agent_input
        assert [item["local_path"] for item in agent_attachments] == [
            "data/wechat869/media/img.jpg",
            "data/wechat869/media/quoted.jpg",
        ]
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_skips_unquoted_ilink_media():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    fake_agent = FakeAgent()
    ctx.plugins.attach_runtime(agent=fake_agent, send_reply=ctx.engine.send_reply)
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            sender_id="u1",
            type="file",
            content="测试.txt",
            raw={
                "scope": "private",
                "attachments": [{"kind": "file", "filename": "测试.txt"}],
            },
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        replies = await ctx.messages.recent_replies()
        assert fake_agent.inputs == []
        assert replies == []
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_passes_quoted_ilink_media_to_agent():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    fake_agent = FakeAgent()
    ctx.plugins.attach_runtime(agent=fake_agent, send_reply=ctx.engine.send_reply)
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            sender_id="u1",
            type="text",
            content="看这个文件",
            raw={
                "scope": "private",
                "quote": {
                    "message_id": "file1",
                    "msg_type": "file",
                    "content": "测试.txt",
                    "attachments": [{"kind": "file", "filename": "测试.txt"}],
                },
            },
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        assert fake_agent.inputs
        agent_input = fake_agent.inputs[-1][0]
        assert "quoted_message:" in agent_input
        assert "filename=测试.txt" in agent_input
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_ignores_group_text_without_mention():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    ctx = build_context(settings)
    fake_agent = FakeAgent()
    ctx.plugins.attach_runtime(agent=fake_agent, send_reply=ctx.engine.send_reply)
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat869",
            conversation_id="123@chatroom",
            sender_id="member_wxid",
            content="普通群消息",
            raw={"id": "group-agent-1", "scope": "group", "mentions_bot": False},
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        replies = await ctx.messages.recent_replies()
        assert fake_agent.inputs == []
        assert replies == []
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()


@pytest.mark.anyio
async def test_agent_chat_plugin_replies_on_agent_timeout():
    settings = load_settings("configs/xbot.toml")
    settings.storage.persist_runtime_events = False
    settings.runtime.timeout.agent_task_seconds = 1
    ctx = build_context(settings)
    ctx.plugins.attach_runtime(
        agent=SlowAgent(),
        send_reply=ctx.engine.send_reply,
        conversations=ctx.conversations,
        settings=settings,
    )
    await ctx.engine.start()
    try:
        message = Message(
            platform="wechat",
            adapter="wechat869",
            conversation_id="123@chatroom",
            sender_id="member_wxid",
            content="@小小x 打开浏览器截图发群里",
            raw={"id": "group-agent-timeout", "scope": "group", "mentions_bot": True},
        )
        await ctx.consumer.handle(MessageEnvelope.from_message(message))

        replies = await ctx.messages.recent_replies()
        assert replies[-1].conversation_id == "123@chatroom"
        assert "超时" in replies[-1].content
    finally:
        await ctx.engine.stop()
        await ctx.storage.close()

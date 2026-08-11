import time
from types import SimpleNamespace

import pytest

from plugins.agent_chat.main import AgentChatPlugin
from xbot.adapters.qq.adapter import QQAdapter
from xbot.adapters.qq.client import QQBotApiError, QQBotClient
from xbot.adapters.registry import AdapterRegistry
from xbot.core.config import AdapterConfig, QQAdapterConfig, Settings
from xbot.messaging.models import Message, Reply


class FakeQueue:
    def __init__(self):
        self.items = []

    async def publish(self, envelope):
        self.items.append(envelope)


class FailingQueue(FakeQueue):
    async def publish(self, envelope):
        raise RuntimeError("queue failed")


class StateRepository:
    def __init__(self):
        self.state = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get_state(self, name):
        return dict(self.state)

    async def set_state(self, name, state):
        self.state = dict(state)


class FakeClient:
    def __init__(self):
        self.sent = []

    async def send_text(self, **payload):
        self.sent.append(payload)
        return {"id": "reply-1"}

    async def close(self):
        return None


class ChannelClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.channel_sent = []

    async def send_channel(self, **payload):
        self.channel_sent.append(payload)
        return {"id": "channel-reply-1"}


class InteractionClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return {"ok": True}


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        self.reason = "fake"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, content_type=None):
        return self.payload

    async def text(self):
        return str(self.payload)


class FakeApiSession:
    def __init__(self):
        self.closed = False
        self.requests = []
        self.token_requests = 0
        self.responses = [
            FakeResponse(401, {"code": 11244, "message": "invalid token"}),
            FakeResponse(200, {"id": "reply-1"}),
        ]

    def post(self, url, **kwargs):
        self.token_requests += 1
        return FakeResponse(200, {"access_token": "fresh-token", "expires_in": 7200})

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


class ClosingWebSocket:
    def __init__(self, close_code):
        self.close_code = close_code
        self.closed = False
        self.sent = []

    async def receive_json(self, **kwargs):
        return {"op": 10, "d": {"heartbeat_interval": 60000}}

    async def send_json(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def close(self):
        self.closed = True


class FakeGatewayClient:
    def __init__(self, websocket):
        self.websocket_instance = websocket

    async def access_token(self):
        return "gateway-token"

    async def gateway_url(self):
        return "wss://gateway.example.invalid"

    async def websocket(self, url):
        return self.websocket_instance


@pytest.mark.anyio
async def test_qq_normalizes_c2c_and_replies_with_original_message_id():
    client = FakeClient()
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret"),
        client_factory=lambda: client,
    )
    message = await adapter.normalize(
        {
            "op": 0,
            "t": "C2C_MESSAGE_CREATE",
            "_event_type": "C2C_MESSAGE_CREATE",
            "d": {
                "id": "msg-1",
                "author": {"user_openid": "user-1", "username": "测试用户"},
                "content": "你好",
                "timestamp": "2026-08-10T10:00:00+08:00",
            },
        }
    )

    assert message.id == "msg-1"
    assert message.platform == "qq"
    assert message.adapter == "qq"
    assert message.conversation_id == "qq:c2c:user-1"
    assert message.sender_id == "user-1"
    assert message.raw["scope"] == "private"
    assert message.timestamp.isoformat() == "2026-08-10T02:00:00"
    assert message.timestamp.tzinfo is None

    await adapter.send(
        Reply(
            platform="qq",
            adapter="qq",
            conversation_id=message.conversation_id,
            content="收到",
            quote_message_id=message.id,
        )
    )

    assert client.sent == [
        {
            "target_type": "c2c",
            "target_id": "user-1",
            "content": "收到",
            "msg_id": "msg-1",
            "msg_seq": 1,
        }
    ]


@pytest.mark.anyio
async def test_qq_normalizes_group_image_and_gateway_publishes():
    queue = FakeQueue()
    adapter = QQAdapter(QQAdapterConfig(), queue=queue)
    websocket = FakeWebSocket()
    payload = {
        "id": "event-1",
        "op": 0,
        "s": 42,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": "msg-group-1",
            "group_openid": "group-1",
            "author": {"member_openid": "member-1", "username": "群成员"},
            "content": "看看图片",
            "attachments": [
                {
                    "content_type": "image/jpeg",
                    "filename": "photo.jpg",
                    "url": "https://example.invalid/photo.jpg",
                    "size": 123,
                }
            ],
        },
    }

    await adapter._handle_gateway_payload(websocket, payload)

    assert adapter.sequence == 42
    assert len(queue.items) == 1
    message = queue.items[0].message
    assert message.type == "image"
    assert message.conversation_id == "qq:group:group-1"
    assert message.raw["scope"] == "group"
    assert message.raw["mentions_bot"] is True
    assert message.raw["attachments"][0]["kind"] == "image"


@pytest.mark.anyio
async def test_qq_gateway_sequence_persists_only_after_queue_publish():
    repo = StateRepository()
    queue = FakeQueue()
    adapter = QQAdapter(QQAdapterConfig(), queue=queue, repository_provider=lambda: repo)
    adapter.sequence = 12
    message = Message(platform="qq", adapter="qq", conversation_id="qq:c2c:u", sender_id="u", content="hi")
    await adapter._publish_message(message)
    assert repo.state["sequence"] == 12

    failed_repo = StateRepository()
    failed = QQAdapter(QQAdapterConfig(), queue=FailingQueue(), repository_provider=lambda: failed_repo)
    failed.sequence = 13
    with pytest.raises(RuntimeError, match="queue failed"):
        await failed._publish_message(message)
    assert failed_repo.state == {}


@pytest.mark.anyio
async def test_qq_gateway_publish_failure_rolls_back_sequence_before_resume():
    repo = StateRepository()
    websocket = ClosingWebSocket(close_code=None)
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret"),
        queue=FailingQueue(),
        client_factory=lambda: FakeGatewayClient(websocket),
        repository_provider=lambda: repo,
    )
    adapter.session_id = "session-1"
    adapter.sequence = 12

    with pytest.raises(RuntimeError, match="queue failed"):
        await adapter._handle_gateway_payload(
            websocket,
            {
                "id": "gateway-message-13",
                "op": 0,
                "s": 13,
                "t": "C2C_MESSAGE_CREATE",
                "d": {
                    "id": "message-13",
                    "author": {"user_openid": "user-1"},
                    "content": "需要重试",
                },
            },
        )

    assert adapter.sequence == 12
    assert repo.state == {}

    await adapter._connect_once()
    assert websocket.sent[0]["op"] == 6
    assert websocket.sent[0]["d"]["seq"] == 12


@pytest.mark.anyio
async def test_qq_gateway_control_and_ignored_events_commit_sequence():
    repo = StateRepository()
    adapter = QQAdapter(
        QQAdapterConfig(channel_enabled=False),
        queue=FakeQueue(),
        repository_provider=lambda: repo,
    )
    websocket = FakeWebSocket()

    await adapter._handle_gateway_payload(
        websocket,
        {
            "op": 0,
            "s": 1,
            "t": "READY",
            "d": {"session_id": "session-1", "user": {"id": "bot-1", "username": "bot"}},
        },
    )
    assert adapter.sequence == 1
    assert repo.state["sequence"] == 1

    await adapter._handle_gateway_payload(websocket, {"op": 0, "s": 2, "t": "RESUMED", "d": {}})
    assert adapter.sequence == 2
    assert repo.state["sequence"] == 2

    # Channel dispatches are intentionally ignored while the capability is
    # disabled, but their cursor is still safe to commit.
    await adapter._handle_gateway_payload(
        websocket,
        {
            "op": 0,
            "s": 3,
            "t": "MESSAGE_CREATE",
            "d": {"id": "channel-message", "channel_id": "channel-1", "content": "ignored"},
        },
    )
    assert adapter.sequence == 3
    assert repo.state["sequence"] == 3
    assert adapter.queue.items == []


@pytest.mark.anyio
async def test_qq_normalizes_voice_and_video_mime_from_urls_when_fields_are_missing():
    adapter = QQAdapter(QQAdapterConfig())
    message = await adapter.normalize(
        {
            "_event_type": "C2C_MESSAGE_CREATE",
            "d": {
                "id": "msg-media",
                "author": {"user_openid": "user-1"},
                "attachments": [
                    {"voice_wav_url": "https://cdn.example.invalid/audio.wav", "asr_refer_text": "你好"},
                    {"url": "https://cdn.example.invalid/video.mp4", "content_type": "video"},
                ],
            },
        }
    )
    voice, video = message.raw["attachments"]
    assert voice["kind"] == "voice"
    assert voice["filename"] == "audio.wav"
    assert voice["mime"] == "audio/wav"
    assert voice["asr_refer_text"] == "你好"
    assert video["kind"] == "video"
    assert video["filename"] == "video.mp4"
    assert video["mime"] == "video/mp4"


@pytest.mark.anyio
async def test_qq_send_splits_long_reply_and_increments_msg_seq():
    client = FakeClient()
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret", max_reply_chars=100),
        client_factory=lambda: client,
    )
    content = "第一段。" * 60

    await adapter.send(
        Reply(
            platform="qq",
            adapter="qq",
            conversation_id="qq:group:group-1",
            content=content,
            quote_message_id="msg-1",
        )
    )

    assert len(client.sent) > 1
    assert [item["msg_seq"] for item in client.sent] == list(range(1, len(client.sent) + 1))
    assert all(len(item["content"]) <= 100 for item in client.sent)


@pytest.mark.anyio
async def test_qq_client_refreshes_access_token_and_retries_one_401():
    session = FakeApiSession()
    client = QQBotClient(
        QQAdapterConfig(app_id="app", client_secret="secret"),
        session=session,
    )
    client._access_token = "stale-token"
    client._access_token_expires_at = time.monotonic() + 3600

    result = await client.request("POST", "/v2/users/user-1/messages", json={"content": "hi"})

    assert result == {"id": "reply-1"}
    assert session.token_requests == 1
    assert [request["headers"]["Authorization"] for request in session.requests] == [
        "QQBot stale-token",
        "QQBot fresh-token",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("close_code", [4006, 4007])
async def test_qq_gateway_invalid_session_close_code_falls_back_to_identify(close_code):
    websocket = ClosingWebSocket(close_code)
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret"),
        client_factory=lambda: FakeGatewayClient(websocket),
    )
    adapter.started = True
    adapter.session_id = "stale-session"
    adapter.sequence = 99

    with pytest.raises(RuntimeError, match="改用 Identify"):
        await adapter._connect_once()

    assert websocket.sent[0]["op"] == 6
    assert adapter.session_id == ""
    assert adapter.sequence is None


@pytest.mark.anyio
async def test_qq_passive_group_reply_is_capped_at_five_messages():
    client = FakeClient()
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret", max_reply_chars=100),
        client_factory=lambda: client,
    )

    await adapter.send(
        Reply(
            platform="qq",
            adapter="qq",
            conversation_id="qq:group:group-1",
            content="内容。" * 240,
            quote_message_id="msg-limit",
        )
    )

    assert len(client.sent) == 5
    assert [item["msg_seq"] for item in client.sent] == [1, 2, 3, 4, 5]
    assert client.sent[-1]["content"].endswith("[回复内容过长，已截断]")
    assert all(len(item["content"]) <= 100 for item in client.sent)


@pytest.mark.anyio
async def test_qq_metadata_msg_id_uses_passive_sequence_and_remaining_quota():
    client = FakeClient()
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret", max_reply_chars=100),
        client_factory=lambda: client,
    )

    await adapter.send(
        Reply(
            platform="qq", adapter="qq", conversation_id="qq:group:group-1",
            content="内容。" * 180, metadata={"msg_id": "msg-meta"},
        )
    )
    assert len(client.sent) == 5
    assert [item["msg_seq"] for item in client.sent] == [1, 2, 3, 4, 5]

    with pytest.raises(QQBotApiError, match="次数已达到"):
        await adapter.send(
            Reply(
                platform="qq", adapter="qq", conversation_id="qq:group:group-1",
                content="再次回复", metadata={"msg_id": "msg-meta"},
            )
        )


@pytest.mark.anyio
async def test_qq_passive_msg_seq_is_shared_across_text_markdown_media_and_text():
    class RichClient(FakeClient):
        async def send_markdown(self, **payload):
            self.sent.append(payload)
            return {"id": f"markdown-{len(self.sent)}"}

        async def send_media(self, **payload):
            self.sent.append(payload)
            return {"id": f"media-{len(self.sent)}"}

    client = RichClient()
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret"),
        client_factory=lambda: client,
    )
    conversation_id = "qq:group:group-1"
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id=conversation_id, content="one", quote_message_id="same-msg"))
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id=conversation_id, type="markdown", content="two", quote_message_id="same-msg"))
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id=conversation_id, type="image", content="ignored", metadata={"file_info": "fi"}, quote_message_id="same-msg"))
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id=conversation_id, content="four", quote_message_id="same-msg"))
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id=conversation_id, content="five", quote_message_id="same-msg"))
    assert [item["msg_seq"] for item in client.sent] == [1, 2, 3, 4, 5]
    with pytest.raises(QQBotApiError, match="次数已达到"):
        await adapter.send(Reply(platform="qq", adapter="qq", conversation_id=conversation_id, content="six", quote_message_id="same-msg"))


@pytest.mark.anyio
async def test_qq_channel_image_requires_explicit_source_and_does_not_send_content_as_url(tmp_path):
    client = ChannelClient()
    adapter = QQAdapter(
        QQAdapterConfig(app_id="app", client_secret="secret", channel_enabled=True, allow_active_messages=True),
        client_factory=lambda: client,
    )
    with pytest.raises(QQBotApiError, match="频道图片回复缺少"):
        await adapter.send(
            Reply(
                platform="qq", adapter="qq", conversation_id="qq:channel:c1",
                type="image", content="这是一段描述，不是 URL",
            )
        )

    image = tmp_path / "photo.png"
    image.write_bytes(b"png")
    await adapter.send(
        Reply(
            platform="qq", adapter="qq", conversation_id="qq:channel:c1",
            type="image", content="描述文本", metadata={"path": str(image)},
        )
    )
    assert client.channel_sent[-1]["image"] == str(image)
    assert client.channel_sent[-1]["content"] == ""


@pytest.mark.anyio
async def test_qq_interaction_group_and_channel_buttons_keep_d_id_as_event_id():
    adapter = QQAdapter(QQAdapterConfig())
    group = await adapter.normalize(
        {
            "id": "gateway-group",
            "_event_type": "INTERACTION_CREATE",
            "d": {
                "id": "interaction-group",
                "type": 11,
                "scene": "group",
                "group_openid": "group-1",
                "user_openid": "member-1",
                "data": {"resolved": {"button_data": "ask", "button_id": "btn-group", "user_id": "member-1"}},
            },
        }
    )
    assert group.conversation_id == "qq:group:group-1"
    assert group.raw["event_id"] == "interaction-group"
    assert group.raw["gateway_event_id"] == "gateway-group"
    assert group.raw["button_data"] == "ask"
    assert group.raw["button_id"] == "btn-group"
    assert group.sender_id == "member-1"

    channel = await adapter.normalize(
        {
            "id": "gateway-channel",
            "_event_type": "INTERACTION_CREATE",
            "d": {
                "id": "interaction-channel",
                "type": 12,
                "scene": "guild",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "data": {"resolved": {"button_data": "open", "button_id": "btn-channel", "user_id": "member-2"}},
            },
        }
    )
    assert channel.conversation_id == "qq:channel:channel-1"
    assert channel.raw["event_id"] == "interaction-channel"
    assert channel.raw["button_data"] == "open"
    assert channel.sender_id == "member-2"


@pytest.mark.anyio
async def test_qq_gateway_acks_and_publishes_only_supported_interaction_types():
    queue = FakeQueue()
    client = InteractionClient()
    adapter = QQAdapter(QQAdapterConfig(), queue=queue, client_factory=lambda: client)
    websocket = FakeWebSocket()

    await adapter._handle_gateway_payload(
        websocket,
        {
            "id": "gateway-11", "op": 0, "t": "INTERACTION_CREATE",
            "d": {"id": "interaction-11", "type": 11, "scene": "group", "group_openid": "g", "user_openid": "u", "data": {"resolved": {"button_data": "x"}}},
        },
    )
    assert len(queue.items) == 1
    assert client.requests == [("PUT", "/interactions/interaction-11", {"json": {"code": 0}})]

    await adapter._handle_gateway_payload(
        websocket,
        {
            "id": "gateway-13", "op": 0, "t": "INTERACTION_CREATE",
            "d": {"id": "interaction-13", "type": 13, "scene": "group", "group_openid": "g", "user_openid": "u", "data": {"resolved": {"button_data": "ignored"}}},
        },
    )
    assert len(queue.items) == 1
    assert len(client.requests) == 1


def test_qq_agent_route_rejects_auxiliary_events_and_unknown_interactions():
    plugin = AgentChatPlugin()

    def message(raw):
        return Message(platform="qq", adapter="qq", conversation_id="qq:c2c:u", sender_id="u", content="x", raw=raw)

    assert plugin._should_handle(message({"scope": "private", "qq_event_type": "INTERACTION_CREATE", "interaction_type": 11}))
    assert not plugin._should_handle(message({"scope": "private", "qq_event_type": "INTERACTION_CREATE", "interaction_type": 13}))
    assert not plugin._should_handle(message({"scope": "private", "qq_event_type": "MESSAGE_REACTION_ADD"}))


@pytest.mark.anyio
async def test_qq_stream_indexes_increment_and_clear_per_conversation():
    class StreamClient(FakeClient):
        async def stream_message(self, **payload):
            self.sent.append(payload)
            return {"id": "stream-1"}

    client = StreamClient()
    adapter = QQAdapter(QQAdapterConfig(app_id="app", client_secret="secret", allow_active_messages=True), client_factory=lambda: client)
    for state, content in ((1, "first"), (1, "second"), (10, "done")):
        await adapter.send(
            Reply(
                platform="qq", adapter="qq", conversation_id="qq:c2c:u",
                type="stream", content=content, metadata={"input_state": state},
            )
        )
    assert [item["index"] for item in client.sent] == [0, 1, 2]
    assert [item.get("stream_msg_id") for item in client.sent] == [None, "stream-1", "stream-1"]
    assert "qq:c2c:u" not in adapter._stream_ids
    assert "qq:c2c:u" not in adapter._stream_indexes
    assert "qq:c2c:u" not in adapter._stream_reply_sequences


@pytest.mark.anyio
async def test_qq_stream_passive_fragments_reuse_first_msg_seq():
    class PassiveStreamClient(FakeClient):
        async def stream_message(self, **payload):
            self.sent.append(payload)
            return {"id": "stream-passive"}

    client = PassiveStreamClient()
    adapter = QQAdapter(QQAdapterConfig(), client_factory=lambda: client)
    for state, content in ((1, "first"), (1, "next"), (10, "done")):
        await adapter.send(
            Reply(
                platform="qq", adapter="qq", conversation_id="qq:c2c:u",
                type="stream", content=content, quote_message_id="incoming",
                metadata={"input_state": state},
            )
        )
    assert [item["msg_seq"] for item in client.sent] == [1, 1, 1]
    assert [item["index"] for item in client.sent] == [0, 1, 2]


@pytest.mark.anyio
async def test_qq_stream_new_trigger_message_resets_unfinished_stream_state():
    class PassiveStreamClient(FakeClient):
        async def stream_message(self, **payload):
            self.sent.append(payload)
            return {"id": f"stream-{len(self.sent)}"}

    client = PassiveStreamClient()
    adapter = QQAdapter(QQAdapterConfig(), client_factory=lambda: client)
    conversation_id = "qq:c2c:u"

    await adapter.send(
        Reply(
            platform="qq", adapter="qq", conversation_id=conversation_id,
            type="stream", content="first", quote_message_id="incoming-1",
        )
    )
    await adapter.send(
        Reply(
            platform="qq", adapter="qq", conversation_id=conversation_id,
            type="stream", content="continuation", quote_message_id="incoming-1",
        )
    )
    # The first stream is intentionally left unfinished.  A different
    # incoming message must start at stream index zero with a fresh stream id
    # and its own passive sequence binding.
    await adapter.send(
        Reply(
            platform="qq", adapter="qq", conversation_id=conversation_id,
            type="stream", content="new message", quote_message_id="incoming-2",
        )
    )
    await adapter.send(
        Reply(
            platform="qq", adapter="qq", conversation_id=conversation_id,
            type="stream", content="done", quote_message_id="incoming-2",
            metadata={"input_state": 10},
        )
    )

    assert [item["msg_seq"] for item in client.sent] == [1, 1, 1, 1]
    assert [item["index"] for item in client.sent] == [0, 1, 0, 1]
    assert [item.get("stream_msg_id") for item in client.sent] == [None, "stream-1", None, "stream-3"]
    assert "qq:c2c:u" not in adapter._stream_reply_sequences


@pytest.mark.anyio
async def test_qq_stream_failure_clears_stream_lifecycle_state():
    class FailingStreamClient(FakeClient):
        async def stream_message(self, **payload):
            raise QQBotApiError("stream failed")

    adapter = QQAdapter(QQAdapterConfig(), client_factory=FailingStreamClient)
    with pytest.raises(QQBotApiError, match="stream failed"):
        await adapter.send(
            Reply(
                platform="qq", adapter="qq", conversation_id="qq:c2c:u",
                type="stream", content="first", quote_message_id="incoming",
            )
        )
    assert "qq:c2c:u" not in adapter._stream_ids
    assert "qq:c2c:u" not in adapter._stream_indexes
    assert "qq:c2c:u" not in adapter._stream_reply_sequences


@pytest.mark.anyio
async def test_qq_client_reaction_uses_numeric_emoji_type_and_rejects_get_or_empty_ids():
    class ReactionClient(QQBotClient):
        def __init__(self):
            super().__init__(QQAdapterConfig())
            self.calls = []

        async def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return {"ok": True}

    client = ReactionClient()
    await client.react(channel_id="c", message_id="m", reaction_type="emoji", reaction_id="128077")
    assert client.calls[0][0:2] == ("PUT", "/channels/c/messages/m/reactions/2/128077")
    with pytest.raises(QQBotApiError, match="只支持 PUT 或 DELETE"):
        await client.react(channel_id="c", message_id="m", reaction_type="2", reaction_id="128077", method="GET")
    with pytest.raises(QQBotApiError, match="缺少"):
        await client.react(channel_id="", message_id="m", reaction_type="2", reaction_id="128077")


@pytest.mark.anyio
async def test_qq_client_and_adapter_reject_empty_text():
    client = QQBotClient(QQAdapterConfig())
    with pytest.raises(QQBotApiError, match="内容不能为空"):
        await client.send_text(target_type="c2c", target_id="u", content="  ")
    adapter = QQAdapter(QQAdapterConfig())
    with pytest.raises(QQBotApiError, match="内容不能为空"):
        adapter._split_text("\t", 100)


@pytest.mark.anyio
async def test_qq_group_card_is_not_exposed_or_sent():
    adapter = QQAdapter(QQAdapterConfig(allow_active_messages=True), client_factory=FakeClient)
    with pytest.raises(QQBotApiError, match="不支持的 QQ Reply 类型"):
        await adapter.send(
            Reply(
                platform="qq", adapter="qq", conversation_id="qq:group:g",
                type="card", content="card", metadata={"card": {}},
            )
        )


@pytest.mark.anyio
async def test_qq_start_without_credentials_stays_stopped():
    adapter = QQAdapter(QQAdapterConfig())
    await adapter.start()
    assert adapter.started is False
    assert adapter.public_status()["started"] is False
    assert "AppID" in adapter.last_error


def test_registry_lists_qq_even_when_disabled_and_can_construct_it():
    disabled = AdapterRegistry(AdapterConfig())
    item = next(item for item in disabled.list_adapters() if item["name"] == "qq")
    assert item["platform"] == "qq"
    assert item["enabled"] is False

    enabled = AdapterRegistry(
        AdapterConfig(qq=QQAdapterConfig(enabled=True, app_id="app", client_secret="secret"))
    )
    assert isinstance(enabled.get("qq"), QQAdapter)


def test_qq_channel_permissions_default_to_guest_and_honor_lists():
    plugin = AgentChatPlugin()
    settings = Settings()
    settings.adapters.qq = QQAdapterConfig(
        admin_openids=["admin-1"],
        member_openids=["member-1"],
        default_profile="guest",
    )
    ctx = SimpleNamespace(settings=settings)

    def message(sender: str) -> Message:
        return Message(
            platform="qq",
            adapter="qq",
            conversation_id="qq:group:g1",
            sender_id=sender,
            content="测试",
            raw={"scope": "group", "member_openid": sender, "mentions_bot": True},
        )

    assert plugin._tool_permission_profile(message("admin-1"), ctx) == "admin"
    assert plugin._tool_permission_profile(message("member-1"), ctx) == "member"
    assert plugin._tool_permission_profile(message("other"), ctx) == "guest"


def test_channel_context_uses_message_adapter_media_root_not_qq_for_wechat():
    plugin = AgentChatPlugin()
    settings = Settings()
    settings.adapters.qq.media_dir = "qq-media"
    settings.adapters.wechat869.media_dir = "wechat-media"
    message = Message(
        platform="wechat", adapter="wechat869", conversation_id="wxid-1",
        sender_id="member-1", content="测试", raw={"scope": "private"},
    )
    context = plugin._channel_context(message, SimpleNamespace(settings=settings, adapters=None))
    assert "wechat-media" in context["media_roots"]
    assert "qq-media" not in context["media_roots"]

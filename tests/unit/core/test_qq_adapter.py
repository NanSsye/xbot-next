import time
from types import SimpleNamespace

import pytest

from plugins.agent_chat.main import AgentChatPlugin
from xbot.adapters.qq.adapter import QQAdapter
from xbot.adapters.qq.client import QQBotClient
from xbot.adapters.registry import AdapterRegistry
from xbot.core.config import AdapterConfig, QQAdapterConfig, Settings
from xbot.messaging.models import Message, Reply


class FakeQueue:
    def __init__(self):
        self.items = []

    async def publish(self, envelope):
        self.items.append(envelope)


class FakeClient:
    def __init__(self):
        self.sent = []

    async def send_text(self, **payload):
        self.sent.append(payload)
        return {"id": "reply-1"}

    async def close(self):
        return None


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

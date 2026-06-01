from __future__ import annotations

from pathlib import Path

import pytest

from xbot.messaging.models import Message
from xbot.plugins.context import PluginContext

from plugins.openclaw_bridge.main import OpenClawBridgePlugin


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = "ok"
        self.content = b"{}"

    def json(self):
        return self._payload


class FakeAsyncClient:
    calls = []
    responses = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, json=None, headers=None):
        self.calls.append({"url": url, "json": json or {}, "headers": headers or {}})
        return self.responses.pop(0)


def _ctx(tmp_path: Path, **config):
    return PluginContext(
        name="openclaw_bridge",
        data_dir=tmp_path,
        config={
            "bridge_url": "http://bridge.local",
            "shared_secret": "secret",
            "agent_id": "main",
            "timeout_seconds": 30,
            **config,
        },
        send_reply=lambda reply: None,
    )


@pytest.mark.anyio
async def test_openclaw_bridge_private_message_calls_reply(monkeypatch, tmp_path):
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [FakeResponse({"text": "收到"})]
    monkeypatch.setattr("plugins.openclaw_bridge.main.httpx.AsyncClient", FakeAsyncClient)

    plugin = OpenClawBridgePlugin()
    message = Message(
        id="m1",
        platform="wechat",
        adapter="wechat869",
        conversation_id="wxid_user",
        sender_id="wxid_user",
        content="你好",
        raw={"scope": "private", "sender_wxid": "wxid_user", "message_id": "m1"},
    )

    result = await plugin.on_message(message, _ctx(tmp_path))

    assert result is True
    assert FakeAsyncClient.calls[0]["url"] == "http://bridge.local/reply"
    assert FakeAsyncClient.calls[0]["headers"]["X-OpenClaw-Secret"] == "secret"
    assert FakeAsyncClient.calls[0]["json"]["session_id"] == "private:wxid_user"
    assert FakeAsyncClient.calls[0]["json"]["need_reply"] is True


@pytest.mark.anyio
async def test_openclaw_bridge_group_untriggered_stores_context(monkeypatch, tmp_path):
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [FakeResponse({"accepted": True})]
    monkeypatch.setattr("plugins.openclaw_bridge.main.httpx.AsyncClient", FakeAsyncClient)

    plugin = OpenClawBridgePlugin()
    message = Message(
        id="m2",
        platform="wechat",
        adapter="wechat869",
        conversation_id="room@chatroom",
        sender_id="wxid_user",
        content="普通群聊",
        raw={
            "scope": "group",
            "sender_wxid": "wxid_user",
            "group_wxid": "room@chatroom",
            "mentions_bot": False,
        },
    )

    result = await plugin.on_message(message, _ctx(tmp_path))

    assert result is True
    assert FakeAsyncClient.calls[0]["url"] == "http://bridge.local/store_message"
    assert FakeAsyncClient.calls[0]["json"]["session_id"] == "group:room@chatroom:user:wxid_user"


@pytest.mark.anyio
async def test_openclaw_bridge_ignores_self_message_before_bridge_call(monkeypatch, tmp_path):
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [FakeResponse({"accepted": True})]
    monkeypatch.setattr("plugins.openclaw_bridge.main.httpx.AsyncClient", FakeAsyncClient)

    plugin = OpenClawBridgePlugin()
    message = Message(
        id="self1",
        platform="wechat",
        adapter="wechat869",
        conversation_id="room@chatroom",
        sender_id="wxid_bot",
        sender_name="小小x",
        content="学姐 自己发的消息",
        raw={
            "scope": "group",
            "sender_wxid": "wxid_bot",
            "group_member_wxid": "wxid_bot",
            "group_wxid": "room@chatroom",
            "bot_wxid": "wxid_bot",
            "bot_nickname": "小小x",
        },
    )

    result = await plugin.on_message(message, _ctx(tmp_path))

    assert result is False
    assert FakeAsyncClient.calls == []

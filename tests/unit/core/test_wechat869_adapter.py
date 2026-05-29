from __future__ import annotations

import pytest

from xbot.adapters.wechat869.adapter import Wechat869Adapter
from xbot.adapters.wechat869.client import Wechat869Client
from xbot.core.config import Wechat869AdapterConfig
from xbot.messaging.models import Reply


class FakeClient869:
    def __init__(self) -> None:
        self.sent = []
        self.token_key = ""
        self.wxid = ""
        self.nickname = ""

    def _append_key_to_ws_url(self, ws_url: str, key: str) -> str:
        separator = "&" if "?" in ws_url else "?"
        return f"{ws_url}{separator}key={key}"

    def append_key_to_ws_url(self, ws_url: str, key: str) -> str:
        return self._append_key_to_ws_url(ws_url, key)

    async def send_text_message(self, wxid: str, content: str, at=None):
        self.sent.append((wxid, content, at))
        return 1, 2, 3


@pytest.mark.anyio
async def test_wechat869_normalizes_private_text_message() -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig())

    message = await adapter.normalize(
        {
            "message": {
                "msg_id": 123,
                "msg_type": 1,
                "from_user_name": "wxid_sender",
                "to_user_name": "wxid_bot",
                "content": "hello",
                "push_content": "张三 : hello",
            }
        }
    )

    assert message.id == "123"
    assert message.platform == "wechat"
    assert message.adapter == "wechat869"
    assert message.conversation_id == "wxid_sender"
    assert message.sender_id == "wxid_sender"
    assert message.sender_name == "张三"
    assert message.raw["sender_wxid"] == "wxid_sender"
    assert message.raw["sender_name"] == "张三"
    assert message.raw["private_wxid"] == "wxid_sender"
    assert message.content == "hello"
    assert message.raw["scope"] == "private"


@pytest.mark.anyio
async def test_wechat869_normalizes_group_text_and_mentions() -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig(bot_nickname="xbot"))

    message = await adapter.normalize(
        {
            "MsgId": 456,
            "MsgType": 1,
            "FromUserName": {"str": "123@chatroom"},
            "Content": {"str": "member_wxid:\n@xbot ping"},
            "push_content": "李四 : @xbot ping",
            "IsGroup": True,
        }
    )

    assert message.conversation_id == "123@chatroom"
    assert message.sender_id == "member_wxid"
    assert message.sender_name == "李四"
    assert message.raw["group_wxid"] == "123@chatroom"
    assert message.raw["group_member_wxid"] == "member_wxid"
    assert message.content == "@xbot ping"
    assert message.raw["scope"] == "group"
    assert message.raw["mentions_bot"] is True


@pytest.mark.anyio
async def test_wechat869_send_text_reply_uses_raw_conversation_id() -> None:
    client = FakeClient869()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(token_key="token"),
        client_factory=lambda: client,
    )
    await adapter.start()

    await adapter.send(
        Reply(
            platform="wechat",
            adapter="wechat869",
            conversation_id="wechat:wechat869:group:123@chatroom",
            content="reply",
        )
    )

    assert client.sent[-1][0] == "123@chatroom"
    assert client.sent[-1][1] == "reply"


def test_wechat869_internal_client_appends_ws_key() -> None:
    client = Wechat869Client("127.0.0.1", 5253)

    assert (
        client.append_key_to_ws_url("ws://127.0.0.1:5253/ws/GetSyncMsg", "token")
        == "ws://127.0.0.1:5253/ws/GetSyncMsg?key=token"
    )
    assert (
        client.append_key_to_ws_url("ws://127.0.0.1:5253/ws/GetSyncMsg?key=old", "token")
        == "ws://127.0.0.1:5253/ws/GetSyncMsg?key=old"
    )


def test_wechat869_internal_client_extracts_send_tuple() -> None:
    client = Wechat869Client("127.0.0.1", 5253)

    assert client._extract_send_tuple(
        [
            {
                "resp": {
                    "chat_send_ret_list": [
                        {
                            "ClientMsgId": 1,
                            "CreateTime": 2,
                            "NewMsgId": 3,
                        }
                    ]
                }
            }
        ]
    ) == (1, 2, 3)


def test_wechat869_extracts_nested_json_string_message() -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig())

    messages = adapter._extract_messages(
        {
            "key": "hidden",
            "type": "message",
            "message": '{"msg_id": "json-1", "msg_type": 1, "from_user_name": "wxid_sender", "content": "hello"}',
        }
    )

    assert messages == [
        {
            "msg_id": "json-1",
            "msg_type": 1,
            "from_user_name": "wxid_sender",
            "content": "hello",
        }
    ]

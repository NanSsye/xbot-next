from __future__ import annotations

import base64

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

    async def download_image(self, aes_key: str, cdn_url: str):
        return b"\xff\xd8\xfffake-jpeg"

    async def download_file(self, aes_key: str, file_url: str):
        return b"file-bytes"

    async def download_attach(self, attach_id: str):
        return b"attach-bytes"


class FakeQueue:
    def __init__(self) -> None:
        self.items = []

    async def publish(self, envelope):
        self.items.append(envelope)


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
async def test_wechat869_uses_msg_source_atuserlist_for_mentions() -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig())

    message = await adapter.normalize(
        {
            "MsgId": 457,
            "MsgType": 1,
            "FromUserName": {"str": "123@chatroom"},
            "ToUserName": {"str": "wxid_bot"},
            "Content": {"str": "member_wxid:\n@小小x 你好"},
            "MsgSource": "<msgsource><atuserlist>wxid_bot</atuserlist></msgsource>",
        }
    )

    assert message.raw["bot_wxid"] == "wxid_bot"
    assert message.raw["at_user_list"] == ["wxid_bot"]
    assert message.raw["mentions_bot"] is True


@pytest.mark.anyio
async def test_wechat869_uses_cdata_msg_source_atuserlist_for_mentions() -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig())

    message = await adapter.normalize(
        {
            "msg_id": 459,
            "msg_type": 1,
            "from_user_name": {"str": "44694849727@chatroom"},
            "to_user_name": {"str": "wxid_p60yfpl5zg2m29"},
            "content": {"str": "wxid_3ic17l92pics22:\n@小小x 写一个skill"},
            "msg_source": (
                "<msgsource><atuserlist><![CDATA[wxid_p60yfpl5zg2m29]]></atuserlist>"
                "<membercount>8</membercount></msgsource>"
            ),
        }
    )

    assert message.raw["bot_wxid"] == "wxid_p60yfpl5zg2m29"
    assert message.raw["at_user_list"] == ["wxid_p60yfpl5zg2m29"]
    assert message.raw["mentions_bot"] is True


@pytest.mark.anyio
async def test_wechat869_does_not_fallback_to_nickname_when_atuserlist_targets_other_user() -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig(bot_nickname="小小x"))

    message = await adapter.normalize(
        {
            "MsgId": 458,
            "MsgType": 1,
            "FromUserName": {"str": "123@chatroom"},
            "ToUserName": {"str": "wxid_bot"},
            "Content": {"str": "member_wxid:\n@别人 小小x 你看看"},
            "MsgSource": "<msgsource><atuserlist>wxid_other</atuserlist></msgsource>",
        }
    )

    assert message.raw["at_user_list"] == ["wxid_other"]
    assert message.raw["mentions_bot"] is False


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


@pytest.mark.anyio
async def test_wechat869_ignores_self_system_messages() -> None:
    queue = FakeQueue()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(bot_wxid="wxid_bot"),
        queue=queue,
    )

    await adapter._handle_ws_text(
        '{"message":{"msg_id": "sys-1", "msg_type": 51, '
        '"from_user_name": {"str": "wxid_bot"}, '
        '"to_user_name": {"str": "wxid_bot"}, '
        '"content": {"str": "<msg><op id=\\"11\\"></op></msg>"}}}'
    )

    assert queue.items == []


@pytest.mark.anyio
async def test_wechat869_ignores_official_account_messages() -> None:
    queue = FakeQueue()
    adapter = Wechat869Adapter(Wechat869AdapterConfig(), queue=queue)

    await adapter._handle_ws_text(
        '{"message":{"msg_id": "gh-1", "msg_type": 1, '
        '"from_user_name": {"str": "gh_official"}, '
        '"to_user_name": {"str": "wxid_bot"}, '
        '"content": {"str": "公众号消息"}}}'
    )

    assert queue.items == []


@pytest.mark.anyio
async def test_wechat869_ignores_builtin_system_conversations() -> None:
    queue = FakeQueue()
    adapter = Wechat869Adapter(Wechat869AdapterConfig(), queue=queue)

    await adapter._handle_ws_text(
        '{"message":{"msg_id": "news-1", "msg_type": 1, '
        '"from_user_name": {"str": "newsapp"}, '
        '"to_user_name": {"str": "wxid_bot"}, '
        '"content": {"str": "新闻消息"}}}'
    )

    assert queue.items == []


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


def test_wechat869_internal_client_extracts_short_base64_payload() -> None:
    client = Wechat869Client("127.0.0.1", 5253)

    assert client._extract_base64_from_payload({"FileData": base64.b64encode(b"short").decode("ascii")})


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


@pytest.mark.anyio
async def test_wechat869_normalizes_image_message_and_saves_media(tmp_path) -> None:
    image_data = b"\xff\xd8\xffimage"
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(media_dir=str(tmp_path), text_only=False),
    )

    message = await adapter.normalize(
        {
            "MsgId": "img-1",
            "MsgType": 3,
            "FromUserName": "wxid_sender",
            "File": base64.b64encode(image_data).decode("ascii"),
            "Filename": "photo.jpg",
        }
    )

    assert message.type == "image"
    assert "[图片]" in (message.content or "")
    attachment = message.raw["attachments"][0]
    assert attachment["kind"] == "image"
    assert attachment["download_status"] == "downloaded"
    assert attachment["local_path"]
    assert (tmp_path / "2026").exists() or attachment["local_path"].startswith(str(tmp_path))


@pytest.mark.anyio
async def test_wechat869_downloads_quoted_image_from_cdn(tmp_path) -> None:
    client = FakeClient869()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(media_dir=str(tmp_path), text_only=False),
        client_factory=lambda: client,
    )
    await adapter.start()

    message = await adapter.normalize(
        {
            "MsgId": "quote-1",
            "MsgType": 49,
            "FromUserName": "wxid_sender",
            "Content": "看图",
            "Quote": {
                "MsgType": 3,
                "NewMsgId": "img-quoted",
                "Content": "quoted-image",
                "aeskey": "aes",
                "cdnmidimgurl": "https://cdn/image",
            },
        }
    )

    quote = message.raw["quote"]
    attachment = quote["attachments"][0]
    assert message.type == "file"
    assert attachment["kind"] == "image"
    assert attachment["download_status"] == "downloaded"
    assert attachment["local_path"]


@pytest.mark.anyio
async def test_wechat869_keeps_quoted_file_metadata_when_no_download_url(tmp_path) -> None:
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(media_dir=str(tmp_path), text_only=False, auto_download_files=False)
    )

    message = await adapter.normalize(
        {
            "MsgId": "quote-file-1",
            "MsgType": 49,
            "FromUserName": "wxid_sender",
            "Content": "看文件",
            "Quote": {
                "MsgType": 49,
                "XmlType": 6,
                "NewMsgId": "file-1",
                "Content": "report.pdf",
                "appattach": {
                    "attachid": "attach-id",
                    "fileext": "pdf",
                    "totallen": 1234,
                },
            },
        }
    )

    attachment = message.raw["quote"]["attachments"][0]
    assert attachment["kind"] == "file"
    assert attachment["filename"] == "report.pdf"
    assert attachment["download_status"] == "metadata_only"


@pytest.mark.anyio
async def test_wechat869_downloads_quoted_file_by_attachid(tmp_path) -> None:
    client = FakeClient869()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(media_dir=str(tmp_path), text_only=False),
        client_factory=lambda: client,
    )
    await adapter.start()

    message = await adapter.normalize(
        {
            "MsgId": "quote-file-download",
            "MsgType": 49,
            "FromUserName": "wxid_sender",
            "Content": "看文件",
            "Quote": {
                "MsgType": 49,
                "XmlType": 6,
                "NewMsgId": "file-download-1",
                "Content": "report.txt",
                "appattach": {
                    "attachid": "@cdn_fileurl_aeskey_1",
                    "fileext": "txt",
                    "totallen": 12,
                },
            },
        }
    )

    attachment = message.raw["quote"]["attachments"][0]
    assert attachment["kind"] == "file"
    assert attachment["download_status"] == "downloaded"
    assert attachment["local_path"]
    assert attachment["size"] == len(b"attach-bytes")


@pytest.mark.anyio
async def test_wechat869_parses_group_prefixed_file_xml_metadata(tmp_path) -> None:
    adapter = Wechat869Adapter(Wechat869AdapterConfig(media_dir=str(tmp_path), text_only=False))

    message = await adapter.normalize(
        {
            "MsgId": "file-xml-1",
            "MsgType": 49,
            "FromUserName": {"str": "room@chatroom"},
            "Content": {
                "str": "member_wxid:\n"
                "<?xml version=\"1.0\"?>\n"
                "<msg><appmsg><title>测试.txt</title><type>6</type>"
                "<appattach><totallen>18</totallen><attachid>attach-id</attachid>"
                "<fileext>txt</fileext></appattach></appmsg></msg>"
            },
            "IsGroup": True,
        }
    )

    attachment = message.raw["attachments"][0]
    assert message.type == "file"
    assert attachment["kind"] == "file"
    assert attachment["filename"] == "测试.txt"
    assert attachment["size"] == 18
    assert attachment["download_status"] == "download_empty"
    assert "测试.txt" in (message.content or "")

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


class FakeLoginClient869(FakeClient869):
    def __init__(self) -> None:
        super().__init__()
        self.admin_key = "admin"
        self.auth_key = "auth"
        self.auth_keys = ["auth"]
        self.poll_key = ""
        self.display_uuid = ""
        self.login_tx_id = ""
        self.data62 = ""
        self.ticket = ""
        self.device_id = ""
        self.device_type = "ipad"
        self.wakeup_ok = False
        self.poll_logged_in = False
        self.profile_refreshed = False

    async def try_wakeup_login(self):
        return self.wakeup_ok

    async def get_login_qrcode(self, *, device_type="ipad", device_id="", proxy=""):
        self.device_type = device_type
        self.device_id = device_id or "device-1"
        self.token_key = "token-1"
        self.poll_key = "poll-1"
        self.display_uuid = "display-1"
        self.login_tx_id = "tx-1"
        self.data62 = "data62"
        return {
            "qrcode": "uuid-1",
            "uuid": "uuid-1",
            "qr_url": "http://weixin.qq.com/x/uuid-1",
            "token_key": self.token_key,
            "poll_key": self.poll_key,
            "display_uuid": self.display_uuid,
            "login_tx_id": self.login_tx_id,
            "data62": self.data62,
            "device_id": self.device_id,
            "login_mode": self.device_type,
        }

    async def poll_login_status(self):
        if self.poll_logged_in:
            self.wxid = "wxid_bot"
            self.nickname = "小小x"
            self.token_key = "token-final"
            return {
                "logged_in": True,
                "status": "online",
                "bot_wxid": self.wxid,
                "bot_nickname": self.nickname,
                "token_key": self.token_key,
            }
        return {"logged_in": False, "status": "waiting_login"}

    async def get_login_status(self):
        await self.refresh_profile()
        return {
            "logged_in": True,
            "status": "online",
            "bot_wxid": self.wxid,
            "bot_nickname": self.nickname,
        }

    async def refresh_profile(self):
        self.profile_refreshed = True
        self.wxid = self.wxid or "wxid_bot"
        self.nickname = self.nickname or "小小x"
        return {"userInfo": {"UserName": self.wxid, "NickName": {"string": self.nickname}}}


class FakeAdapterRepo:
    def __init__(self, state):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_state(self, adapter):
        return self.state.get(adapter, {})

    async def set_state(self, adapter, value):
        self.state[adapter] = value


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
async def test_wechat869_ignores_self_group_text_from_to_user_fallback() -> None:
    queue = FakeQueue()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(bot_nickname="小小x"),
        queue=queue,
    )

    await adapter._handle_ws_text(
        '{"message":{"msg_id": "self-1", "msg_type": 1, '
        '"from_user_name": {"str": "123@chatroom"}, '
        '"to_user_name": {"str": "wxid_bot"}, '
        '"content": {"str": "wxid_bot:\\n学姐 我刚刚回复的内容"}}}'
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


@pytest.mark.anyio
async def test_wechat869_client_status_loads_profile_when_login_status_has_no_wxid(monkeypatch) -> None:
    async def fake_request(self, path, *, body=None, method="POST", key=None):
        if path == "/login/GetLoginStatus":
            return {"Code": 0, "Data": {"Status": 0}}
        if path == "/user/GetProfile":
            return {
                "Code": 200,
                "Data": {
                    "userInfo": {
                        "userName": {"str": "wxid_profile"},
                        "nickName": {"str": "小小x"},
                    }
                },
                "Success": False,
            }
        return {"Code": 0}

    monkeypatch.setattr(Wechat869Client, "request", fake_request)
    client = Wechat869Client("127.0.0.1", 5253, token_key="token")

    status = await client.get_login_status()

    assert status["logged_in"] is True
    assert status["bot_wxid"] == "wxid_profile"
    assert status["bot_nickname"] == "小小x"
    assert status["profile_loaded"] is True


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


@pytest.mark.anyio
async def test_wechat869_login_start_persists_qrcode_state() -> None:
    state = {}
    client = FakeLoginClient869()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(enabled=True, admin_key="admin"),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )

    result = await adapter.start_login()

    assert result["logged_in"] is False
    assert result["qr_url"] == "http://weixin.qq.com/x/uuid-1"
    assert result["qr_image_url"].startswith(("data:image/png;base64,", "https://api.qrserver.com/"))
    assert state["wechat869"]["token_key"] == "token-1"
    assert state["wechat869"]["poll_key"] == "poll-1"
    assert state["wechat869"]["qrcode"] == "uuid-1"


@pytest.mark.anyio
async def test_wechat869_login_poll_persists_success_state() -> None:
    state = {"wechat869": {"token_key": "token-1", "poll_key": "poll-1", "qrcode": "uuid-1"}}
    client = FakeLoginClient869()
    client.poll_logged_in = True
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(enabled=True, admin_key="admin"),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )

    result = await adapter.poll_login_status()

    assert result["logged_in"] is True
    assert result["bot_wxid"] == "wxid_bot"
    assert result["bot_nickname"] == "小小x"
    assert state["wechat869"]["token_key"] == "token-final"
    assert state["wechat869"]["bot_wxid"] == "wxid_bot"
    assert state["wechat869"]["bot_nickname"] == "小小x"
    assert state["wechat869"]["qrcode"] == ""


@pytest.mark.anyio
async def test_wechat869_env_token_key_takes_priority_over_persisted_state() -> None:
    state = {"wechat869": {"token_key": "persisted-token", "poll_key": "persisted-poll"}}
    client = FakeLoginClient869()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(enabled=True, admin_key="admin", token_key="env-token"),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )

    await adapter.start()
    await adapter.stop()

    assert adapter.config.token_key == "env-token"
    assert client.token_key == "env-token"


@pytest.mark.anyio
async def test_wechat869_refreshed_public_status_fetches_profile_from_env_token() -> None:
    state = {}
    client = FakeLoginClient869()
    adapter = Wechat869Adapter(
        Wechat869AdapterConfig(enabled=True, admin_key="admin", token_key="env-token"),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )
    await adapter.start()

    status = await adapter.refreshed_public_status()
    await adapter.stop()

    assert status["logged_in"] is True
    assert status["login_status"] == "online"
    assert status["bot_wxid"] == "wxid_bot"
    assert status["bot_nickname"] == "小小x"
    assert state["wechat869"]["bot_wxid"] == "wxid_bot"
    assert state["wechat869"]["bot_nickname"] == "小小x"

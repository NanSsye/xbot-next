import asyncio
import base64
from pathlib import Path

import pytest

from xbot.adapters.registry import AdapterRegistry
from xbot.adapters.wechat_ilink.adapter import WechatIlinkAdapter
from xbot.adapters.wechat_ilink.client import WechatIlinkClient
from xbot.core.config import AdapterConfig, Wechat869AdapterConfig, WechatIlinkAdapterConfig
from xbot.messaging.models import Reply


class FakeQueue:
    def __init__(self):
        self.items = []

    async def publish(self, envelope):
        self.items.append(envelope)


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


class FakeClient:
    def __init__(self):
        self.sent = []
        self.payload = {"get_updates_buf": "next", "msgs": []}
        self.qrcode_payload = {"qrcode": "qr1", "qrcode_img_content": "https://qr.local/qr1.png"}
        self.status_payload = {
            "status": "confirmed",
            "bot_token": "new-token",
            "ilink_bot_id": "bot-1",
            "ilink_user_id": "user-1",
            "baseurl": "https://ilink-runtime.local",
        }

    async def get_updates(self, cursor):
        self.cursor = cursor
        return self.payload

    async def send_text(self, *, to_user_id, context_token, text):
        self.sent.append(
            {
                "type": "text",
                "to_user_id": to_user_id,
                "context_token": context_token,
                "text": text,
            }
        )

    async def send_image(self, *, to_user_id, context_token, path, text=""):
        self.sent.append(
            {
                "type": "image",
                "to_user_id": to_user_id,
                "context_token": context_token,
                "path": path,
                "text": text,
            }
        )

    async def send_file(self, *, to_user_id, context_token, path, name=None, text=""):
        self.sent.append(
            {
                "type": "file",
                "to_user_id": to_user_id,
                "context_token": context_token,
                "path": path,
                "name": name,
                "text": text,
            }
        )

    async def download_cdn(self, url):
        self.downloaded_url = url
        return b""

    async def get_qr_code(self):
        return self.qrcode_payload

    async def poll_qr_status(self, qrcode, *, base_url=None):
        self.qrcode = qrcode
        self.base_url = base_url
        return self.status_payload


@pytest.mark.anyio
async def test_wechat_ilink_normalizes_text_and_remembers_reply_target():
    client = FakeClient()
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token"),
        client_factory=lambda: client,
    )
    message = await adapter.normalize(
        {
            "msg_id": "m1",
            "message_type": 1,
            "from_user_id": "u1",
            "context_token": "ctx1",
            "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        }
    )

    assert message.id == "m1"
    assert message.adapter == "wechat_ilink"
    assert message.platform == "wechat"
    assert message.type == "text"
    assert message.conversation_id == "ilink:u1"
    assert message.sender_id == "u1"
    assert message.content == "你好"
    assert message.raw["context_token"] == "ctx1"

    await adapter.send(
        Reply(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            content="收到",
        )
    )

    assert client.sent == [{"type": "text", "to_user_id": "u1", "context_token": "ctx1", "text": "收到"}]


@pytest.mark.anyio
async def test_wechat_ilink_sends_image_and_file_replies(tmp_path):
    client = FakeClient()
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token"),
        client_factory=lambda: client,
    )
    await adapter.normalize(
        {
            "msg_id": "m1",
            "message_type": 1,
            "from_user_id": "u1",
            "context_token": "ctx1",
            "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
        }
    )
    image = tmp_path / "out.png"
    file = tmp_path / "report.pdf"
    image.write_bytes(b"image")
    file.write_bytes(b"file")

    await adapter.send(
        Reply(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            type="image",
            content=str(image),
        )
    )
    await adapter.send(
        Reply(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            type="file",
            content=str(file),
        )
    )

    assert client.sent[-2]["type"] == "image"
    assert client.sent[-2]["path"] == str(image)
    assert client.sent[-1]["type"] == "file"
    assert client.sent[-1]["path"] == str(file)


@pytest.mark.anyio
async def test_wechat_ilink_normalizes_file_message():
    adapter = WechatIlinkAdapter(WechatIlinkAdapterConfig())
    message = await adapter.normalize(
        {
            "msg_id": "file1",
            "message_type": 1,
            "from_user_id": "u1",
            "context_token": "ctx1",
            "item_list": [{"type": 4, "file_item": {"file_name": "report.pdf"}}],
        }
    )

    assert message.type == "file"
    assert message.content == "report.pdf"
    assert message.raw["attachments"][0]["kind"] == "file"
    assert message.raw["attachments"][0]["filename"] == "report.pdf"


@pytest.mark.anyio
async def test_wechat_ilink_poll_publishes_messages_and_updates_cursor():
    queue = FakeQueue()
    client = FakeClient()
    client.payload = {
        "get_updates_buf": "cursor-next",
        "msgs": [
            {
                "msg_id": "m1",
                "message_type": 1,
                "from_user_id": "u1",
                "context_token": "ctx1",
                "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
            },
            {"msg_id": "ignore", "message_type": 2},
        ],
    }
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token", cursor="cursor-start"),
        queue=queue,
        client_factory=lambda: client,
    )
    adapter.client = client

    await adapter._poll_once()

    assert adapter.cursor == "cursor-next"
    assert len(queue.items) == 1
    assert queue.items[0].message.content == "hi"
    assert client.cursor == "cursor-start"


@pytest.mark.anyio
async def test_wechat_ilink_poll_ignores_self_messages():
    queue = FakeQueue()
    client = FakeClient()
    client.payload = {
        "get_updates_buf": "cursor-next",
        "msgs": [
            {
                "msg_id": "self1",
                "message_type": 1,
                "from_user_id": "bot-1",
                "context_token": "ctx1",
                "item_list": [{"type": 1, "text_item": {"text": "学姐 自己发的消息"}}],
            }
        ],
    }
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token", bot_wxid="bot-1"),
        queue=queue,
        client_factory=lambda: client,
    )
    adapter.client = client

    await adapter._poll_once()

    assert queue.items == []


@pytest.mark.anyio
async def test_wechat_ilink_defers_unquoted_file_messages():
    queue = FakeQueue()
    client = FakeClient()
    client.payload = {
        "get_updates_buf": "cursor-next",
        "msgs": [
            {
                "msg_id": "file1",
                "message_type": 1,
                "from_user_id": "u1",
                "context_token": "ctx1",
                "item_list": [{"type": 4, "file_item": {"file_name": "测试.txt"}}],
            }
        ],
    }
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token"),
        queue=queue,
        client_factory=lambda: client,
    )
    adapter.client = client

    await adapter._poll_once()

    assert queue.items == []


@pytest.mark.anyio
async def test_wechat_ilink_publishes_text_with_quoted_file():
    queue = FakeQueue()
    client = FakeClient()
    client.payload = {
        "get_updates_buf": "cursor-next",
        "msgs": [
            {
                "msg_id": "quote1",
                "message_type": 1,
                "from_user_id": "u1",
                "context_token": "ctx1",
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": "看这个文件"},
                        "ref_msg": {
                            "message_id": "file1",
                            "from_user_id": "u1",
                            "message_item": {
                                "type": 4,
                                "file_item": {"file_name": "测试.txt", "file_size": 18},
                            },
                        },
                    }
                ],
            }
        ],
    }
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token"),
        queue=queue,
        client_factory=lambda: client,
    )
    adapter.client = client

    await adapter._poll_once()

    assert len(queue.items) == 1
    message = queue.items[0].message
    assert message.type == "text"
    assert message.content == "看这个文件"
    assert message.raw["quote"]["msg_type"] == "file"
    assert message.raw["quote"]["attachments"][0]["filename"] == "测试.txt"


@pytest.mark.anyio
async def test_wechat_ilink_downloads_quoted_file_to_channel_media_dir(tmp_path):
    queue = FakeQueue()
    client = FakeClient()
    media_client = WechatIlinkClient("https://ilink.local", "token")
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    encrypted = media_client._encrypt_aes_ecb(b"hello file", key)

    async def fake_download(url):
        client.downloaded_url = url
        return encrypted

    client.download_cdn = fake_download
    client.payload = {
        "get_updates_buf": "cursor-next",
        "msgs": [
            {
                "msg_id": "quote1",
                "message_type": 1,
                "from_user_id": "u1",
                "context_token": "ctx1",
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": "看这个文件"},
                        "ref_msg": {
                            "message_id": "file1",
                            "from_user_id": "u1",
                            "message_item": {
                                "type": 4,
                                "file_item": {
                                    "file_name": "测试.txt",
                                    "len": "10",
                                    "media": {
                                        "encrypt_query_param": "download-token",
                                        "aes_key": base64.b64encode(key.hex().encode("ascii")).decode("ascii"),
                                        "encrypt_type": 1,
                                    },
                                },
                            },
                        },
                    }
                ],
            }
        ],
    }
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(token="token", media_dir=str(tmp_path / "ilink-media")),
        queue=queue,
        client_factory=lambda: client,
    )
    adapter.client = client

    await adapter._poll_once()

    attachment = queue.items[0].message.raw["quote"]["attachments"][0]
    assert attachment["download_status"] == "downloaded"
    assert attachment["source"] == "wechat_ilink"
    assert (tmp_path / "ilink-media") in Path(attachment["local_path"]).parents
    assert Path(attachment["local_path"]).read_bytes() == b"hello file"


def test_adapter_registry_can_enable_wechat869_and_ilink_together():
    registry = AdapterRegistry(
        AdapterConfig(
            wechat869=Wechat869AdapterConfig(enabled=True, token_key="token"),
            wechat_ilink=WechatIlinkAdapterConfig(enabled=True, token="ilink-token"),
        )
    )

    names = {item["name"] for item in registry.list_adapters()}
    assert "wechat869" in names
    assert "wechat_ilink" in names


@pytest.mark.anyio
async def test_wechat_ilink_qr_login_updates_runtime_token():
    client = FakeClient()
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(enabled=True, base_url="https://ilink.local"),
        client_factory=lambda: client,
    )
    adapter.client = client

    qrcode = await adapter.get_login_qrcode()
    status = await adapter.poll_login_status()

    assert qrcode["qrcode"] == "qr1"
    assert status["logged_in"] is True
    assert status["account_id"] == "bot-1"
    assert adapter.config.token == "new-token"
    assert adapter.config.base_url == "https://ilink-runtime.local"
    assert adapter.config.bot_wxid == "bot-1"
    assert client.qrcode == "qr1"
    assert client.base_url == "https://ilink.local"


@pytest.mark.anyio
async def test_wechat_ilink_persists_login_state_and_restores_on_start():
    state = {}
    client = FakeClient()
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(enabled=True, base_url="https://ilink.local"),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )
    adapter.client = client

    await adapter.get_login_qrcode()
    await adapter.poll_login_status()

    assert state["wechat_ilink"]["token"] == "new-token"
    assert state["wechat_ilink"]["base_url"] == "https://ilink-runtime.local"
    assert state["wechat_ilink"]["bot_wxid"] == "bot-1"

    restored = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(enabled=True),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )
    await restored.start()
    await restored.stop()

    assert restored.config.token == "new-token"
    assert restored.config.base_url == "https://ilink-runtime.local"
    assert restored.config.bot_wxid == "bot-1"


@pytest.mark.anyio
async def test_wechat_ilink_start_fetches_qrcode_when_no_token():
    client = FakeClient()
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(enabled=True, base_url="https://ilink.local"),
        client_factory=lambda: client,
    )
    adapter.client = client

    await adapter.start()
    await adapter.stop()

    assert adapter._login_qrcode == "qr1"
    assert adapter._task is None


@pytest.mark.anyio
async def test_wechat_ilink_start_auto_polls_login_status_and_persists():
    state = {}
    client = FakeClient()
    adapter = WechatIlinkAdapter(
        WechatIlinkAdapterConfig(enabled=True, base_url="https://ilink.local"),
        client_factory=lambda: client,
        repository_provider=lambda: FakeAdapterRepo(state),
    )
    adapter.client = client

    await adapter.start()
    for _ in range(20):
        if adapter.config.token:
            break
        await asyncio.sleep(0.01)
    await adapter.stop()

    assert adapter.config.token == "new-token"
    assert state["wechat_ilink"]["token"] == "new-token"


@pytest.mark.anyio
async def test_wechat_ilink_client_sends_text_without_splitting(monkeypatch):
    calls = []

    async def fake_post(self, endpoint, body, *, timeout):
        calls.append({"endpoint": endpoint, "body": body, "timeout": timeout})
        return {"ret": 0}

    monkeypatch.setattr(WechatIlinkClient, "_post", fake_post)
    client = WechatIlinkClient("https://ilink.local", "token")
    text = "第一行\n\n第二行" + ("x" * 4500)

    await client.send_text(to_user_id="u1", context_token="ctx1", text=text)

    assert len(calls) == 1
    message = calls[0]["body"]["msg"]
    assert message["item_list"][0]["text_item"]["text"] == text


@pytest.mark.anyio
async def test_wechat_ilink_client_sends_image_and_file_items(monkeypatch, tmp_path):
    calls = []
    image = tmp_path / "out.png"
    file = tmp_path / "report.txt"
    image.write_bytes(b"image")
    file.write_bytes(b"report")

    async def fake_upload(self, *, path, to_user_id, media_type):
        return {
            "download_param": f"download-{media_type}",
            "aeskey_hex": "00112233445566778899aabbccddeeff",
            "raw_size": len(Path(path).read_bytes()),
            "cipher_size": 32,
        }

    async def fake_post(self, endpoint, body, *, timeout):
        calls.append({"endpoint": endpoint, "body": body, "timeout": timeout})
        return {"ret": 0}

    monkeypatch.setattr(WechatIlinkClient, "_upload_media", fake_upload)
    monkeypatch.setattr(WechatIlinkClient, "_post", fake_post)
    client = WechatIlinkClient("https://ilink.local", "token")

    await client.send_image(to_user_id="u1", context_token="ctx1", path=str(image), text="caption")
    await client.send_file(to_user_id="u1", context_token="ctx1", path=str(file), name="renamed.txt")

    assert calls[0]["body"]["msg"]["item_list"][0]["type"] == 1
    assert calls[1]["body"]["msg"]["item_list"][0]["type"] == 2
    assert calls[1]["body"]["msg"]["item_list"][0]["image_item"]["media"]["encrypt_query_param"] == "download-1"
    assert calls[2]["body"]["msg"]["item_list"][0]["type"] == 4
    assert calls[2]["body"]["msg"]["item_list"][0]["file_item"]["file_name"] == "renamed.txt"

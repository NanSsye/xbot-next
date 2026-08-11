import pytest

from xbot.adapters.qq.adapter import QQAdapter
from xbot.adapters.qq.client import QQBotApiError, QQBotClient
from xbot.core.config import QQAdapterConfig
from xbot.messaging.models import Reply


class _Response:
    def __init__(self, status=200, payload=None, body=b""):
        self.status = status
        self.payload = payload
        self.body = body
        self.reason = "OK"
        self.headers = {"Content-Length": str(len(body))}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, content_type=None):
        if self.payload is None:
            raise ValueError("empty")
        return self.payload

    async def text(self):
        return self.body.decode() if self.body else ""


class _Session:
    closed = False

    def __init__(self):
        self.calls = []
        self.queue = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return _Response(200, {"access_token": "t", "expires_in": 3600})

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.queue.pop(0) if self.queue else _Response(200, {})


class _Client:
    def __init__(self):
        self.calls = []

    async def send_channel(self, **kwargs):
        self.calls.append(("channel", kwargs))
        return {"id": "channel-message"}

    async def send_text(self, **kwargs):
        self.calls.append(("text", kwargs))
        return {"id": "message"}


@pytest.mark.anyio
async def test_client_accepts_empty_200_and_204_without_json():
    session = _Session()
    session.queue.extend([_Response(200, None), _Response(204, None)])
    client = QQBotClient(QQAdapterConfig(app_id="a", client_secret="s"), session=session)
    assert await client.request("DELETE", "/anything") == {}
    assert await client.request("DELETE", "/anything") == {}


@pytest.mark.anyio
async def test_client_stream_uses_documented_input_state_and_content_raw():
    session = _Session()
    client = QQBotClient(QQAdapterConfig(app_id="a", client_secret="s"), session=session)
    await client.stream_message(target_id="u", content="a", input_mode="append", input_state=10, index=2)
    body = session.calls[-1][2]["json"]
    assert body["input_state"] == 10
    assert body["content_raw"] == "a"
    assert "state" not in body and "content" not in body


@pytest.mark.anyio
async def test_local_media_upload_runs_prepare_parts_finish_and_files(monkeypatch, tmp_path):
    path = tmp_path / "note.bin"
    path.write_bytes(b"0123456789")
    client = QQBotClient(QQAdapterConfig(app_id="a", client_secret="s", media_chunk_size=4))
    requests = []

    async def request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        if endpoint.endswith("upload_prepare"):
            return {"upload_id": "up", "parts": [{"part_index": 0, "presigned_url": "https://cdn.invalid/0", "block_size": 4}, {"part_index": 1, "presigned_url": "https://cdn.invalid/1", "block_size": 6}]}
        if endpoint.endswith("/files"):
            return {"file_info": "info"}
        return {}

    uploaded = []
    monkeypatch.setattr(client, "request", request)
    async def put(url, data):
        uploaded.append((url, data))

    monkeypatch.setattr(client, "_put_presigned", put)
    result = await client.upload_file(target_type="group", target_id="g", path=path, media_type="file")
    assert result["file_info"] == "info"
    assert [item[1] for item in uploaded] == [b"0123", b"456789"]
    assert [item[2]["json"]["block_size"] for item in requests if item[0] == "POST" and "part_finish" in item[1]] == ["4", "6"]


@pytest.mark.anyio
async def test_channel_reply_uses_channel_schema_and_active_gate():
    client = _Client()
    adapter = QQAdapter(QQAdapterConfig(), client_factory=lambda: client)
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id="qq:channel:c", content="nope"))
    assert client.calls == []
    await adapter.send(Reply(platform="qq", adapter="qq", conversation_id="qq:channel:c", content="ok", quote_message_id="m"))
    assert client.calls[0][0] == "channel"
    assert client.calls[0][1]["target_type"] == "channel"


@pytest.mark.anyio
async def test_group_message_create_does_not_imply_mention():
    adapter = QQAdapter(QQAdapterConfig())
    message = await adapter.normalize({"t": "GROUP_MESSAGE_CREATE", "d": {"id": "m", "group_openid": "g", "author": {"member_openid": "u"}, "content": "hi"}})
    assert message.raw["mentions_bot"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["send_text", "send_markdown", "send_media", "stream_message", "input_notify"])
async def test_client_rejects_empty_send_target(method):
    client = QQBotClient(QQAdapterConfig())
    if method in {"send_text", "send_markdown"}:
        kwargs = {"target_type": "c2c", "target_id": "", "content": "hello"}
    elif method == "send_media":
        kwargs = {"target_type": "c2c", "target_id": "", "file_info": "info"}
    elif method == "stream_message":
        kwargs = {"target_id": "", "content": "hello"}
    else:
        kwargs = {"target_id": "", "input_second": 5}
    with pytest.raises(QQBotApiError, match="目标不能为空"):
        await getattr(client, method)(**kwargs)


@pytest.mark.anyio
async def test_client_rejects_empty_channel_send_target():
    client = QQBotClient(QQAdapterConfig())
    with pytest.raises(QQBotApiError, match="目标不能为空"):
        await client.send_channel(target_type="channel", target_id="", content="hello")


@pytest.mark.anyio
@pytest.mark.parametrize("content", [None, "", "  ", {}, {"content": "  "}])
async def test_client_rejects_empty_markdown_content(content):
    client = QQBotClient(QQAdapterConfig())
    with pytest.raises(QQBotApiError, match="Markdown 内容不能为空"):
        await client.send_markdown(target_type="c2c", target_id="u", content=content)


@pytest.mark.anyio
@pytest.mark.parametrize("file_info", [None, "", "  ", {}, {"file_info": "x"}, []])
async def test_client_rejects_non_string_or_empty_file_info(file_info):
    client = QQBotClient(QQAdapterConfig())
    with pytest.raises(QQBotApiError, match="file_info 必须是非空字符串"):
        await client.send_media(target_type="c2c", target_id="u", file_info=file_info)

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from xbot.messaging.models import Message


def load_plugin_module():
    path = Path(__file__).resolve().parents[3] / "plugins" / "xhs_content" / "main.py"
    spec = importlib.util.spec_from_file_location("xbot_xhs_content_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeContent:
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def iter_chunked(self, size: int):
        for index in range(0, len(self.body), size):
            yield self.body[index:index + size]


class FakeResponse:
    def __init__(self, status: int, *, payload: Any = None, headers: dict[str, str] | None = None, body: bytes = b"") -> None:
        self.status = status
        self.payload = payload
        self.headers = headers or {}
        self.content = FakeContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, detail: FakeResponse, downloads: list[FakeResponse] | None = None) -> None:
        self.detail = detail
        self.downloads = list(downloads or [])
        self.closed = False
        self.posts: list[dict[str, Any]] = []
        self.gets: list[str] = []

    def post(self, url: str, **kwargs: Any):
        self.posts.append({"url": url, **kwargs})
        return self.detail

    def get(self, url: str, **kwargs: Any):
        self.gets.append(url)
        return self.downloads.pop(0)

    async def close(self) -> None:
        self.closed = True


def detail_data(*, kind: str = "图文", urls: list[str] | None = None) -> dict[str, Any]:
    return {
        "message": "获取小红书作品数据成功",
        "data": {
            "作品ID": "68a1bcde123456",
            "作品标题": "周末散步",
            "作品描述": "今天去了公园，天气很好。",
            "作品类型": kind,
            "作品标签": ["生活", "散步"],
            "发布时间": "2026-08-15",
            "作者昵称": "小红薯",
            "点赞数量": "100",
            "收藏数量": 20,
            "评论数量": "10",
            "分享数量": None,
            "下载地址": urls or [],
        },
    }


def incoming(platform: str, adapter: str, url: str = "https://www.xiaohongshu.com/discovery/item/68a1bcde123456") -> Message:
    return Message(
        id="message-1",
        platform=platform,
        adapter=adapter,
        conversation_id=f"{platform}:group:test",
        sender_id="user-1",
        content=f"看看这个 {url}",
        raw={"scope": "group"},
    )


def configured_plugin(module, tmp_path: Path, session: FakeSession):
    plugin = module.XhsContentPlugin()
    plugin._session = session
    plugin._base_url = "http://host.docker.internal:5556"
    plugin._api_token = "configured-secret"
    plugin._data_dir = tmp_path
    plugin._assert_public_dns = lambda value: _async_none()
    replies = []

    async def send_reply(reply):
        replies.append(reply)
        return {"ok": True}

    plugin._send_reply = send_reply
    return plugin, replies


async def _async_none():
    return None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("platform", "adapter"),
    [("wechat", "wechat869"), ("qq", "qq")],
)
async def test_image_note_is_handled_without_agent_and_sends_text_and_images(tmp_path, platform, adapter):
    module = load_plugin_module()
    urls = ["https://sns-img-qc.xhscdn.com/a.jpg", "https://sns-img-qc.xhscdn.com/b.png"]
    session = FakeSession(
        FakeResponse(200, payload=detail_data(urls=urls)),
        [
            FakeResponse(200, headers={"Content-Type": "image/jpeg"}, body=b"jpeg-data"),
            FakeResponse(200, headers={"Content-Type": "image/png"}, body=b"png-data"),
        ],
    )
    plugin, replies = configured_plugin(module, tmp_path, session)

    handled = await plugin.on_message(incoming(platform, adapter), None)

    assert handled is True
    assert [reply.type for reply in replies] == ["text", "image", "image"]
    assert "周末散步" in replies[0].content
    assert "今天去了公园" in replies[0].content
    assert "#生活" in replies[0].content
    assert all(Path(reply.content).is_file() for reply in replies[1:])
    assert session.posts[0]["json"] == {
        "url": "https://www.xiaohongshu.com/discovery/item/68a1bcde123456",
        "download": False,
        "skip": False,
    }
    assert set(session.posts[0]["json"]) == {"url", "download", "skip"}


@pytest.mark.anyio
async def test_telegram_video_note_sends_description_and_video(tmp_path):
    module = load_plugin_module()
    url = "https://sns-video-qc.xhscdn.com/demo.mp4"
    session = FakeSession(
        FakeResponse(200, payload=detail_data(kind="视频", urls=[url])),
        [FakeResponse(200, headers={"Content-Type": "video/mp4"}, body=b"video-data")],
    )
    plugin, replies = configured_plugin(module, tmp_path, session)

    assert await plugin.on_message(incoming("telegram", "telegram"), None) is True

    assert [reply.type for reply in replies] == ["video"]
    assert replies[0].quote_message_id == "message-1"
    assert replies[0].metadata["parse_mode"] == "Markdown"
    assert "周末散步" in replies[0].metadata["caption"]
    assert "今天去了公园" in replies[0].metadata["caption"]
    assert Path(replies[0].content).suffix == ".mp4"


@pytest.mark.anyio
async def test_telegram_image_note_combines_first_image_and_markdown_caption(tmp_path):
    module = load_plugin_module()
    urls = ["https://sns-img-qc.xhscdn.com/a.jpg", "https://sns-img-qc.xhscdn.com/b.jpg"]
    session = FakeSession(
        FakeResponse(200, payload=detail_data(urls=urls)),
        [
            FakeResponse(200, headers={"Content-Type": "image/jpeg"}, body=b"first"),
            FakeResponse(200, headers={"Content-Type": "image/jpeg"}, body=b"second"),
        ],
    )
    plugin, replies = configured_plugin(module, tmp_path, session)

    assert await plugin.on_message(incoming("telegram", "telegram"), None) is True

    assert [reply.type for reply in replies] == ["image"]
    assert replies[0].metadata["parse_mode"] == "Markdown"
    assert replies[0].metadata["caption"].startswith("*📕 周末散步*")
    assert "今天去了公园" in replies[0].metadata["caption"]
    assert len(replies[0].metadata["paths"]) == 2
    assert replies[0].quote_message_id == "message-1"


def test_telegram_caption_uses_available_space_before_splitting_text():
    module = load_plugin_module()
    plugin = module.XhsContentPlugin()
    payload = detail_data()["data"]
    payload["作品描述"] = "文" * 700

    caption, continuation = plugin._telegram_media_text(payload)

    assert len(caption) <= 1000
    assert continuation == ""


@pytest.mark.anyio
async def test_http_200_with_null_data_is_business_failure_and_stops_agent(tmp_path):
    module = load_plugin_module()
    session = FakeSession(FakeResponse(200, payload={"message": "失败", "data": None}))
    plugin, replies = configured_plugin(module, tmp_path, session)

    handled = await plugin.on_message(incoming("qq", "qq"), None)

    assert handled is True
    assert len(replies) == 1
    assert "暂时无法解析" in replies[0].content


@pytest.mark.anyio
async def test_short_link_redirect_to_untrusted_host_is_rejected_before_parse(tmp_path):
    module = load_plugin_module()
    session = FakeSession(
        FakeResponse(200, payload=detail_data()),
        [FakeResponse(302, headers={"Location": "http://127.0.0.1/private"})],
    )
    plugin, replies = configured_plugin(module, tmp_path, session)

    handled = await plugin.on_message(incoming("wechat", "wechat869", "https://xhslink.cn/abc123"), None)

    assert handled is True
    assert session.posts == []
    assert len(replies) == 1
    assert "链接无效" in replies[0].content


@pytest.mark.anyio
async def test_401_is_configuration_error_and_token_is_not_exposed(tmp_path):
    module = load_plugin_module()
    session = FakeSession(FakeResponse(401, payload={"detail": "unauthorized"}))
    plugin, replies = configured_plugin(module, tmp_path, session)

    assert await plugin.on_message(incoming("qq", "qq"), None) is True

    assert len(replies) == 1
    assert "配置" in replies[0].content
    assert "configured-secret" not in replies[0].content


def test_url_validation_rejects_credentials_and_non_xhs_hosts():
    module = load_plugin_module()
    with pytest.raises(module.XhsParseError):
        module.XhsContentPlugin._validate_url("https://user@xiaohongshu.com/item/123456", module.ALLOWED_LINK_HOSTS)
    with pytest.raises(module.XhsParseError):
        module.XhsContentPlugin._validate_url("https://example.com/item/123456", module.ALLOWED_LINK_HOSTS)


def test_qq_webp_image_is_converted_to_jpeg(tmp_path):
    module = load_plugin_module()
    from PIL import Image

    source = tmp_path / "image.webp"
    Image.new("RGB", (8, 8), color=(200, 20, 20)).save(source, format="WEBP")

    target = module.XhsContentPlugin._qq_compatible_image(source)

    assert target.suffix == ".jpg"
    assert target.is_file()
    with Image.open(target) as converted:
        assert converted.format == "JPEG"

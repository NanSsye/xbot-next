from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbot.messaging.models import Message
from xbot.plugins.loader import PluginLoader


def _plugin():
    loader = PluginLoader()
    plugin_dir = Path("plugins/wxsph_video")
    return loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))


async def finish_tasks(plugin) -> None:
    await asyncio.gather(*list(plugin._tasks))


@pytest.mark.asyncio
async def test_qq_link_without_mention_sends_native_video_reply():
    plugin = _plugin()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    async def parse(_url):
        return "测试视频", None, "https://media.example.test/video", None

    plugin._send_reply_fn = send_reply
    plugin._parse = parse
    message = Message(
        id="qq-video-message",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="https://v.douyin.com/abc123/",
        raw={"scope": "group", "mentions_bot": False},
    )

    handled = await plugin.on_message(message, SimpleNamespace())
    await finish_tasks(plugin)

    assert handled is True
    assert len(replies) == 1
    assert replies[0].type == "video"
    assert replies[0].metadata == {
        "url": "https://media.example.test/video",
        "file_name": "video.mp4",
    }
    assert replies[0].quote_message_id == message.id


@pytest.mark.asyncio
async def test_qq_music_file_uses_generic_file_reply():
    plugin = _plugin()
    replies = []

    async def send_reply(reply):
        replies.append(reply)

    plugin._send_reply_fn = send_reply
    message = Message(
        id="qq-music-message",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="提取音乐 https://v.douyin.com/abc123/",
        raw={"scope": "group", "mentions_bot": False},
    )

    await plugin._send_music_file(message, "/tmp/wxsph_music/example.mp3", "测试音乐")

    assert len(replies) == 1
    assert replies[0].type == "file"
    assert replies[0].metadata["path"] == "/tmp/wxsph_music/example.mp3"
    assert replies[0].quote_message_id == message.id


@pytest.mark.asyncio
async def test_qq_quoted_video_converts_to_mp3_without_mention():
    plugin = _plugin()
    replies = []
    quoted = Message(
        id="quoted-video",
        platform="qq",
        adapter="qq",
        type="video",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="[视频]",
        raw={
            "attachments": [
                {
                    "kind": "video",
                    "filename": "holiday.mp4",
                    "local_path": "/tmp/inbound/holiday.mp4",
                }
            ]
        },
    )

    class Conversations:
        async def get_messages(self, conversation_id, limit=20):
            assert conversation_id == "qq:group:test"
            assert limit == 100
            return [quoted]

    async def send_reply(reply):
        replies.append(reply)

    async def extract(path):
        assert path == "/tmp/inbound/holiday.mp4"
        return "/tmp/wxsph_music/holiday.mp3"

    plugin._send_reply_fn = send_reply
    plugin._conversations = Conversations()
    plugin._extract_audio_from_local_video = extract
    message = Message(
        id="convert-command",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="转mp3",
        raw={
            "scope": "group",
            "mentions_bot": False,
            "message_reference": {"message_id": "quoted-video"},
        },
    )

    handled = await plugin.on_message(message, SimpleNamespace())
    await finish_tasks(plugin)

    assert handled is True
    assert len(replies) == 1
    assert replies[0].type == "file"
    assert replies[0].content == "holiday.mp3"
    assert replies[0].metadata["path"] == "/tmp/wxsph_music/holiday.mp3"


@pytest.mark.asyncio
async def test_wechat_quoted_video_attachment_converts_to_mp3_without_mention():
    plugin = _plugin()
    sent = []

    async def extract(path):
        assert path == "/tmp/inbound/wechat-video.mp4"
        return "/tmp/wxsph_music/wechat-video.mp3"

    async def send_music(message, path, title):
        sent.append((message.adapter, path, title))

    plugin._extract_audio_from_local_video = extract
    plugin._send_music_file = send_music
    message = Message(
        id="wechat-convert-command",
        platform="wechat",
        adapter="wechat869",
        conversation_id="wechat:group:test",
        sender_id="user-1",
        content="帮我转成 MP3 文件",
        raw={
            "scope": "group",
            "mentions_bot": False,
            "quote": {
                "attachments": [
                    {
                        "kind": "video",
                        "filename": "wechat-video.mp4",
                        "local_path": "/tmp/inbound/wechat-video.mp4",
                    }
                ]
            },
        },
    )

    handled = await plugin.on_message(message, SimpleNamespace())
    await finish_tasks(plugin)

    assert handled is True
    assert sent == [("wechat869", "/tmp/wxsph_music/wechat-video.mp3", "wechat-video.mp3")]


@pytest.mark.asyncio
async def test_video_processing_releases_message_dispatch_immediately():
    plugin = _plugin()
    started = asyncio.Event()
    release = asyncio.Event()

    async def parse(_url):
        started.set()
        await release.wait()
        return "测试视频", None, "https://media.example.test/video", None

    plugin._parse = parse
    message = Message(
        id="slow-video-message",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="https://v.douyin.com/slow123/",
        raw={"scope": "group", "mentions_bot": False},
    )

    assert await plugin.on_message(message, SimpleNamespace()) is True
    await asyncio.wait_for(started.wait(), timeout=0.2)
    assert plugin._tasks
    release.set()
    await finish_tasks(plugin)

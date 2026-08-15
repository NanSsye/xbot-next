from __future__ import annotations

from typing import Any

import pytest

from xbot.adapters.registry import AdapterRegistry
from xbot.adapters.telegram.adapter import TelegramAdapter
from xbot.adapters.telegram.client import TelegramApiError
from xbot.core.config import AdapterConfig, TelegramAdapterConfig
from xbot.messaging.models import Reply


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.answered: list[str] = []
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append({"kind": "text", **kwargs})
        return {"message_id": len(self.sent)}

    async def send_media(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append({"transport": "media", **kwargs})
        return {"message_id": len(self.sent)}

    async def send_media_group(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.sent.append({"transport": "media_group", **kwargs})
        return [{"message_id": index + 1} for index, _ in enumerate(kwargs["sources"])]

    async def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> bool:
        self.answered.append(callback_query_id)
        return True


class FakeQueue:
    def __init__(self) -> None:
        self.items = []

    async def publish(self, envelope) -> None:
        self.items.append(envelope)


class MarkdownFallbackClient(FakeTelegramClient):
    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append({"kind": "text", **kwargs})
        if kwargs.get("parse_mode"):
            raise TelegramApiError("Bad Request: can't parse entities")
        return {"message_id": len(self.sent)}


def telegram_update() -> dict[str, Any]:
    return {
        "update_id": 100,
        "message": {
            "message_id": 7,
            "date": 1_700_000_000,
            "chat": {"id": -123, "type": "supergroup", "title": "测试群"},
            "from": {"id": 42, "first_name": "Alice", "username": "alice"},
            "text": "@smallx_bot 你好",
            "reply_to_message": {
                "message_id": 6,
                "chat": {"id": -123, "type": "supergroup"},
                "from": {"id": 88, "first_name": "Bob"},
                "caption": "引用的视频",
                "video": {
                    "file_id": "video-file",
                    "file_unique_id": "unique-video",
                    "file_name": "demo.mp4",
                    "file_size": 1234,
                    "mime_type": "video/mp4",
                },
            },
        },
    }


@pytest.mark.asyncio
async def test_normalize_group_mention_quote_and_media() -> None:
    adapter = TelegramAdapter(TelegramAdapterConfig(auto_download_media=False))
    adapter.bot_id = "999"
    adapter.bot_username = "smallx_bot"

    message = await adapter.normalize(telegram_update())

    assert message.platform == "telegram"
    assert message.adapter == "telegram"
    assert message.conversation_id == "telegram:group:-123"
    assert message.sender_id == "42"
    assert message.raw["mentions_bot"] is True
    assert message.raw["user_id"] == "42"
    assert message.raw["quote"]["message_id"] == "6"
    assert message.raw["quote"]["attachments"][0]["type"] == "video"
    assert message.raw["quote"]["attachments"][0]["file_id"] == "video-file"
    assert message.timestamp.isoformat() == "2023-11-14T22:13:20"
    assert message.timestamp.tzinfo is None


@pytest.mark.asyncio
async def test_send_text_keyboard_quote_and_media() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(
        TelegramAdapterConfig(max_reply_chars=5),
        client_factory=lambda: client,
    )

    result = await adapter.send(Reply(
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:group:-123",
        type="keyboard",
        content="123456",
        quote_message_id="-123:7",
        metadata={"inline_keyboard": [[{"text": "确认", "callback_data": "confirm"}]]},
    ))
    await adapter.send(Reply(
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:private:42",
        type="video",
        content="https://cdn.example/video.mp4",
    ))

    assert result == {"message_id": "2", "message_ids": ["1", "2"]}
    assert client.sent[0]["reply_to_message_id"] == 7
    assert client.sent[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "confirm"
    assert client.sent[2]["chat_id"] == "42"
    assert client.sent[2]["transport"] == "media"
    assert client.sent[2]["kind"] == "video"


@pytest.mark.asyncio
async def test_markdown_reply_falls_back_to_plain_text_on_parse_error() -> None:
    client = MarkdownFallbackClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)

    result = await adapter.send(Reply(
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:private:42",
        type="markdown",
        content="**broken markdown",
    ))

    assert result == {"message_id": "2", "message_ids": ["2"]}
    assert [item["parse_mode"] for item in client.sent] == ["Markdown", None]


@pytest.mark.asyncio
async def test_send_image_group_uses_telegram_album() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)

    result = await adapter.send(Reply(
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:private:42",
        type="image",
        content="/tmp/one.jpg",
        quote_message_id="42:7",
        metadata={
            "paths": ["/tmp/one.jpg", "/tmp/two.jpg"],
            "caption": "*标题*",
            "parse_mode": "Markdown",
        },
    ))

    assert result == {"message_id": "2", "message_ids": ["1", "2"]}
    assert client.sent[0]["transport"] == "media_group"
    assert client.sent[0]["sources"] == ["/tmp/one.jpg", "/tmp/two.jpg"]
    assert client.sent[0]["reply_to_message_id"] == 7


@pytest.mark.asyncio
async def test_callback_is_acked_and_published() -> None:
    client = FakeTelegramClient()
    queue = FakeQueue()
    adapter = TelegramAdapter(
        TelegramAdapterConfig(auto_download_media=False),
        queue=queue,
        client_factory=lambda: client,
    )
    raw = {
        "update_id": 101,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 42, "first_name": "Alice"},
            "data": "menu:help",
            "message": {
                "message_id": 8,
                "date": 1_700_000_001,
                "chat": {"id": -123, "type": "group", "title": "测试群"},
            },
        },
    }

    await adapter._handle_update(raw)

    assert client.answered == ["cb-1"]
    assert len(queue.items) == 1
    assert queue.items[0].message.content == "menu:help"
    assert queue.items[0].message.raw["mentions_bot"] is True


def test_registry_lists_telegram() -> None:
    registry = AdapterRegistry(AdapterConfig(telegram=TelegramAdapterConfig(enabled=True, bot_token="token")))
    item = next(item for item in registry.list_adapters() if item["name"] == "telegram")
    assert item["platform"] == "telegram"
    assert item["configured_enabled"] is True

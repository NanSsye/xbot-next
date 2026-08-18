from __future__ import annotations

from typing import Any

import pytest

from xbot.adapters.registry import AdapterRegistry
from xbot.adapters.telegram.adapter import TelegramAdapter
from xbot.adapters.telegram.client import TelegramApiError, TelegramBotClient
from xbot.adapters.telegram.formatting import markdown_to_telegram_html, split_markdown
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

    async def edit_message_text(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append({"kind": "edit", **kwargs})
        return {"message_id": kwargs["message_id"]}

    async def send_media(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append({"transport": "media", **kwargs})
        return {"message_id": len(self.sent)}

    async def send_media_group(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.sent.append({"transport": "media_group", **kwargs})
        return [{"message_id": index + 1} for index, _ in enumerate(kwargs["sources"])]

    async def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> bool:
        self.answered.append(callback_query_id)
        return True

    async def send_chat_action(self, **kwargs: Any) -> bool:
        self.sent.append({"kind": "chat_action", **kwargs})
        return True

    async def set_my_commands(self, **kwargs: Any) -> bool:
        self.sent.append({"kind": "commands", **kwargs})
        return True

    async def set_chat_menu_button(self, **kwargs: Any) -> bool:
        self.sent.append({"kind": "menu_button", **kwargs})
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
            "media_group_id": "album-1",
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
    assert message.raw["telegram_media_group_id"] == "album-1"
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
async def test_send_chat_action_uses_conversation_target() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)

    result = await adapter.send_chat_action("telegram:private:42")

    assert result is True
    assert client.sent == [{"kind": "chat_action", "chat_id": "42", "action": "typing"}]


@pytest.mark.asyncio
async def test_configure_command_menu_is_scoped_to_each_admin_chat() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)
    commands = [{"command": "codex", "description": "选择 Codex 任务"}]

    await adapter.configure_command_menu(["42"], commands)

    assert client.sent == [
        {
            "kind": "commands",
            "commands": commands,
            "scope": {"type": "chat", "chat_id": "42"},
        },
        {"kind": "menu_button", "chat_id": "42"},
    ]


@pytest.mark.asyncio
async def test_configure_group_command_menu_uses_all_group_chats_scope() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)
    commands = [{"command": "xbot", "description": "和小X对话"}]

    await adapter.configure_group_command_menu(commands)

    assert client.sent == [{
        "kind": "commands",
        "commands": commands,
        "scope": {"type": "all_group_chats"},
    }]


@pytest.mark.asyncio
async def test_start_configures_xbot_group_menu() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(
        TelegramAdapterConfig(enabled=True, bot_token="token"),
        client_factory=lambda: client,
    )

    await adapter.start()

    assert client.sent[0]["kind"] == "commands"
    assert client.sent[0]["scope"] == {"type": "all_group_chats"}
    assert [item["command"] for item in client.sent[0]["commands"]] == [
        "xbot", "new", "status", "help",
    ]


@pytest.mark.asyncio
async def test_normalize_group_xbot_command_as_explicit_bot_mention() -> None:
    adapter = TelegramAdapter(TelegramAdapterConfig(auto_download_media=False))
    adapter.bot_username = "smallx_bot"
    raw = telegram_update()
    raw["message"]["text"] = "/xbot 帮我看看"

    message = await adapter.normalize(raw)

    assert message.raw["mentions_bot"] is True


@pytest.mark.asyncio
async def test_group_command_addressed_to_other_bot_is_not_a_mention() -> None:
    adapter = TelegramAdapter(TelegramAdapterConfig(auto_download_media=False))
    adapter.bot_username = "smallx_bot"
    raw = telegram_update()
    raw["message"]["text"] = "/xbot@other_bot 帮我看看"

    message = await adapter.normalize(raw)

    assert message.raw["mentions_bot"] is False


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
    assert [item["parse_mode"] for item in client.sent] == ["HTML", None]
    assert client.sent[-1]["text"] == "**broken markdown"


@pytest.mark.asyncio
async def test_edit_keyboard_message_in_place_with_markdown() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)

    result = await adapter.send(Reply(
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:private:42",
        type="keyboard",
        content="*第二页*",
        metadata={
            "edit_message_id": "42:18",
            "parse_mode": "Markdown",
            "inline_keyboard": [[{"text": "下一页", "callback_data": "page:2"}]],
        },
    ))

    assert result == {"message_id": "18", "message_ids": ["18"]}
    assert client.sent == [{
        "kind": "edit",
        "chat_id": "42",
        "message_id": 18,
        "text": "<i>第二页</i>",
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[{"text": "下一页", "callback_data": "page:2"}]]},
    }]


@pytest.mark.asyncio
async def test_edit_message_can_remove_inline_keyboard() -> None:
    client = FakeTelegramClient()
    adapter = TelegramAdapter(TelegramAdapterConfig(), client_factory=lambda: client)

    await adapter.send(Reply(
        platform="telegram",
        adapter="telegram",
        conversation_id="telegram:private:42",
        type="markdown",
        content="完成",
        metadata={"edit_message_id": "18", "inline_keyboard": []},
    ))

    assert client.sent[0]["reply_markup"] == {"inline_keyboard": []}


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
    assert client.sent[0]["caption"] == "<i>标题</i>"
    assert client.sent[0]["parse_mode"] == "HTML"


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
    assert queue.items[0].dedupe_key == "telegram:telegram:callback:cb-1"


def test_registry_lists_telegram() -> None:
    registry = AdapterRegistry(AdapterConfig(telegram=TelegramAdapterConfig(enabled=True, bot_token="token")))
    item = next(item for item in registry.list_adapters() if item["name"] == "telegram")
    assert item["platform"] == "telegram"
    assert item["configured_enabled"] is True


def test_markdown_renderer_escapes_html_and_formats_common_blocks() -> None:
    rendered = markdown_to_telegram_html(
        "# 标题\n\n- **重点** <script>\n\n"
        "| 名称 | 状态 |\n| --- | --- |\n| TG | `正常` |\n\n"
        "[官网](https://example.com?a=1&b=2)"
    )

    assert "<b>标题</b>" in rendered
    assert "• <b>重点</b> &lt;script&gt;" in rendered
    assert "<b>名称</b>：TG" in rendered
    assert "<code>正常</code>" in rendered
    assert '<a href="https://example.com?a=1&amp;b=2">官网</a>' in rendered
    assert "<script>" not in rendered


def test_markdown_splitter_closes_each_long_code_fence() -> None:
    chunks = split_markdown("```python\n" + ("print('x')\n" * 20) + "```", 80)

    assert len(chunks) > 1
    assert all(chunk.startswith("```python\n") and chunk.endswith("\n```") for chunk in chunks)
    assert all(len(chunk) <= 80 for chunk in chunks)


class SequenceResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status = int(payload.get("error_code") or 200)
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class SequenceSession:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0
        self.closed = False

    def post(self, url: str, **kwargs: Any):
        payload = self.payloads[self.calls]
        self.calls += 1
        return SequenceResponse(payload)


@pytest.mark.asyncio
async def test_telegram_client_retries_json_request_once_after_429(monkeypatch) -> None:
    session = SequenceSession([
        {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests",
            "parameters": {"retry_after": 1},
        },
        {"ok": True, "result": {"message_id": 9}},
    ])
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("xbot.adapters.telegram.client.asyncio.sleep", fake_sleep)
    client = TelegramBotClient(TelegramAdapterConfig(bot_token="token"), session=session)

    result = await client.request("sendMessage", json={"chat_id": "42", "text": "hi"})

    assert result == {"message_id": 9}
    assert session.calls == 2
    assert sleeps == [1.0]

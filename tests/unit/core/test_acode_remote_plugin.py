from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xbot.messaging.models import Message
from xbot.plugins.context import PluginContext


def load_plugin_module():
    path = Path(__file__).resolve().parents[3] / "plugins" / "acode_remote" / "main.py"
    spec = importlib.util.spec_from_file_location("xbot_acode_remote_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def incoming(
    content: str,
    *,
    sender_id: str = "42",
    message_type: str = "text",
    attachments: list[dict[str, Any]] | None = None,
    media_group_id: str = "",
) -> Message:
    return Message(
        id="42:7",
        platform="telegram",
        adapter="telegram",
        type=message_type,
        conversation_id="telegram:private:42",
        sender_id=sender_id,
        content=content,
        raw={
            "scope": "private",
            "telegram_message_id": 7,
            "attachments": attachments or [],
            "telegram_media_group_id": media_group_id,
        },
    )


def plugin_context(tmp_path: Path, replies: list[Any], *, adapters: Any = None) -> PluginContext:
    async def send_reply(reply):
        replies.append(reply)
        return {"message_id": str(len(replies))}

    settings = SimpleNamespace(
        adapters=SimpleNamespace(
            telegram=SimpleNamespace(admin_user_ids=["42"]),
        ),
    )
    return PluginContext(
        name="acode_remote",
        data_dir=tmp_path,
        config={
            "enabled": True,
            "base_url": "http://acode.test:8787",
            "admin_token": "a" * 32,
            "allowed_user_ids": [],
        },
        settings=settings,
        send_reply=send_reply,
        adapters=adapters,
    )


def add_pending_run(
    plugin,
    thread_id: str,
    *,
    turn_id: str = "turn-new",
    conversation_id: str = "telegram:private:42",
    message_id: str = "",
) -> str:
    run_key = f"{thread_id}:{turn_id}"
    plugin._runs[run_key] = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "title": "测试任务",
        "started_at": 0,
        "targets": {conversation_id: message_id},
        "delivered_to": [],
    }
    return run_key


@pytest.mark.asyncio
async def test_inactive_admin_message_falls_through_to_existing_agent(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))

    handled = await plugin.on_message(incoming("你好"), plugin._ctx)

    assert handled is False
    assert replies == []
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_menu_lists_agent_and_acode_threads(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)

    async def list_threads(*, limit: int):
        assert limit == 30
        return [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "title": "实现 TG Codex 远程插件",
                "status": "running",
                "updatedAtMs": 100,
                "cwd": r"\\?\D:\公司项目\xbot-next",
            }
        ]

    plugin._list_threads = list_threads

    assert await plugin.on_message(incoming("/codex"), ctx) is True
    await asyncio.gather(*list(plugin._tasks))

    assert len(replies) == 1
    assert replies[0].type == "keyboard"
    keyboard = replies[0].metadata["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == "acode:agent"
    assert keyboard[1][0]["callback_data"] == "acode:thread:11111111-1111-1111-1111-111111111111"
    assert keyboard[1][1]["callback_data"] == "acode:favorite:11111111-1111-1111-1111-111111111111"
    assert "项目：*📁 xbot-next*" in replies[0].content
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_search_filters_threads_across_projects(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)

    async def list_threads(*, limit: int):
        assert limit == 100
        return [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "title": "完善 TG 远程功能",
                "cwd": r"D:\公司项目\xbot-next",
                "status": "completed",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "title": "会员接口",
                "cwd": r"D:\个人项目\wechat-companion-ai",
                "status": "completed",
            },
        ]

    plugin._list_threads = list_threads

    assert await plugin.on_message(incoming("/find xbot"), ctx) is True
    await asyncio.gather(*list(plugin._tasks))

    assert "完善 TG 远程功能" in replies[-1].content
    assert "会员接口" not in replies[-1].content
    assert replies[-1].metadata["inline_keyboard"][0][0]["callback_data"].startswith("acode:thread:")
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_search_pagination_edits_the_same_card(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)

    async def list_threads(*, limit: int):
        return [{
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "title": f"xbot 任务 {index}",
            "cwd": r"D:\公司项目\xbot-next",
            "status": "completed",
        } for index in range(1, 7)]

    plugin._list_threads = list_threads
    await plugin._send_search_results(incoming("/find xbot"), "xbot", token="searchtoken")
    callback = incoming("acode:search:searchtoken:1", message_type="event")
    assert await plugin.on_message(callback, ctx) is True
    await asyncio.gather(*list(plugin._tasks))

    assert "xbot 任务 6" in replies[-1].content
    assert replies[-1].metadata["edit_message_id"] == "7"
    assert "第 2/2 页" in replies[-1].content
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_task_management_and_approval_callbacks_use_acode_api(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)
    thread_id = "11111111-1111-1111-1111-111111111111"
    await plugin._set_selection("42", thread_id)
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        if path == "/api/workspaces":
            return {"data": [{"name": "xbot-next", "cwd": r"D:\公司项目\xbot-next"}]}
        if path == "/api/threads":
            return {"threadId": thread_id, "turn": {"id": "turn-create"}}
        return {"ok": True}

    async def watch(_run_key: str):
        return None

    plugin._request = request
    plugin._watch_run = watch
    await plugin._rename_thread(incoming("/rename TG 优化"), "/rename TG 优化")
    await plugin._resolve_approval(
        incoming("acode:approval:allow:22222222-2222-2222-2222-222222222222", message_type="event"),
        "22222222-2222-2222-2222-222222222222",
        "allow",
    )

    assert ("PATCH", f"/api/threads/{thread_id}", {"title": "TG 优化"}) in calls
    assert (
        "POST",
        "/api/approvals/22222222-2222-2222-2222-222222222222/resolve",
        {"decision": "allow"},
    ) in calls
    assert replies[-1].metadata["edit_message_id"] == "7"
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_approval_event_is_allowed_without_sending_telegram_card(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    requests: list[tuple[str, str, Any]] = []

    async def request(method: str, path: str, *, payload=None):
        requests.append((method, path, payload))
        return {"applied": True}

    plugin._request = request
    await plugin._auto_approve({"approval": {"id": "approval-1"}})
    await plugin._auto_approve({"approval": {"id": "approval-1"}})

    assert requests == [(
        "POST",
        "/api/approvals/approval-1/resolve",
        {"decision": "allow"},
    )]
    assert replies == []
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_voice_is_transcribed_locally_before_turn_start(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "33333333-3333-3333-3333-333333333333"
    voice_path = tmp_path / "voice.ogg"
    voice_path.write_bytes(b"voice")
    requests: list[dict[str, Any]] = []

    async def transcribe_file(path: Path):
        assert path == voice_path
        return "请检查菜单功能"

    async def thread_status(_thread_id: str):
        return "completed"

    async def request(method: str, path: str, *, payload=None):
        requests.append({"method": method, "path": path, "payload": payload})
        return {"turn": {"id": "turn-voice"}}

    async def watch(_run_key: str):
        return None

    plugin._transcribe_file = transcribe_file
    plugin._thread_status = thread_status
    plugin._request = request
    plugin._watch_run = watch
    await plugin._process_prompt(
        incoming("[语音]", message_type="voice"),
        thread_id,
        "请查看并处理我发送的附件。",
        attachments=[{
            "source": "telegram",
            "type": "voice",
            "local_path": str(voice_path),
        }],
    )
    await asyncio.gather(*list(plugin._tasks))

    assert "请检查菜单功能" in requests[0]["payload"]["text"]
    assert "attachments" not in requests[0]["payload"]
    await plugin.on_unload()


def test_media_cleanup_is_scoped_and_supports_dry_run(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    media_root = tmp_path / "telegram-media"
    old_file = media_root / "1" / "old.jpg"
    fresh_file = media_root / "2" / "fresh.jpg"
    outside_file = tmp_path / "outside.jpg"
    for path in (old_file, fresh_file, outside_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    old_time = 1_600_000_000
    os.utime(old_file, (old_time, old_time))
    os.utime(outside_file, (old_time, old_time))

    class Registry:
        def get(self, name: str):
            if name != "telegram":
                return None
            return SimpleNamespace(config=SimpleNamespace(media_dir=str(media_root)))

    plugin._ctx = SimpleNamespace(adapters=Registry())
    plugin._retention_days = 30

    preview = plugin._cleanup_telegram_media(True)
    result = plugin._cleanup_telegram_media(False)

    assert preview == {"eligible_files": 1, "removed_files": 0}
    assert result == {"eligible_files": 1, "removed_files": 1}
    assert not old_file.exists()
    assert fresh_file.exists()
    assert outside_file.exists()


@pytest.mark.asyncio
async def test_favorite_toggle_persists_per_user(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "11111111-1111-1111-1111-111111111111"
    menu_calls: list[str] = []

    async def send_menu(message, *, page=None):
        menu_calls.append(message.sender_id)

    plugin._send_menu = send_menu
    message = incoming(f"acode:favorite:{thread_id}", message_type="event")

    await plugin._toggle_favorite(message, thread_id)
    saved = json.loads((tmp_path / "favorites.json").read_text(encoding="utf-8"))

    assert saved == {"42": [thread_id]}
    assert menu_calls == ["42"]
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_album_messages_merge_into_one_codex_turn(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)
    thread_id = "33333333-3333-3333-3333-333333333333"
    await plugin._set_selection("42", thread_id)
    plugin._album_delay = 0.01
    prompts: list[dict[str, Any]] = []

    async def process_prompt(message, selected_thread_id: str, content: str, *, attachments=None):
        prompts.append({
            "thread_id": selected_thread_id,
            "content": content,
            "attachments": attachments,
        })

    plugin._process_prompt = process_prompt
    first = incoming(
        "分析这一组图片",
        message_type="image",
        media_group_id="media-1",
        attachments=[{"source": "telegram", "type": "image", "file_id": "photo-1"}],
    )
    second = incoming(
        "[图片]",
        message_type="image",
        media_group_id="media-1",
        attachments=[{"source": "telegram", "type": "image", "file_id": "photo-2"}],
    )

    assert await plugin.on_message(first, ctx) is True
    assert await plugin.on_message(second, ctx) is True
    await asyncio.sleep(0.05)

    assert len(prompts) == 1
    assert prompts[0]["thread_id"] == thread_id
    assert prompts[0]["content"] == "分析这一组图片"
    assert [item["file_id"] for item in prompts[0]["attachments"]] == ["photo-1", "photo-2"]
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_menu_groups_projects_and_callback_pages_edit_same_message(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)

    async def list_threads(*, limit: int):
        assert limit == 30
        return [
            {
                "id": f"00000000-0000-0000-0000-00000000000{index}",
                "title": f"xbot 任务 {index}",
                "status": "notLoaded",
                "updatedAtMs": 100 - index,
                "cwd": r"\\?\D:\公司项目\xbot-next",
            }
            for index in range(6)
        ] + [{
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "微伴任务",
            "status": "running",
            "updatedAtMs": 1,
            "cwd": r"\\?\D:\个人项目\wechat-companion-ai",
        }]

    plugin._list_threads = list_threads
    callback = incoming("acode:page:2", message_type="event")

    assert await plugin.on_message(callback, ctx) is True
    await asyncio.gather(*list(plugin._tasks))

    reply = replies[-1]
    assert "wechat-companion-ai" in reply.content
    assert "微伴任务" in reply.content
    assert reply.metadata["edit_message_id"] == "7"
    assert reply.metadata["parse_mode"] == "Markdown"
    assert reply.metadata["inline_keyboard"][-2][1]["text"] == "3/3"
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_callback_switch_persists_and_selected_message_claims_agent_route(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)
    thread_id = "22222222-2222-2222-2222-222222222222"

    async def list_threads(*, limit: int):
        assert limit == 100
        return [{"id": thread_id, "title": "继续当前任务", "status": "completed"}]

    plugin._list_threads = list_threads
    callback = incoming(f"acode:thread:{thread_id}", message_type="event")
    assert await plugin.on_message(callback, ctx) is True
    await asyncio.gather(*list(plugin._tasks))

    assert plugin._selected_thread("42") == thread_id
    assert (tmp_path / "selections.json").is_file()
    assert "继续当前任务" in replies[-1].content
    assert replies[-1].metadata["edit_message_id"] == "7"

    prompts: list[tuple[str, str]] = []

    async def process_prompt(message, selected_thread_id: str, content: str):
        prompts.append((selected_thread_id, content))

    plugin._process_prompt = process_prompt
    assert await plugin.on_message(incoming("继续修改代码"), ctx) is True
    await asyncio.gather(*list(plugin._tasks))
    assert prompts == [(thread_id, "继续修改代码")]
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_non_admin_cannot_open_task_menu(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)

    result = await plugin.on_message(incoming("/codex", sender_id="99"), ctx)

    assert result.content == "该功能仅限管理员使用。"
    assert plugin._tasks == set()
    await plugin.on_unload()


class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.login_json: dict[str, Any] | None = None
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any):
        self.login_json = kwargs.get("json")
        return FakeResponse(200, {"token": "short-lived-session-token"})

    def request(self, method: str, url: str, **kwargs: Any):
        self.requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(200, {"data": []})

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_admin_secret_is_used_only_for_login_and_session_token_authorizes_api(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    fake = FakeSession()
    plugin._session = fake

    result = await plugin._request("GET", "/api/threads?limit=1")

    assert result == {"data": []}
    assert fake.login_json == {"token": "a" * 32}
    assert fake.requests[0]["headers"] == {"Authorization": "Bearer short-lived-session-token"}
    assert "a" * 32 not in str(fake.requests)
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_watcher_returns_only_agent_result_to_telegram(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "33333333-3333-3333-3333-333333333333"
    run_key = add_pending_run(plugin, thread_id)
    now = "2026-08-15T20:00:00+00:00"

    async def request(method: str, path: str):
        assert method == "GET"
        assert path == f"/sessions/{thread_id}/events"
        return {
            "events": [
                {
                    "message": {
                        "type": "session-output",
                        "sessionId": thread_id,
                        "timestamp": now,
                        "payload": {
                            "eventType": "item/commandExecution/outputDelta",
                            "chunk": "secret command log",
                        },
                    }
                },
                {
                    "message": {
                        "type": "session-output",
                        "sessionId": thread_id,
                        "timestamp": now,
                        "payload": {
                            "eventType": "item/completed",
                            "jsonPayload": {
                                "item": {"type": "agentMessage", "text": "代码已经修改完成。"}
                            },
                        },
                    }
                },
                {
                    "message": {
                        "type": "session-finished",
                        "sessionId": thread_id,
                        "timestamp": now,
                        "payload": {"turn": {"id": "turn-new", "status": "completed"}},
                    }
                },
            ]
        }

    plugin._request = request
    await plugin._watch_run(run_key)

    assert len(replies) == 1
    assert "代码已经修改完成" in replies[0].content
    assert "secret command log" not in replies[0].content
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_watcher_ignores_unscoped_stale_finish_and_uses_final_turn_items(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "33333333-3333-3333-3333-333333333334"
    run_key = add_pending_run(plugin, thread_id, message_id="77")

    async def request(method: str, path: str):
        assert (method, path) == ("GET", f"/sessions/{thread_id}/events")
        return {"events": [
            {
                "message": {
                    "type": "session-finished",
                    "payload": {"turn": {"status": "completed"}},
                }
            },
            {
                "message": {
                    "type": "session-finished",
                    "payload": {
                        "turn": {
                            "id": "turn-new",
                            "status": "completed",
                            "items": [
                                {"type": "agentMessage", "text": "这是当前任务的真实回复。"}
                            ],
                        }
                    },
                }
            },
        ]}

    plugin._request = request
    await plugin._watch_run(run_key)

    assert len(replies) == 1
    assert replies[0].content == "这是当前任务的真实回复。"
    assert "没有返回文字内容" not in replies[0].content
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_prompt_creates_only_one_editable_progress_message(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "34343434-3434-3434-3434-343434343434"
    watched: list[tuple[str, str]] = []

    async def thread_status(selected_thread_id: str):
        assert selected_thread_id == thread_id
        return "completed"

    async def request(method: str, path: str, *, payload=None):
        assert (method, path, payload) == (
            "POST",
            f"/api/threads/{thread_id}/turns",
            {"text": "继续修改"},
        )
        return {"turn": {"id": "turn-new"}}

    async def watch(run_key: str):
        run = plugin._runs[run_key]
        watched.append((run["thread_id"], run["turn_id"]))

    plugin._thread_status = thread_status
    plugin._request = request
    plugin._watch_run = watch
    await plugin._process_prompt(incoming("继续修改"), thread_id, "继续修改")
    await asyncio.gather(*list(plugin._tasks))

    assert len(replies) == 1
    assert replies[0].content == plugin._live_progress("", [])
    assert "已发送给 Codex" not in replies[0].content
    run_key = f"{thread_id}:turn-new"
    assert plugin._runs[run_key]["targets"]["telegram:private:42"] == "1"
    assert watched == [(thread_id, "turn-new")]
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_typing_action_uses_live_telegram_adapter(tmp_path: Path) -> None:
    module = load_plugin_module()
    calls: list[tuple[str, str]] = []

    class TypingAdapter:
        async def send_chat_action(self, conversation_id: str, action: str) -> bool:
            calls.append((conversation_id, action))
            return True

    class Registry:
        def get(self, name: str):
            return TypingAdapter() if name == "telegram" else None

    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies, adapters=Registry()))

    await plugin._send_typing("telegram:private:42")

    assert calls == [("telegram:private:42", "typing")]
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_admin_private_menu_registers_acode_commands(tmp_path: Path) -> None:
    module = load_plugin_module()
    configured: list[tuple[list[str], list[dict[str, str]]]] = []

    class MenuAdapter:
        async def configure_command_menu(self, chat_ids, commands):
            configured.append((chat_ids, commands))

    class Registry:
        def get(self, name: str):
            return MenuAdapter() if name == "telegram" else None

    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies, adapters=Registry()))
    await asyncio.gather(*list(plugin._tasks))

    assert configured[0][0] == ["42"]
    assert [item["command"] for item in configured[0][1]] == [
        "codex", "find", "new", "rename", "archive", "archived",
        "status", "doctor", "stop", "agent", "help",
    ]
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_doctor_checks_gateway_codex_recovery_and_voice_without_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_plugin_module()

    class TelegramAdapter:
        async def send_chat_action(self, conversation_id: str, action: str) -> bool:
            return True

    class Registry:
        def get(self, name: str):
            return TelegramAdapter() if name == "telegram" else None

    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies, adapters=Registry()))
    await plugin._set_selection("42", "thread-1")
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: object())

    async def request(method: str, path: str, *, payload=None):
        if path == "/api/health":
            return {
                "ok": True,
                "publicOrigin": "http://must-not-leak:8787",
                "codexHome": "C:/must-not-leak",
                "codex": {"connected": True, "ready": True},
            }
        if path == "/sessions/thread-1":
            return {"session": {"status": "running"}}
        raise AssertionError((method, path, payload))

    plugin._request = request
    await plugin._send_doctor(incoming("/doctor"))

    assert len(replies) == 1
    content = replies[0].content
    assert "Codex 远程诊断" in content
    assert "✅ *aCode 网关*" in content
    assert "✅ *Codex 连接*" in content
    assert "事件链路正常 · running" in content
    assert "must-not-leak" not in content
    assert replies[0].metadata["inline_keyboard"][0][0]["callback_data"] == "acode:doctor"
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_telegram_image_is_forwarded_to_acode_as_base64_attachment(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    ctx = plugin_context(tmp_path, replies)
    await plugin.on_load(ctx)
    thread_id = "34343434-3434-3434-3434-343434343437"
    await plugin._set_selection("42", thread_id)
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"png-content")
    requests: list[dict[str, Any]] = []

    async def thread_status(selected_thread_id: str):
        assert selected_thread_id == thread_id
        return "completed"

    async def request(method: str, path: str, *, payload=None):
        requests.append({"method": method, "path": path, "payload": payload})
        return {"turn": {"id": "turn-media"}}

    async def watch(run_key: str):
        return None

    plugin._thread_status = thread_status
    plugin._request = request
    plugin._watch_run = watch
    message = incoming(
        "[图片]",
        message_type="image",
        attachments=[{
            "source": "telegram",
            "type": "image",
            "local_path": str(image_path),
            "file_name": "sample.png",
            "size": len(b"png-content"),
            "mime_type": "image/png",
        }],
    )

    assert await plugin.on_message(message, ctx) is True
    await asyncio.gather(*list(plugin._tasks))

    payload = requests[0]["payload"]
    assert payload["text"] == "请查看并处理我发送的附件。"
    assert payload["attachments"][0]["name"] == "sample.png"
    assert payload["attachments"][0]["mimeType"] == "image/png"
    assert base64.b64decode(payload["attachments"][0]["dataBase64"]) == b"png-content"
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_running_turn_rejects_attachment_instead_of_sending_path(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "34343434-3434-3434-3434-343434343438"
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"png")

    async def thread_status(selected_thread_id: str):
        return "running"

    async def request(*args, **kwargs):
        raise AssertionError("running turn must not receive attachment")

    plugin._thread_status = thread_status
    plugin._request = request
    await plugin._process_prompt(
        incoming("看看图片"),
        thread_id,
        "看看图片",
        attachments=[{
            "source": "telegram",
            "local_path": str(image_path),
            "mime_type": "image/png",
        }],
    )

    assert "暂时不能追加图片或文件" in replies[-1].content
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_running_thread_message_steers_existing_turn_without_new_progress_card(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "34343434-3434-3434-3434-343434343435"
    run_key = add_pending_run(plugin, thread_id, message_id="88")
    paths: list[str] = []
    watched: list[str] = []

    async def thread_status(selected_thread_id: str):
        assert selected_thread_id == thread_id
        return "running"

    async def request(method: str, path: str, *, payload=None):
        assert method == "POST"
        assert payload == {"text": "先处理失败测试"}
        paths.append(path)
        return {"turnId": "turn-new"}

    async def watch(selected_run_key: str):
        watched.append(selected_run_key)

    plugin._thread_status = thread_status
    plugin._request = request
    plugin._watch_run = watch

    await plugin._process_prompt(incoming("先处理失败测试"), thread_id, "先处理失败测试")
    await asyncio.gather(*list(plugin._tasks))

    assert paths == [f"/api/threads/{thread_id}/interjections"]
    assert list(plugin._runs) == [run_key]
    assert watched == [run_key]
    assert replies == []
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_stop_uses_active_turn_id_required_by_acode(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "34343434-3434-3434-3434-343434343439"
    add_pending_run(plugin, thread_id, turn_id="turn-active")
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}

    plugin._request = request
    await plugin._stop_thread(incoming("/stop"), thread_id)

    assert calls == [(
        "POST",
        f"/api/threads/{thread_id}/interrupt",
        {"turnId": "turn-active"},
    )]
    assert replies[-1].content == "停止请求已发送。"
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_on_load_recovers_finished_turn_and_delivers_once(tmp_path: Path) -> None:
    thread_id = "34343434-3434-3434-3434-343434343436"
    turn_id = "turn-recovered"
    run_key = f"{thread_id}:{turn_id}"
    (tmp_path / "pending_turns.json").write_text(
        json.dumps({
            run_key: {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "title": "恢复任务",
                "started_at": 0,
                "targets": {"telegram:private:42": "99"},
                "delivered_to": [],
            }
        }),
        encoding="utf-8",
    )
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []

    async def request(method: str, path: str):
        assert (method, path) == ("GET", f"/sessions/{thread_id}/events")
        return {"events": [
            {
                "message": {
                    "type": "session-output",
                    "payload": {
                        "turnId": turn_id,
                        "eventType": "item/completed",
                        "jsonPayload": {
                            "item": {"id": "agent-1", "type": "agentMessage", "text": "重启后补发成功。"}
                        },
                    },
                }
            },
            {
                "message": {
                    "type": "session-finished",
                    "payload": {"turn": {"id": turn_id, "status": "completed"}},
                }
            },
        ]}

    plugin._request = request
    await plugin.on_load(plugin_context(tmp_path, replies))
    await asyncio.gather(*list(plugin._tasks))

    assert len(replies) == 1
    assert replies[0].content == "重启后补发成功。"
    assert replies[0].metadata["edit_message_id"] == "99"
    assert json.loads((tmp_path / "pending_turns.json").read_text(encoding="utf-8")) == {}
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_timeout_notice_keeps_persistent_run_until_final_result(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "34343434-3434-3434-3434-343434343440"
    run_key = add_pending_run(plugin, thread_id, message_id="99")

    await plugin._deliver_timeout(run_key)

    assert len(replies) == 1
    assert "完成后会自动更新这里" in replies[0].content
    assert replies[0].metadata["inline_keyboard"][0][0]["callback_data"] == "acode:stop"
    assert run_key in plugin._runs
    assert plugin._runs[run_key]["delivered_to"] == []
    assert plugin._runs[run_key]["timeout_notified_to"] == ["telegram:private:42"]
    persisted = module.AcodeRemotePlugin._read_runs(tmp_path / "pending_turns.json")
    assert persisted[run_key]["timeout_notified_to"] == ["telegram:private:42"]

    await plugin._deliver_timeout(run_key)
    assert len(replies) == 1

    await plugin._deliver_result(run_key, "最终结果已返回。", "completed")

    assert len(replies) == 2
    assert replies[-1].content == "最终结果已返回。"
    assert run_key not in plugin._runs
    assert json.loads((tmp_path / "pending_turns.json").read_text(encoding="utf-8")) == {}
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_watcher_continues_after_timeout_without_repeating_notice(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    plugin._result_timeout = 0
    plugin._poll_interval = 0
    thread_id = "34343434-3434-3434-3434-343434343441"
    run_key = add_pending_run(plugin, thread_id, message_id="100")
    calls = 0

    async def request(method: str, path: str):
        nonlocal calls
        assert (method, path) == ("GET", f"/sessions/{thread_id}/events")
        calls += 1
        if calls < 3:
            return {"events": []}
        return {"events": [
            {
                "message": {
                    "type": "session-output",
                    "payload": {
                        "turnId": "turn-new",
                        "eventType": "item/completed",
                        "jsonPayload": {
                            "item": {
                                "id": "agent-final",
                                "type": "agentMessage",
                                "text": "超时后仍然成功补发。",
                            }
                        },
                    },
                }
            },
            {
                "message": {
                    "type": "session-finished",
                    "payload": {"turn": {"id": "turn-new", "status": "completed"}},
                }
            },
        ]}

    plugin._request = request
    await plugin._watch_run(run_key)

    assert calls == 3
    timeout_replies = [
        reply for reply in replies if "完成后会自动更新这里" in reply.content
    ]
    assert len(timeout_replies) == 1
    assert replies[-1].content == "超时后仍然成功补发。"
    assert run_key not in plugin._runs
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_watcher_edits_one_message_with_safe_progress_then_final_answer(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    plugin._poll_interval = 0
    thread_id = "35353535-3535-3535-3535-353535353535"
    conversation_id = "telegram:private:42"
    run_key = add_pending_run(
        plugin,
        thread_id,
        conversation_id=conversation_id,
        message_id="91",
    )
    calls = 0
    first_events = [
        {
            "message": {
                "type": "session-output",
                "payload": {
                    "turnId": "turn-new",
                    "eventType": "item/commandExecution/outputDelta",
                    "chunk": "TOKEN=must-not-leak cwd=C:\\secret",
                    "jsonPayload": {"itemId": "cmd-1"},
                },
            }
        },
        {
            "message": {
                "type": "session-output",
                "payload": {
                    "turnId": "turn-new",
                    "eventType": "item/agentMessage/delta",
                    "chunk": "我正在检查问题。",
                    "jsonPayload": {"itemId": "agent-1"},
                },
            }
        },
    ]
    final_events = [
        *first_events,
        {
            "message": {
                "type": "session-output",
                "payload": {
                    "turnId": "turn-new",
                    "eventType": "item/completed",
                    "jsonPayload": {
                        "item": {
                            "id": "cmd-1",
                            "type": "commandExecution",
                            "exitCode": 0,
                            "command": "private command",
                            "aggregatedOutput": "private output",
                        }
                    },
                },
            }
        },
        {
            "message": {
                "type": "session-output",
                "payload": {
                    "turnId": "turn-new",
                    "eventType": "item/completed",
                    "jsonPayload": {
                        "item": {"id": "agent-2", "type": "agentMessage", "text": "已经修复。"}
                    },
                },
            }
        },
        {
            "message": {
                "type": "session-finished",
                "payload": {"turn": {"id": "turn-new", "status": "completed"}},
            }
        },
    ]

    async def request(method: str, path: str):
        nonlocal calls
        calls += 1
        return {"events": first_events if calls == 1 else final_events}

    plugin._request = request
    await plugin._watch_run(run_key)

    assert len(replies) == 3
    assert all(reply.metadata["edit_message_id"] == "91" for reply in replies)
    assert "⏳ shell_command" in replies[0].content
    assert "我正在检查问题" in replies[0].content
    assert "✅ shell_command" in replies[1].content
    assert replies[-1].content == "已经修复。"
    combined = "\n".join(reply.content for reply in replies)
    assert "must-not-leak" not in combined
    assert "private command" not in combined
    assert "private output" not in combined
    assert "Codex｜" not in combined
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_long_result_edits_progress_then_sends_only_required_continuations(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "36363636-3636-3636-3636-363636363636"
    conversation_id = "telegram:private:42"
    run_key = add_pending_run(
        plugin,
        thread_id,
        conversation_id=conversation_id,
        message_id="92",
    )

    await plugin._finish_live_message(run_key, conversation_id, "甲" * 8000)

    assert len(replies) == 3
    assert replies[0].metadata["edit_message_id"] == "92"
    assert "edit_message_id" not in replies[1].metadata
    assert "edit_message_id" not in replies[2].metadata
    assert "".join(reply.content for reply in replies) == "甲" * 8000
    await plugin.on_unload()


def test_live_progress_shows_only_current_tool_without_details() -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    steps: list[str] = []
    running: dict[str, int] = {}

    plugin._update_tool_steps(
        {
            "eventType": "item/commandExecution/outputDelta",
            "chunk": "secret command output",
            "jsonPayload": {"itemId": "cmd-1"},
        },
        steps,
        running,
    )
    plugin._update_tool_steps(
        {
            "eventType": "item/webSearch/outputDelta",
            "jsonPayload": {"itemId": "search-1", "query": "private query"},
        },
        steps,
        running,
    )

    content = plugin._live_progress("", steps)
    assert content == (
        "*🟢 Codex 正在处理*\n\n──────────\n\n"
        "⏳ web_search\n\n💭 *正在思考…*"
    )
    assert "命令" not in content
    assert "secret" not in content
    assert "private" not in content
    assert plugin._tool_display_name("fileChange", {}) == "apply_patch"


def test_attachment_chat_action_matches_media_kind() -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()

    assert plugin._attachment_action([{"type": "image"}, {"type": "image"}]) == "upload_photo"
    assert plugin._attachment_action([{"type": "video"}]) == "upload_video"
    assert plugin._attachment_action([{"type": "voice"}]) == "upload_voice"
    assert plugin._attachment_action([{"type": "image"}, {"type": "file"}]) == "upload_document"


def test_manifest_is_telegram_private_and_before_agent_fallback() -> None:
    path = Path(__file__).resolve().parents[3] / "plugins" / "acode_remote" / "plugin.toml"
    with path.open("rb") as stream:
        manifest = tomllib.load(stream)

    routing = manifest["routing"]
    assert routing["platforms"] == ["telegram"]
    assert routing["adapters"] == ["telegram"]
    assert routing["scopes"] == ["private"]
    assert {"image", "file", "video", "voice"}.issubset(routing["message_types"])
    assert routing["fallback"] is False
    assert routing["exclusive"] is False
    assert routing["priority"] < 10000


def test_active_writer_error_is_translated_without_leaking_raw_protocol() -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()

    message = plugin._safe_error(
        module.AcodeApiError(500, "thread abc already has an active writer")
    )

    assert "电脑端 Codex" in message
    assert "active writer" not in message


@pytest.mark.asyncio
async def test_active_writer_offers_fork_with_original_prompt(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    thread_id = "44444444-4444-4444-4444-444444444444"
    plugin._thread_titles[thread_id] = "当前电脑任务"

    async def thread_status(selected_thread_id: str):
        assert selected_thread_id == thread_id
        return "completed"

    async def request(method: str, path: str, *, payload=None):
        raise module.AcodeApiError(500, f"thread {thread_id} already has an active writer")

    plugin._thread_status = thread_status
    plugin._request = request
    await plugin._process_prompt(incoming("继续修复"), thread_id, "继续修复")

    assert len(replies) == 1
    button = replies[0].metadata["inline_keyboard"][0][0]
    assert button["callback_data"].startswith("acode:fork:")
    request_id = button["callback_data"].removeprefix("acode:fork:")
    assert plugin._fork_requests[request_id]["content"] == "继续修复"
    assert "电脑端正在使用" in replies[0].content
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_fork_callback_is_idempotent_and_sends_original_prompt_once(tmp_path: Path) -> None:
    module = load_plugin_module()
    plugin = module.AcodeRemotePlugin()
    replies: list[Any] = []
    await plugin.on_load(plugin_context(tmp_path, replies))
    source_id = "55555555-5555-5555-5555-555555555555"
    forked_id = "66666666-6666-6666-6666-666666666666"
    request_id = "a" * 32
    plugin._fork_requests[request_id] = {
        "sender_id": "42",
        "conversation_id": "telegram:private:42",
        "source_thread_id": source_id,
        "source_title": "电脑任务",
        "content": "继续执行",
        "created_at": 1,
        "processing": False,
        "forked_thread_id": "",
    }
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    prompts: list[tuple[str, str]] = []

    async def request(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        return {"threadId": forked_id, "applied": True, "replayed": False}

    async def process_prompt(message, thread_id: str, content: str):
        prompts.append((thread_id, content))

    plugin._request = request
    plugin._process_prompt = process_prompt
    callback = incoming(f"acode:fork:{request_id}", message_type="event")

    await plugin._fork_and_send(callback, request_id)
    await plugin._fork_and_send(callback, request_id)

    assert calls == [(
        "POST",
        f"/api/threads/{source_id}/fork",
        {"title": "TG｜电脑任务", "idempotency_key": request_id},
    )]
    assert prompts == [(forked_id, "继续执行")]
    assert plugin._selected_thread("42") == forked_id
    assert replies[0].metadata["edit_message_id"] == "7"
    await plugin.on_unload()

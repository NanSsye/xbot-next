from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import plugins.OpenClawBridge.main as openclaw_main
from plugins.OpenClawBridge.main import OpenClawBridgePlugin
from xbot.messaging.models import Message
from xbot.plugins.context import PluginContext


def _ctx(tmp_path: Path) -> PluginContext:
    return PluginContext(
        name="openclaw_bridge",
        data_dir=tmp_path,
        config={
            "filters": {
                "filter_mode": "None",
                "whitelist": [],
                "blacklist": [],
                "mention_only": True,
                "allow_groups": True,
                "trigger_words": [],
                "disable_private_chat_at_trigger": False,
            },
            "limits": {"enable_group_limit": False},
            "prompt": {"enabled": False, "mode": "body_for_agent", "text": ""},
        },
        send_reply=lambda reply: None,
    )


async def _make_plugin(monkeypatch, tmp_path: Path, bot_wxid: str = "wxid_bot"):
    plugin = OpenClawBridgePlugin()
    ctx = _ctx(tmp_path)
    forwarded: list[dict] = []

    async def fake_forward(*args, **kwargs):
        forwarded.append({"args": args, "kwargs": kwargs})

    async def fake_contacts():
        return {}

    async def fake_display_name(*args, **kwargs):
        return "某人"

    monkeypatch.setattr(plugin, "forward_to_openclaw", fake_forward)
    monkeypatch.setattr(plugin, "get_contacts_cache", fake_contacts)
    monkeypatch.setattr(plugin, "_schedule_group_members_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(plugin, "_resolve_sender_display_name", fake_display_name)
    monkeypatch.setattr(openclaw_main, "get_contact_from_db", lambda *a, **k: None)
    monkeypatch.setattr(plugin, "limits_config", {"enable_group_limit": False})
    monkeypatch.setattr(
        openclaw_main.group_members_db_module,
        "_connect",
        lambda: pytest.fail("测试不应访问真实群限制/联系人数据库"),
    )
    plugin.bot = openclaw_main._XBot869BotShim(ctx, plugin)
    plugin.bot.wxid = bot_wxid
    return plugin, ctx, forwarded


@pytest.mark.anyio
async def test_openclaw_bridge_private_message_forwarded(monkeypatch, tmp_path):
    plugin, ctx, forwarded = await _make_plugin(monkeypatch, tmp_path)
    message = Message(
        id="m1",
        platform="wechat",
        adapter="wechat869",
        conversation_id="wxid_user",
        sender_id="wxid_user",
        content="你好",
        raw={"scope": "private", "sender_wxid": "wxid_user", "message_id": "m1"},
    )

    result = await plugin.on_message(message, ctx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert result is True
    assert len(forwarded) == 1
    assert forwarded[0]["args"][0] == "wxid_user"
    assert forwarded[0]["args"][1] == "你好"
    assert forwarded[0]["args"][2] == "wxid_user"
    assert forwarded[0]["args"][3] is False


@pytest.mark.anyio
async def test_openclaw_bridge_group_untriggered_not_forwarded(monkeypatch, tmp_path):
    plugin, ctx, forwarded = await _make_plugin(monkeypatch, tmp_path)
    message = Message(
        id="m2",
        platform="wechat",
        adapter="wechat869",
        conversation_id="room@chatroom",
        sender_id="wxid_user",
        content="普通群聊",
        raw={
            "scope": "group",
            "sender_wxid": "wxid_user",
            "group_wxid": "room@chatroom",
            "mentions_bot": False,
        },
    )

    result = await plugin.on_message(message, ctx)
    await asyncio.sleep(0)

    assert result is False
    assert forwarded == []


@pytest.mark.anyio
async def test_openclaw_bridge_group_mention_forwarded(monkeypatch, tmp_path):
    plugin, ctx, forwarded = await _make_plugin(monkeypatch, tmp_path)
    message = Message(
        id="m3",
        platform="wechat",
        adapter="wechat869",
        conversation_id="room@chatroom",
        sender_id="wxid_user",
        content="@小球球 在吗",
        raw={
            "scope": "group",
            "sender_wxid": "wxid_user",
            "group_wxid": "room@chatroom",
            "mentions_bot": True,
            "bot_wxid": "wxid_bot",
            "bot_nickname": "小球球",
        },
    )

    result = await plugin.on_message(message, ctx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert result is True
    assert len(forwarded) == 1
    assert forwarded[0]["args"][2] == "room@chatroom"
    assert forwarded[0]["args"][3] is True

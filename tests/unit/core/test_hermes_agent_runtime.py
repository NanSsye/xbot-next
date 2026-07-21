from __future__ import annotations

import json

import anyio
import pytest

from xbot.agent.hermes_runtime import (
    _ensure_hermes_home_files,
    _ensure_hermes_import_path,
    _permission_profile_for_source,
    _restore_session_history,
    _session_source_for_source,
    _session_id_for_source,
    _tool_policy_denial,
    _tool_policy_for_source,
    _toolsets_for_source,
    clear_hermes_session,
)
import xbot.agent.runtime as runtime_module
from xbot.agent.runtime import AgentRuntime
from xbot.core.config import AgentConfig


@pytest.mark.anyio
async def test_agent_runtime_uses_embedded_hermes_by_default(monkeypatch):
    calls = []

    async def fake_run_hermes_agent(**kwargs):
        calls.append(kwargs)
        await kwargs["add_event"](kwargs["task_id"], "hermes.test", {"ok": True})
        return "hermes output"

    monkeypatch.setattr(runtime_module, "run_hermes_agent", fake_run_hermes_agent)

    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    result = await runtime.run_task("hello", source="api")

    assert result.output == "hermes output"
    assert calls
    assert calls[0]["input_text"] == "hello"
    assert calls[0]["source"] == "api"


def test_restore_session_history_uses_hermes_session_db():
    class FakeSessionDB:
        def get_session(self, session_id):
            assert session_id == "old-session"
            return {"id": session_id}

        def resolve_resume_session_id(self, session_id):
            assert session_id == "old-session"
            return "new-session"

        def get_messages_as_conversation(self, session_id):
            assert session_id == "new-session"
            return [
                {"role": "session_meta", "content": "ignored"},
                {"role": "user", "content": "previous"},
                {"role": "assistant", "content": "done"},
            ]

    class FakeAgent:
        session_id = "old-session"
        _session_db = FakeSessionDB()

    agent = FakeAgent()

    assert _restore_session_history(agent) == [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "done"},
    ]
    assert agent.session_id == "new-session"


def test_ensure_hermes_home_files_creates_default_config(tmp_path):
    _ensure_hermes_home_files(tmp_path)

    config_path = tmp_path / "config.yaml"
    env_example_path = tmp_path / ".env.example"

    assert config_path.exists()
    assert env_example_path.exists()
    assert "memory_enabled: true" in config_path.read_text(encoding="utf-8")
    assert "creation_nudge_interval" in config_path.read_text(encoding="utf-8")
    assert "curator:" in config_path.read_text(encoding="utf-8")
    assert "XBOT_LLM_BASE_URL" in env_example_path.read_text(encoding="utf-8")


def test_permission_scoped_channel_source_selects_hermes_toolsets():
    assert _toolsets_for_source("channel:wechat:wechat869:group@chatroom:guest") == ["wechat"]
    assert "file" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "terminal" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "wechat" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert _toolsets_for_source("channel:wechat:wechat869:group@chatroom") == ["hermes-api-server"]


def test_permission_scoped_channel_source_shares_hermes_session_with_allowed_source():
    allowed = "channel:wechat:wechat869:group@chatroom"
    restricted = "channel:wechat:wechat869:group@chatroom:restricted"
    member = "channel:wechat:wechat869:group@chatroom:member"
    guest = "channel:wechat:wechat869:group@chatroom:guest"

    assert _session_source_for_source(restricted) == allowed
    assert _session_source_for_source(member) == allowed
    assert _session_source_for_source(guest) == allowed
    assert _session_id_for_source(restricted) == _session_id_for_source(allowed)
    assert _session_id_for_source(member) == _session_id_for_source(allowed)
    assert _session_id_for_source(guest) == _session_id_for_source(allowed)
    assert _permission_profile_for_source(member) == "member"
    assert _permission_profile_for_source(guest) == "guest"
    assert _toolsets_for_source(allowed) == ["hermes-api-server"]


def test_wechat_tools_are_registered_for_admin_and_member():
    _ensure_hermes_import_path()
    from model_tools import get_tool_definitions

    admin_names = {item["function"]["name"] for item in get_tool_definitions(["hermes-api-server"], quiet_mode=True)}
    member_names = {item["function"]["name"] for item in get_tool_definitions(["wechat"], quiet_mode=True)}
    expected = {
        "wechat_send_text", "wechat_send_image", "wechat_send_file", "wechat_send_voice",
        "wechat_send_video", "wechat_send_link", "wechat_send_music_card",
    }
    assert expected <= admin_names
    assert expected <= member_names


@pytest.mark.anyio
async def test_runtime_passes_reply_sender_to_hermes(monkeypatch):
    captured = {}

    async def fake_run_hermes_agent(**kwargs):
        captured.update(kwargs)
        kwargs["mark_proactive_send"]()
        return "ok"

    async def sender(reply):
        return None

    monkeypatch.setattr(runtime_module, "run_hermes_agent", fake_run_hermes_agent)
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    runtime.attach_reply_sender(sender)
    result = await runtime.run_task("hello", source="channel:wechat:wechat869:group@chatroom:member")
    assert captured["send_reply"] is sender
    assert result.suppress_channel_reply is True


@pytest.mark.anyio
async def test_wechat_tool_routes_current_and_explicit_targets():
    _ensure_hermes_import_path()
    from tools.xbot_wechat_tools import reset_send_context, send_text, set_send_context

    calls = []

    async def sender(**kwargs):
        calls.append(kwargs)

    token = set_send_context({
        "loop": __import__("asyncio").get_running_loop(),
        "sender": sender,
        "adapter": "wechat869",
        "conversation_id": "current@chatroom",
    })
    try:
        current = json.loads(await anyio.to_thread.run_sync(send_text, {"text": "current"}))
        explicit = json.loads(await anyio.to_thread.run_sync(
            send_text, {"to_wxid": "wxid_target", "text": "direct"}
        ))
    finally:
        reset_send_context(token)

    assert current["to_wxid"] == "current@chatroom"
    assert explicit["to_wxid"] == "wxid_target"
    assert [item["conversation_id"] for item in calls] == ["current@chatroom", "wxid_target"]


def test_wechat_tool_without_context_returns_error():
    _ensure_hermes_import_path()
    from tools.xbot_wechat_tools import send_text

    assert "error" in json.loads(send_text({"text": "hello"}))


@pytest.mark.anyio
async def test_wechat_extended_tools_build_metadata_and_route_targets():
    _ensure_hermes_import_path()
    from tools.xbot_wechat_tools import (
        reset_send_context, send_link, send_music_card, send_video, send_voice, set_send_context,
    )

    calls = []

    async def sender(**kwargs):
        calls.append(kwargs)

    token = set_send_context({
        "loop": __import__("asyncio").get_running_loop(), "sender": sender,
        "adapter": "wechat869", "conversation_id": "current@chatroom",
    })
    try:
        await anyio.to_thread.run_sync(send_voice, {"path": "voice.wav", "format": "wav", "seconds": 3})
        await anyio.to_thread.run_sync(send_video, {"to_wxid": "wxid_video", "path": "video.mp4"})
        await anyio.to_thread.run_sync(send_link, {
            "url": "https://example.com/?a=1&b=2", "title": "A&B", "desc": "<safe>",
        })
        await anyio.to_thread.run_sync(send_music_card, {
            "title": "Song", "singer": "A&B", "url": "https://example.com/song",
            "music_url": "https://example.com/song.mp3", "cover_url": "https://example.com/c.jpg",
        })
    finally:
        reset_send_context(token)

    assert [item["message_type"] for item in calls] == ["voice", "video", "link", "music_card"]
    assert calls[0]["metadata"] == {"format": "wav", "seconds": 3}
    assert calls[1]["conversation_id"] == "wxid_video"
    assert calls[2]["metadata"]["content_type"] == 5
    assert "A&amp;B" in calls[2]["metadata"]["content_xml"]
    assert "&lt;safe&gt;" in calls[2]["metadata"]["content_xml"]
    assert calls[3]["metadata"]["content_type"] == 3
    assert "<type>3</type>" in calls[3]["metadata"]["content_xml"]


def test_member_tool_policy_limits_files_to_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = AgentConfig()
    config.member_policy.workspace_roots = ["workspace"]
    policy = _tool_policy_for_source(config, "channel:wechat:wechat869:group@chatroom:member")

    assert _tool_policy_denial("read_file", {"path": "workspace/app.py"}, policy) is None
    denial = _tool_policy_denial("read_file", {"path": "../secret.txt"}, policy)
    assert denial
    assert "授权工作目录外" in denial


def test_guest_policy_allows_only_wechat_send_tools():
    policy = {"profile": "guest"}
    assert _tool_policy_denial("wechat_send_text", {"text": "hi"}, policy) is None
    assert _tool_policy_denial("wechat_send_image", {"path": "a.png"}, policy) is None
    assert _tool_policy_denial("wechat_send_file", {"path": "a.pdf"}, policy) is None
    assert _tool_policy_denial("wechat_send_voice", {"path": "a.wav"}, policy) is None
    assert _tool_policy_denial("wechat_send_video", {"path": "a.mp4"}, policy) is None
    assert _tool_policy_denial("wechat_send_link", {"url": "https://example.com"}, policy) is None
    assert _tool_policy_denial("wechat_send_music_card", {"music_url": "https://example.com/a.mp3"}, policy) is None
    assert _tool_policy_denial("read_file", {"path": "a.txt"}, policy)


def test_member_tool_policy_blocks_private_network_targets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "workspace").mkdir()
    config = AgentConfig()
    config.member_policy.workspace_roots = ["workspace"]
    policy = _tool_policy_for_source(config, "channel:wechat:wechat869:group@chatroom:member")

    assert _tool_policy_denial("web_extract", {"url": "https://example.com"}, policy) is None
    assert _tool_policy_denial("web_extract", {"url": "http://192.168.6.19:3000"}, policy)
    assert _tool_policy_denial("terminal", {"command": "nmap 192.168.6.0/24"}, policy)
    assert _tool_policy_denial("execute_code", {"code": "print(1)"}, policy)


def test_ensure_hermes_home_files_does_not_overwrite_existing_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("memory:\n  memory_enabled: false\n", encoding="utf-8")

    _ensure_hermes_home_files(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "memory:\n  memory_enabled: false\n"


def test_clear_hermes_session_deletes_only_source_session(tmp_path, monkeypatch):
    monkeypatch.setattr("xbot.agent.hermes_runtime.hermes_home_dir", lambda: tmp_path)
    _ensure_hermes_import_path()

    from hermes_state import SessionDB

    target_source = "channel:wechat:wechat869:group-1@chatroom"
    target_session_id = _session_id_for_source(target_source)
    other_session_id = _session_id_for_source("channel:wechat:wechat869:group-2@chatroom")
    session_db = SessionDB(db_path=tmp_path / "state.db")
    session_db.create_session(target_session_id, source=target_source, system_prompt="old")
    session_db.create_session(other_session_id, source="other", system_prompt="keep")

    result = clear_hermes_session(target_source)

    assert result["session_id"] == target_session_id
    assert result["deleted"] is True
    assert session_db.get_session(target_session_id) is None
    assert session_db.get_session(other_session_id) is not None

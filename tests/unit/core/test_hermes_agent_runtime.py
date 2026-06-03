from __future__ import annotations

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
    assert _toolsets_for_source("channel:wechat:wechat869:group@chatroom:guest") == []
    assert "file" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "terminal" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
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

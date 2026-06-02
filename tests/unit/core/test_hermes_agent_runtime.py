from __future__ import annotations

import pytest

from xbot.agent.hermes_runtime import _ensure_hermes_home_files, _restore_session_history
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


def test_ensure_hermes_home_files_does_not_overwrite_existing_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("memory:\n  memory_enabled: false\n", encoding="utf-8")

    _ensure_hermes_home_files(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "memory:\n  memory_enabled: false\n"

from __future__ import annotations

import pytest

import xbot.agent.hermes_runtime as hermes_runtime
from xbot.core.config import AgentConfig


def test_unknown_model_fallback_and_default_compression_policy():
    hermes_runtime._ensure_hermes_import_path()

    from agent.model_metadata import CONTEXT_PROBE_TIERS, DEFAULT_FALLBACK_CONTEXT
    from hermes_cli.config_defaults import DEFAULT_CONFIG

    assert CONTEXT_PROBE_TIERS[0] == 512_000
    assert DEFAULT_FALLBACK_CONTEXT == 512_000
    assert DEFAULT_CONFIG["compression"]["threshold"] == pytest.approx(0.80)
    assert "threshold: 0.80" in hermes_runtime._DEFAULT_HERMES_CONFIG


def test_explicit_runtime_context_calibrates_main_and_auxiliary_compression(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    hermes_runtime._ensure_hermes_home_files(tmp_path)
    hermes_runtime._ensure_hermes_import_path()

    from hermes_state import SessionDB
    from run_agent import AIAgent

    session_db = SessionDB(db_path=tmp_path / "state.db")
    try:
        agent = AIAgent(
            base_url="https://example.invalid/v1",
            api_key="test-key",
            provider="custom",
            api_mode="chat_completions",
            model="test-model",
            enabled_toolsets=["wechat"],
            quiet_mode=True,
            session_id="xbot-context-policy",
            session_db=session_db,
            skip_context_files=True,
            skip_memory=True,
            context_length=1_000_000,
        )

        assert agent.context_compressor.context_length == 1_000_000
        assert agent.context_compressor.threshold_percent == pytest.approx(0.80)
        assert agent.context_compressor.threshold_tokens == 800_000
        assert agent._aux_compression_context_length_config == 1_000_000
    finally:
        session_db.close()


@pytest.mark.anyio
async def test_xbot_passes_configured_context_to_selected_group_model(
    tmp_path, monkeypatch
):
    hermes_runtime._ensure_hermes_import_path()
    import hermes_cli.env_loader as env_loader
    import hermes_state
    import run_agent

    captured = {}

    class FakeSessionDB:
        def get_session(self, session_id):
            return None

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.session_id = kwargs["session_id"]
            self._session_db = kwargs["session_db"]
            self.tools = []
            self.valid_tool_names = set()

        def run_conversation(self, *args, **kwargs):
            return "done"

    async def add_event(*args, **kwargs):
        return None

    config = AgentConfig()
    config.llm.enabled = True
    config.llm.api_key = "test-key"
    config.llm.base_url = "https://example.invalid/v1"
    config.llm.model = "default-model"
    config.llm.enabled_models = ["default-model", "group-model"]
    config.llm.context_window_tokens = 1_000_000

    monkeypatch.setattr(hermes_runtime, "hermes_home_dir", lambda: tmp_path)
    monkeypatch.setattr(hermes_runtime, "_assert_safe_hermes_sqlite", lambda: None)
    monkeypatch.setattr(hermes_runtime, "_configure_hermes_auxiliary_client", lambda *args: None)
    monkeypatch.setattr(hermes_runtime, "_install_hermes_tool_policy_wrapper", lambda: None)
    monkeypatch.setattr(env_loader, "load_hermes_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(hermes_state, "SessionDB", FakeSessionDB)
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)

    result = await hermes_runtime.run_hermes_agent(
        config=config,
        task_id="task-context-policy",
        input_text="hello",
        source="api",
        attachments=None,
        add_event=add_event,
        llm_status=dict,
        channel_context={"conversation_model": "group-model"},
    )

    assert result == "done"
    assert captured["model"] == "group-model"
    assert captured["context_length"] == 1_000_000

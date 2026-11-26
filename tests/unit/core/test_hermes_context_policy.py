from __future__ import annotations

from types import SimpleNamespace

import pytest

import xbot.agent.hermes_runtime as hermes_runtime
from xbot.core.config import AgentConfig


def test_unknown_model_fallback_and_default_compression_policy():
    hermes_runtime._ensure_hermes_import_path()

    from agent.model_metadata import CONTEXT_PROBE_TIERS, DEFAULT_FALLBACK_CONTEXT
    assert CONTEXT_PROBE_TIERS[0] == DEFAULT_FALLBACK_CONTEXT == 256_000
    assert "threshold: 0.80" in hermes_runtime._DEFAULT_HERMES_CONFIG


def test_explicit_runtime_context_calibrates_main_compression(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    hermes_runtime._ensure_hermes_home_files(tmp_path)
    hermes_runtime._ensure_hermes_import_path()

    from agent.agent_init import set_config_context_length
    from run_agent import AIAgent

    agent = AIAgent(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        provider="custom",
        api_mode="chat_completions",
        model="test-model",
        enabled_toolsets=["wechat"],
        quiet_mode=True,
        session_id="xbot-context-policy",
        skip_context_files=True,
        skip_memory=True,
    )

    try:
        set_config_context_length(agent, 1_000_000)
        agent.context_compressor.context_length = 1_000_000
        assert agent.context_compressor.context_length == 1_000_000
        assert agent.context_compressor.threshold_percent == pytest.approx(0.80)
    finally:
        agent.close()


@pytest.mark.anyio
async def test_xbot_passes_configured_context_to_selected_group_model(
    tmp_path, monkeypatch
):
    hermes_runtime._ensure_hermes_import_path()
    import hermes_cli.env_loader as env_loader
    import run_agent
    from agent.tool_guardrails import ToolGuardrailDecision

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.session_id = kwargs["session_id"]
            self.context_compressor = SimpleNamespace()
            self._tool_guardrails = SimpleNamespace(before_call=lambda *args: ToolGuardrailDecision())
            self.tools = []
            self.valid_tool_names = set()

        def run_conversation(self, *args, **kwargs):
            captured["context_length"] = self.context_compressor.context_length
            captured["aux_model"] = hermes_runtime._HERMES_AUX_RUNTIME.get()["model"]
            return "done"

        def close(self):
            pass

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
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
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
    assert captured["aux_model"] == "group-model"
    assert captured["context_length"] == 1_000_000

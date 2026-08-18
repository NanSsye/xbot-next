from __future__ import annotations

import json

import anyio
import pytest

import xbot.agent.hermes_runtime as hermes_runtime_module
import xbot.agent.runtime as runtime_module
from xbot.agent.hermes_runtime import (
    _assert_safe_hermes_sqlite,
    _configure_hermes_auxiliary_client,
    _ensure_hermes_home_files,
    _ensure_hermes_import_path,
    _group_persona_identity_override,
    _model_for_channel,
    _permission_profile_for_source,
    _restore_session_history,
    _session_id_for_source,
    _session_source_for_source,
    _tool_policy_denial,
    _tool_policy_for_source,
    _toolsets_for_source,
    clear_hermes_session,
)
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
    assert _toolsets_for_source("channel:wechat:wechat869:group@chatroom:guest") == [
        "wechat",
        "weiban-readonly",
        "weiban-knowledge",
        "artifacts",
    ]


def test_group_persona_replaces_soul_identity_without_wrapper():
    prompt = _group_persona_identity_override({"group_persona_prompt": " 你叫小法，回答简洁。 "})

    assert prompt == "你叫小法，回答简洁。"
    assert _group_persona_identity_override({}) is None
    config = AgentConfig(llm={"model": "default-model", "enabled_models": ["default-model", "group-model"]})
    assert _model_for_channel(config, {"group_model": "group-model"}) == "group-model"
    assert _model_for_channel(config, {"group_model": "removed-model"}) == "default-model"
    assert _model_for_channel(config, {}) == "default-model"
    assert "file" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "terminal" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "wechat" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "weiban-readonly" in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert "weiban-admin" not in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:guest")
    assert "weiban-admin" not in _toolsets_for_source("channel:wechat:wechat869:group@chatroom:member")
    assert _toolsets_for_source("channel:wechat:wechat869:group@chatroom") == [
        "hermes-api-server",
        "wechat",
        "weiban-readonly",
        "weiban-knowledge",
        "weiban-admin",
        "artifacts",
    ]


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
    assert _toolsets_for_source(allowed) == [
        "hermes-api-server",
        "wechat",
        "weiban-readonly",
        "weiban-knowledge",
        "weiban-admin",
        "artifacts",
    ]


def test_wechat_tools_are_registered_for_admin_and_member():
    _ensure_hermes_import_path()
    from model_tools import get_tool_definitions

    admin_names = {
        item["function"]["name"]
        for item in get_tool_definitions(
            _toolsets_for_source("channel:wechat:wechat869:group@chatroom"),
            quiet_mode=True,
            skip_tool_search_assembly=True,
        )
    }
    member_names = {
        item["function"]["name"]
        for item in get_tool_definitions(
            ["wechat"],
            quiet_mode=True,
            skip_tool_search_assembly=True,
        )
    }
    expected = {
        "wechat_send_text", "wechat_send_image", "wechat_send_file", "wechat_send_voice",
        "wechat_send_video", "wechat_send_link", "wechat_send_music_card",
    }
    assert expected <= admin_names
    assert expected <= member_names


def test_weiban_readonly_tool_is_registered_for_every_permission_profile():
    _ensure_hermes_import_path()
    from model_tools import get_tool_definitions

    sources = (
        "channel:wechat:wechat869:group@chatroom:guest",
        "channel:wechat:wechat869:group@chatroom:member",
        "channel:wechat:wechat869:group@chatroom",
    )
    for source in sources:
        tool_names = {
            item["function"]["name"]
            for item in get_tool_definitions(
                _toolsets_for_source(source),
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
        }
        assert "weiban_query_account" in tool_names

    guest_names = {
        item["function"]["name"]
        for item in get_tool_definitions(
            _toolsets_for_source(sources[0]),
            quiet_mode=True,
            skip_tool_search_assembly=True,
        )
    }
    assert guest_names == {
        "wechat_send_text",
        "wechat_send_image",
        "wechat_send_file",
        "wechat_send_voice",
        "wechat_send_video",
        "wechat_send_link",
        "wechat_send_music_card",
        "weiban_query_account",
        "weiban_search_knowledge",
        "artifact_create",
    }


@pytest.mark.anyio
async def test_guest_runtime_uses_direct_policy_filtered_tools_without_deferred_search(tmp_path, monkeypatch):
    _ensure_hermes_import_path()
    import hermes_cli.env_loader as env_loader
    import hermes_state
    import model_tools
    import run_agent

    agents = []
    tool_definition_calls = []

    class FakeSessionDB:
        def get_session(self, session_id):
            return None

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            self._session_db = kwargs["session_db"]
            self.enabled_toolsets = kwargs["enabled_toolsets"]
            self.tools = [
                {"function": {"name": "tool_search"}},
                {"function": {"name": "tool_describe"}},
                {"function": {"name": "tool_call"}},
            ]
            self.valid_tool_names = {"tool_search", "tool_describe", "tool_call"}
            agents.append(self)

        def run_conversation(self, *args, **kwargs):
            return "done"

    def fake_get_tool_definitions(enabled_toolsets, *, quiet_mode, skip_tool_search_assembly=False):
        tool_definition_calls.append((enabled_toolsets, quiet_mode, skip_tool_search_assembly))
        return [
            {"function": {"name": "qq_send_text"}},
            {"function": {"name": "qq_send_markdown"}},
            {"function": {"name": "qq_recall"}},
            {"function": {"name": "qq_react"}},
            {"function": {"name": "weiban_query_account"}},
            {"function": {"name": "artifact_create"}},
            {"function": {"name": "tool_search"}},
            {"function": {"name": "tool_describe"}},
            {"function": {"name": "tool_call"}},
        ]

    async def add_event(*args, **kwargs):
        return None

    config = AgentConfig()
    config.llm.enabled = True
    config.llm.api_key = "test-key"
    config.llm.base_url = "https://example.invalid/v1"
    config.llm.model = "test-model"
    config.member_policy.enabled = True
    monkeypatch.setattr(hermes_runtime_module, "hermes_home_dir", lambda: tmp_path)
    monkeypatch.setattr(hermes_runtime_module, "_assert_safe_hermes_sqlite", lambda: None)
    monkeypatch.setattr(hermes_runtime_module, "_configure_hermes_auxiliary_client", lambda *args: None)
    monkeypatch.setattr(hermes_runtime_module, "_install_hermes_tool_policy_wrapper", lambda: None)
    monkeypatch.setattr(env_loader, "load_hermes_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(hermes_state, "SessionDB", FakeSessionDB)
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
    monkeypatch.setattr(model_tools, "get_tool_definitions", fake_get_tool_definitions)

    for source in (
        "channel:qq:qq:c2c:test:guest",
        "channel:qq:qq:c2c:test:member",
        "channel:qq:qq:c2c:test",
    ):
        result = await hermes_runtime_module.run_hermes_agent(
            config=config,
            task_id=f"task-{source.rsplit(':', 1)[-1]}",
            input_text="查询账号",
            source=source,
            attachments=None,
            add_event=add_event,
            llm_status=dict,
        )
        assert result == "done"

    guest_agent, member_agent, admin_agent = agents
    assert {item["function"]["name"] for item in guest_agent.tools} == {
        "qq_send_text",
        "qq_send_markdown",
        "weiban_query_account",
        "artifact_create",
    }
    assert guest_agent.valid_tool_names == {
        "qq_send_text",
        "qq_send_markdown",
        "weiban_query_account",
        "artifact_create",
    }
    assert {item["function"]["name"] for item in member_agent.tools} == {
        "tool_search",
        "tool_describe",
        "tool_call",
    }
    assert {item["function"]["name"] for item in admin_agent.tools} == {
        "tool_search",
        "tool_describe",
        "tool_call",
    }
    assert tool_definition_calls == [
        (["qq", "weiban-readonly", "weiban-knowledge", "artifacts"], True, True),
    ]


def test_hermes_sqlite_gate_rejects_vulnerable_runtime(monkeypatch):
    monkeypatch.setattr("xbot.agent.hermes_runtime.sqlite3.sqlite_version_info", (3, 45, 1))
    monkeypatch.setattr("xbot.agent.hermes_runtime.sqlite3.sqlite_version", "3.45.1")

    with pytest.raises(RuntimeError, match="WAL-reset corruption bug"):
        _assert_safe_hermes_sqlite()


def test_hermes_sqlite_gate_accepts_fixed_runtime(monkeypatch):
    monkeypatch.setattr("xbot.agent.hermes_runtime.sqlite3.sqlite_version_info", (3, 51, 3))
    monkeypatch.setattr("xbot.agent.hermes_runtime.sqlite3.sqlite_version", "3.51.3")

    _assert_safe_hermes_sqlite()


def test_upgraded_hermes_aiagent_constructor_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _ensure_hermes_home_files(tmp_path)
    _ensure_hermes_import_path()

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
            session_id="xbot-constructor-contract",
            session_db=session_db,
            skip_context_files=True,
            skip_memory=True,
        )
        agent._soul_identity_override = "你叫小球子。"
        stable_prompt = agent._build_system_prompt_parts()["stable"]
    finally:
        session_db.close()

    assert agent.session_id == "xbot-constructor-contract"
    assert agent.enabled_toolsets == ["wechat"]
    assert stable_prompt.startswith("你叫小球子。")


def test_upgraded_hermes_auxiliary_client_contract():
    _ensure_hermes_import_path()
    from agent import auxiliary_client

    config = AgentConfig()
    config.llm.provider = "openai_compatible"
    config.llm.base_url = "https://example.invalid/v1"
    config.llm.api_key = "test-key"
    config.llm.model = "test-model"
    patched_names = (
        "_resolve_custom_runtime",
        "_resolve_auto",
        "resolve_provider_client",
        "get_text_auxiliary_client",
        "get_async_text_auxiliary_client",
        "_get_provider_chain",
        "_try_openrouter",
        "_try_nous",
    )
    originals = {name: getattr(auxiliary_client, name) for name in patched_names}
    try:
        _configure_hermes_auxiliary_client(auxiliary_client, config)
        client, model = auxiliary_client.resolve_provider_client("auto")
    finally:
        for name, value in originals.items():
            setattr(auxiliary_client, name, value)

    assert client is not None
    assert model == "test-model"


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
    from xbot.agent.tools.hermes_wechat import reset_send_context, send_text, set_send_context

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


@pytest.mark.anyio
async def test_qq_tool_preserves_adapter_message_ids_from_sender_result():
    _ensure_hermes_import_path()
    from xbot.agent.tools.hermes_qq import reset_send_context, send_text, set_send_context

    calls = []

    async def sender(**kwargs):
        calls.append(kwargs)
        return {"message_id": "reply-42", "message_ids": ["reply-41", "reply-42"]}

    token = set_send_context({
        "loop": __import__("asyncio").get_running_loop(),
        "sender": sender,
        "adapter": "qq",
        "conversation_id": "qq:c2c:user-1",
        "message_id": "incoming-1",
        "scope": "private",
    })
    try:
        result = json.loads(await anyio.to_thread.run_sync(send_text, {"text": "收到"}))
    finally:
        reset_send_context(token)

    assert result["message_id"] == "reply-42"
    assert result["message_ids"] == ["reply-41", "reply-42"]
    assert calls[-1]["conversation_id"] == "qq:c2c:user-1"


def test_wechat_tool_without_context_returns_error():
    _ensure_hermes_import_path()
    from xbot.agent.tools.hermes_wechat import send_text

    assert "error" in json.loads(send_text({"text": "hello"}))


@pytest.mark.anyio
async def test_wechat_extended_tools_build_metadata_and_route_targets():
    _ensure_hermes_import_path()
    from xbot.agent.tools.hermes_wechat import (
        reset_send_context,
        send_link,
        send_music_card,
        send_video,
        send_voice,
        set_send_context,
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


def test_member_tool_policy_allows_only_current_message_attachment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    media_dir = tmp_path / "data" / "wechat869" / "media"
    media_dir.mkdir(parents=True)
    current_attachment = media_dir / "current.docx"
    current_attachment.write_bytes(b"docx")
    unrelated_attachment = media_dir / "other.docx"
    unrelated_attachment.write_bytes(b"other")
    config = AgentConfig()
    policy = _tool_policy_for_source(
        config,
        "channel:wechat:wechat869:user:member",
        attachments=[{"local_path": "data/wechat869/media/current.docx"}],
    )

    assert _tool_policy_denial(
        "read_file", {"path": "data/wechat869/media/current.docx"}, policy,
    ) is None
    denial = _tool_policy_denial(
        "read_file", {"path": "data/wechat869/media/other.docx"}, policy,
    )
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
    assert _tool_policy_denial("weiban_query_account", {"email": "user@example.com"}, policy) is None
    assert _tool_policy_denial("weiban_search_knowledge", {"query": "怎么绑定"}, policy) is None
    assert _tool_policy_denial("artifact_create", {"format": "docx", "filename": "a.docx"}, policy) is None
    assert _tool_policy_denial("read_file", {"path": "a.txt"}, policy)
    assert _tool_policy_denial("terminal", {"command": "dir"}, policy)
    assert _tool_policy_denial("weiban_update_account", {"email": "user@example.com"}, policy)


def test_qq_guest_policy_allows_only_current_session_send_tools():
    policy = {"profile": "guest", "channel": "qq"}
    allowed = {
        "qq_send_text",
        "qq_send_markdown",
        "qq_send_image",
        "qq_send_file",
        "qq_send_voice",
        "qq_send_video",
        "qq_send_stream",
        "qq_input_notify",
    }
    for tool_name in allowed:
        assert _tool_policy_denial(tool_name, {}, policy) is None

    for tool_name in {"qq_recall", "qq_react", "wechat_send_text", "read_file"}:
        assert _tool_policy_denial(tool_name, {}, policy) == "当前 QQ guest 用户只能调用当前会话的 QQ 消息工具或微伴账号只读查询。"


def test_telegram_guest_policy_is_channel_scoped():
    policy = {"profile": "guest", "channel": "telegram"}
    for tool_name in {
        "telegram_send_text", "telegram_send_image", "telegram_send_file",
        "telegram_send_voice", "telegram_send_video",
    }:
        assert _tool_policy_denial(tool_name, {}, policy) is None
    for tool_name in {"qq_send_text", "wechat_send_text", "read_file"}:
        assert _tool_policy_denial(tool_name, {}, policy) == (
            "当前 Telegram guest 用户只能调用当前会话的 Telegram 消息工具或微伴账号只读查询。"
        )
    assert _tool_policy_denial("weiban_query_account", {"email": "user@example.com"}, policy) is None
    assert _tool_policy_denial("weiban_search_knowledge", {"query": "有哪些功能"}, policy) is None

    # Mutation tools remain available to explicitly elevated QQ profiles.
    assert _tool_policy_denial("qq_recall", {}, {"profile": "member", "channel": "qq"}) is None
    assert _tool_policy_denial("qq_react", {}, {"profile": "member", "channel": "qq"}) is None
    assert _tool_policy_denial("qq_recall", {}, {"profile": "admin", "channel": "qq"}) is None
    assert _tool_policy_denial("qq_react", {}, {"profile": "admin", "channel": "qq"}) is None


def test_public_weiban_knowledge_is_searchable_by_guest():
    from xbot.agent.tools.hermes_weiban_knowledge import search_knowledge

    result = json.loads(search_knowledge({"query": "绑定邀请码可以不加空格吗"}))

    assert result["success"] is True
    assert "绑定ABCD1234" in result["content"]


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
    monkeypatch.setattr("xbot.agent.hermes_runtime.sqlite3.sqlite_version_info", (3, 51, 3))
    monkeypatch.setattr("xbot.agent.hermes_runtime.sqlite3.sqlite_version", "3.51.3")
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

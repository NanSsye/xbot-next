from contextlib import asynccontextmanager

import pytest

from xbot.agent.runtime import AgentRuntime
from xbot.agent.llm import LLMResponse
from xbot.agent.tool_registry import ToolDefinition
from xbot.core.config import AgentConfig, AgentToolsetConfig, AgentWorkspaceConfig, PluginConfig, SkillConfig
from xbot.plugins.base import PluginBase
from xbot.plugins.manager import PluginManager
from xbot.skills.manager import SkillManager


class FakePluginRepository:
    def __init__(self):
        self.enabled = {}
        self.manifests = {}

    async def upsert_manifest(self, manifest, path, enabled):
        self.manifests[manifest.name] = (manifest, path)
        self.enabled.setdefault(manifest.name, enabled)

    async def set_enabled(self, name, enabled):
        self.enabled[name] = enabled
        return True

    async def get_enabled(self, name):
        return self.enabled.get(name)


class FakeSkillRepository(FakePluginRepository):
    pass


class FakeAgentRepository:
    def __init__(self):
        self.tasks = []
        self.finished = []
        self.events = []
        self.memories = []

    async def create_task(self, task_id, source, input_text):
        self.tasks.append((task_id, source, input_text))

    async def finish_task(self, result):
        self.finished.append(result)

    async def add_event(self, task_id, event_type, content):
        self.events.append((task_id, event_type, content))

    async def save_memory(self, item, **kwargs):
        self.memories.append((item, kwargs))


class FakeLLMProvider:
    def __init__(self, responses=None):
        self.messages = []
        self.responses = list(responses or ["LLM accepted the task."])

    async def complete(self, messages):
        self.messages.append(messages)
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model="fake-model",
            provider="fake",
            usage={"total_tokens": 3},
            raw_id="fake-response",
        )

    def status(self):
        return {"enabled": True, "provider": "fake", "model": "fake-model"}


@pytest.mark.anyio
async def test_plugin_manager_persists_manifest_and_enabled_state():
    repo = FakePluginRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    manager = PluginManager(PluginConfig(directory="plugins"), repository_provider=provider)
    await manager.load_all()
    assert "echo" in repo.manifests

    await manager.disable("echo")
    assert repo.enabled["echo"] is False

    await manager.enable("echo")
    assert repo.enabled["echo"] is True


@pytest.mark.anyio
async def test_skill_manager_persists_manifest_and_enabled_state():
    repo = FakeSkillRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    manager = SkillManager(SkillConfig(directory="skills"), repository_provider=provider)
    await manager.load_all()
    assert "code_assistant" in repo.manifests

    await manager.disable("code_assistant")
    assert repo.enabled["code_assistant"] is False

    await manager.enable("code_assistant")
    assert repo.enabled["code_assistant"] is True


@pytest.mark.anyio
async def test_agent_runtime_persists_task_event_and_memory():
    repo = FakeAgentRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    llm = FakeLLMProvider()
    runtime = AgentRuntime(
        AgentConfig(),
        plugins=None,
        skills=None,
        repository_provider=provider,
        llm_provider=llm,
    )
    result = await runtime.run_task("inspect project", source="test")

    assert repo.tasks[0][0] == result.task_id
    assert repo.finished[0].task_id == result.task_id
    assert result.output == "LLM accepted the task."
    assert llm.messages
    assert repo.memories
    assert any(event[1] == "llm.completed" for event in repo.events)
    assert any(event[1] == "task.completed" for event in repo.events)


@pytest.mark.anyio
async def test_agent_runtime_executes_filesystem_tool_and_audits(tmp_path):
    repo = FakeAgentRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        allow_file_write=True,
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, repository_provider=provider)

    write_result = await runtime.execute_tool(
        "filesystem.write_file",
        {"path": "notes.txt", "content": "hello agent"},
        source="test",
    )
    read_result = await runtime.execute_tool(
        "filesystem.read_file",
        {"path": "notes.txt"},
        task_id=write_result.task_id,
        source="test",
    )

    assert write_result.status == "completed"
    assert read_result.output == "hello agent"
    assert any(event[1] == "tool.started" for event in repo.events)
    assert any(event[1] == "tool.completed" for event in repo.events)


@pytest.mark.anyio
async def test_agent_runtime_caches_read_only_tool_results_and_clears_on_write(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("hello cache", encoding="utf-8")
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        allow_file_write=True,
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)
    original_execute = runtime.executor.execute
    calls = []

    async def counting_execute(name, payload):
        calls.append(name)
        return await original_execute(name, payload)

    runtime.executor.execute = counting_execute

    first = await runtime.execute_tool("filesystem.read_file", {"path": "notes.txt"})
    second = await runtime.execute_tool("filesystem.read_file", {"path": "notes.txt"})
    await runtime.execute_tool(
        "filesystem.write_file",
        {"path": "notes.txt", "content": "updated cache"},
    )
    third = await runtime.execute_tool("filesystem.read_file", {"path": "notes.txt"})

    assert first.output == "hello cache"
    assert second.output == "hello cache"
    assert third.output == "updated cache"
    assert calls == ["filesystem.read_file", "filesystem.write_file", "filesystem.read_file"]


@pytest.mark.anyio
async def test_agent_runtime_registers_skill_tools_with_schema():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    tools = {item["name"]: item for item in runtime.tools.list_tools()}

    assert "skill.list" in tools
    assert "skill.describe" in tools
    assert "skill.run" in tools
    assert tools["filesystem.list_dir"]["input_schema"]["properties"]["path"]["type"] == "string"
    assert tools["filesystem.list_dir"]["toolset"] == "filesystem"
    assert tools["filesystem.list_dir"]["cacheable"] is True
    assert tools["skill.run"]["source"] == "skill"
    assert "action" in tools["skill.run"]["input_schema"]["required"]


@pytest.mark.anyio
async def test_agent_runtime_uses_tool_metadata_for_cache_invalidation(tmp_path):
    target = tmp_path / "project.txt"
    target.write_text("one", encoding="utf-8")
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)

    first = await runtime.execute_tool("filesystem.read_file", {"path": "project.txt"})
    second = await runtime.execute_tool("filesystem.read_file", {"path": "project.txt"})
    await runtime.execute_tool(
        "filesystem.write_file",
        {"path": "project.txt", "content": "two"},
    )
    third = await runtime.execute_tool("filesystem.read_file", {"path": "project.txt"})

    assert first.output == "one"
    assert second.output == "one"
    assert third.output == "two"


def test_agent_toolset_visibility_filters_prompt_tools():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    prompt = runtime._agent_system_prompt(source="channel:wechat:wechat869:group:123@chatroom")

    assert '"toolset": "shell"' not in prompt
    assert '"toolset": "browser"' not in prompt
    assert '"toolset": "database"' not in prompt
    assert '"toolset": "git"' not in prompt
    assert "filesystem.write_file" not in prompt
    assert "filesystem.delete_path" not in prompt
    assert '"toolset": "filesystem"' in prompt


def test_agent_admin_prompt_includes_extended_tool_providers():
    runtime = AgentRuntime(
        AgentConfig(
            mode="admin",
            admin_mode_allowed=True,
            toolsets=AgentToolsetConfig(admin=["core"]),
        ),
        plugins=None,
        skills=None,
    )
    prompt = runtime._agent_system_prompt(source="api")

    assert "browser.screenshot_url" in prompt
    assert "git.status" in prompt
    assert "github.repo_info" in prompt
    assert "skill.run" in prompt


@pytest.mark.anyio
async def test_agent_registers_plugin_tool_provider():
    class FakePlugin(PluginBase):
        name = "fake"

        def agent_tools(self):
            async def handler(payload):
                return {"ok": payload.get("value")}

            return [
                ToolDefinition(
                    name="plugin.fake_echo",
                    description="Echo a value from a plugin tool.",
                    risk_level="read",
                    handler=handler,
                    toolset="plugin",
                    source="plugin",
                    cacheable=True,
                )
            ]

    class FakePlugins:
        def iter_agent_tools(self):
            return [("fake", list(FakePlugin().agent_tools()))]

    runtime = AgentRuntime(AgentConfig(), plugins=FakePlugins(), skills=None)
    await runtime.start()
    tool = runtime.tools.get("plugin.fake_echo")

    assert tool is not None
    assert tool.source == "plugin:fake"
    assert tool.toolset == "plugin"
    result = await runtime.execute_tool("plugin.fake_echo", {"value": "x"})
    assert result.output == {"ok": "x"}


@pytest.mark.anyio
async def test_database_tool_rejects_mutating_sql(tmp_path):
    from xbot.agent.tools.database_provider import register_database_tools

    class FakeStorage:
        session_factory = None

    storage = FakeStorage()
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    register_database_tools(runtime.tools, storage=storage)

    result = await runtime.execute_tool("database.query", {"sql": "delete from users"})

    assert result.status == "denied"
    assert "read-only" in result.error


def test_agent_system_prompt_includes_current_time():
    runtime = AgentRuntime(AgentConfig(timezone="Asia/Shanghai"), plugins=None, skills=None)
    prompt = runtime._agent_system_prompt()

    assert "Current runtime time" in prompt
    assert "timezone: Asia/Shanghai" in prompt
    assert "date:" in prompt


def test_agent_system_prompt_falls_back_when_timezone_is_missing():
    runtime = AgentRuntime(AgentConfig(timezone="Missing/Timezone"), plugins=None, skills=None)
    prompt = runtime._agent_system_prompt()

    assert "timezone: UTC" in prompt
    assert "date:" in prompt


def test_agent_static_prompt_cache_keeps_dynamic_time_separate():
    runtime = AgentRuntime(AgentConfig(timezone="Asia/Shanghai"), plugins=None, skills=None)
    prompt = runtime._agent_system_prompt()

    assert "Current runtime time" in prompt
    assert runtime._static_prompt_cache is not None
    assert "Current runtime time" not in runtime._static_prompt_cache[1]


def test_agent_current_state_detection_uses_channel_content_only():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    channel_input = (
        "Channel message received.\n"
        "conversation_summaries:\n- none\n"
        "recent_conversation_messages:\n- none\n"
        "content: 打开浏览器截图发群里\n"
        "If the content asks about real project files, directories, plugins, skills, config, or runtime state, use tools before answering."
    )

    assert runtime._request_requires_current_state_tool(channel_input) is False


@pytest.mark.anyio
async def test_agent_runtime_stops_after_repeated_missing_tool_calls(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"final":"正在查看 skill 目录..."}',
            '{"final":"正在查看 skill 目录..."}',
            '{"final":"正在查看 skill 目录..."}',
            '{"final":"正在查看 skill 目录..."}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("列出skill目录所有skill名称", source="test")

    assert "连续没有发起工具调用" in result.output
    assert len(llm.messages) == 4


@pytest.mark.anyio
async def test_agent_runtime_denies_shell_by_default(tmp_path):
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        allow_shell=False,
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)

    result = await runtime.execute_tool("shell.exec", {"command": "echo denied"})

    assert result.status == "denied"
    assert "Shell execution is disabled" in result.error


@pytest.mark.anyio
async def test_agent_runtime_reports_disabled_llm():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)

    result = await runtime.run_task("hello", source="test")

    assert result.status == "completed"
    assert "LLM provider is not available" in result.output


@pytest.mark.anyio
async def test_agent_runtime_plans_tool_calls_and_returns_final_answer(tmp_path):
    repo = FakeAgentRepository()
    target = tmp_path / "project.txt"
    target.write_text("xbot project", encoding="utf-8")

    @asynccontextmanager
    async def provider():
        yield repo

    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"filesystem.read_file","payload":{"path":"project.txt"}}]}',
            '{"final":"文件内容是 xbot project"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(
        config,
        plugins=None,
        skills=None,
        repository_provider=provider,
        llm_provider=llm,
    )

    result = await runtime.run_task("读取 project.txt", source="test")

    assert result.output == "文件内容是 xbot project"
    assert len(llm.messages) == 2
    assert any(event[1] == "tool.completed" for event in repo.events)
    assert any(event[1] == "llm.completed" for event in repo.events)


@pytest.mark.anyio
async def test_agent_runtime_parses_multiple_tool_call_json_blocks(tmp_path):
    (tmp_path / "skills").mkdir()
    llm = FakeLLMProvider(
        responses=[
            (
                '{"tool_calls":[{"tool":"filesystem.list_dir","payload":{"path":"skills"}}]}\n'
                '{"tool_calls":[{"tool":"filesystem.list_dir","payload":{"path":"."}}]}'
            ),
            '{"final":"完成"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("检查目录", source="test")

    assert result.output == "完成"
    assert len(llm.messages) == 2


@pytest.mark.anyio
async def test_agent_runtime_hides_empty_tool_calls_from_final_output():
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[]}\n\n我是 xbot 助手，有什么可以帮您？',
        ]
    )
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("你好", source="test")

    assert result.output == "我是 xbot 助手，有什么可以帮您？"
    assert "tool_calls" not in result.output


@pytest.mark.anyio
async def test_agent_runtime_never_returns_tool_call_json_as_final_output():
    llm = FakeLLMProvider(
        responses=[
            (
                '{"tool_calls":[]}\n'
                '{"tool_calls":[{"tool":"filesystem.list_dir","payload":{"path":"skills"}}]}'
            ),
            '{"final":"工具调用已处理"}',
        ]
    )
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("你好", source="test")

    assert result.output == "工具调用已处理"
    assert "tool_calls" not in result.output


@pytest.mark.anyio
async def test_agent_runtime_reprompts_after_empty_final_and_then_uses_tool(tmp_path):
    target_dir = tmp_path / "skills"
    target_dir.mkdir()
    (target_dir / "code_assistant").mkdir()
    (target_dir / "wechat").mkdir()
    llm = FakeLLMProvider(
        responses=[
            '{"final":""}',
            '{"tool_calls":[{"tool":"filesystem.list_dir","payload":{"path":"skills"}}]}',
            '{"final":"当前 skill 有 code_assistant、wechat"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("列出skill目录所有skill名称", source="test")

    assert result.output == "当前 skill 有 code_assistant、wechat"
    assert len(llm.messages) == 3


@pytest.mark.anyio
async def test_agent_runtime_reprompts_after_premature_final_and_then_uses_tool(tmp_path):
    target_dir = tmp_path / "skills"
    target_dir.mkdir()
    (target_dir / "code_assistant").mkdir()
    llm = FakeLLMProvider(
        responses=[
            '{"final":"正在查看 skill 目录..."}',
            '{"tool_calls":[{"tool":"filesystem.list_dir","payload":{"path":"skills"}}]}',
            '{"final":"当前 skill 有 code_assistant"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("列出skill目录所有skill名称", source="test")

    assert result.output == "当前 skill 有 code_assistant"
    assert len(llm.messages) == 3

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import anyio
import pytest

from xbot.agent.planner import AgentPlanner
from xbot.agent.runtime import AgentRuntime
from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.llm import LLMMessage, LLMResponse
from xbot.agent.tools.skill_provider import SkillToolProvider
from xbot.agent.tool_registry import ToolDefinition
from xbot.core.config import (
    AgentConfig,
    AgentLLMConfig,
    AgentToolsetConfig,
    AgentWorkspaceConfig,
    PluginConfig,
    SkillConfig,
)
from xbot.messaging.models import Message, Reply
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
        self.background_tasks = {}

    async def create_task(self, task_id, source, input_text):
        self.tasks.append((task_id, source, input_text))

    async def finish_task(self, result):
        self.finished.append(result)

    async def add_event(self, task_id, event_type, content):
        self.events.append((task_id, event_type, content))

    async def save_memory(self, item, **kwargs):
        self.memories.append((item, kwargs))

    async def upsert_background_task(self, item):
        self.background_tasks[item.id] = item.model_copy(deep=True)

    async def get_background_task(self, task_id):
        return self.background_tasks.get(task_id)

    async def list_background_tasks(self, limit=50):
        return list(self.background_tasks.values())[-limit:]


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


class FakeStreamingLLMProvider(FakeLLMProvider):
    def __init__(self, chunks):
        super().__init__(responses=["".join(chunks)])
        self.chunks = list(chunks)

    async def stream(self, messages):
        self.messages.append(messages)
        for chunk in self.chunks:
            yield chunk


class FakeFailingStreamingLLMProvider(FakeLLMProvider):
    async def stream(self, messages):
        self.messages.append(("stream", messages))
        raise RuntimeError("stream unsupported")
        yield ""


class FakeFlakyLLMProvider(FakeLLMProvider):
    def __init__(self, outcomes):
        super().__init__(responses=[])
        self.outcomes = list(outcomes)

    async def complete(self, messages):
        self.messages.append(messages)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResponse(
            content=outcome,
            model="fake-model",
            provider="fake",
            usage={"total_tokens": 3},
            raw_id="fake-response",
        )


@pytest.mark.anyio
async def test_agent_runtime_streams_terminal_plain_text_without_persisting_deltas():
    repo = FakeAgentRepository()

    @asynccontextmanager
    async def provider():
        yield repo

    llm = FakeStreamingLLMProvider(["你好，", "我可以帮你。"])
    runtime = AgentRuntime(
        AgentConfig(),
        plugins=None,
        skills=None,
        repository_provider=provider,
        llm_provider=llm,
    )
    events = []
    runtime.subscribe_events(lambda event: events.append(event))

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="你好")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content == "你好，我可以帮你。"
    assert [event.type for event in events] == ["llm.delta"]
    assert events[0].content["text"] == "你好，我可以帮你。"
    assert repo.events == []


@pytest.mark.anyio
async def test_agent_runtime_retries_transient_llm_failure():
    llm = FakeFlakyLLMProvider([TimeoutError("first timeout"), "retry ok"])
    runtime = AgentRuntime(
        AgentConfig(llm=AgentLLMConfig(max_attempts=2, retry_backoff_seconds=0)),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )
    events = []
    runtime.subscribe_events(lambda event: events.append(event))

    output = await runtime._run_llm("task-1", "你好")

    assert output == "retry ok"
    assert len(llm.messages) == 2
    assert [event.type for event in events].count("llm.retry") == 1
    retry_event = next(event for event in events if event.type == "llm.retry")
    assert retry_event.content["attempt"] == 1
    assert retry_event.content["max_attempts"] == 2


@pytest.mark.anyio
async def test_agent_runtime_returns_timeout_after_retry_attempts_exhausted():
    llm = FakeFlakyLLMProvider([TimeoutError("one"), TimeoutError("two")])
    runtime = AgentRuntime(
        AgentConfig(llm=AgentLLMConfig(max_attempts=2, retry_backoff_seconds=0)),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )

    output = await runtime._run_llm("task-1", "你好")

    assert output == "LLM provider call timed out, please try again later."
    assert len(llm.messages) == 2


@pytest.mark.anyio
async def test_agent_runtime_deduplicates_overlapping_stream_chunks():
    llm = FakeStreamingLLMProvider(["你好，我可以", "我可以帮你。", "帮你。"])
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)
    events = []
    runtime.subscribe_events(lambda event: events.append(event))

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="你好")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content == "你好，我可以帮你。"
    assert "".join(event.content["text"] for event in events) == "你好，我可以帮你。"


@pytest.mark.anyio
async def test_agent_runtime_skips_stream_chunk_already_in_current_text():
    llm = FakeStreamingLLMProvider(["您好！请问您想要问什么呢？", "想要问什么呢？"])
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="你还")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content == "您好！请问您想要问什么呢？"


@pytest.mark.anyio
async def test_agent_runtime_deduplicates_cumulative_stream_chunks():
    llm = FakeStreamingLLMProvider(["你好，", "你好，我可以", "你好，我可以帮你。"])
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="你好")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content == "你好，我可以帮你。"


@pytest.mark.anyio
async def test_agent_runtime_deduplicates_restarted_stream_suffix():
    first = "你好！有什么我可以帮你的吗？无论是代码问题、项目调试、文件操作，还是其他开发相关的事情，随时告诉我。"
    duplicate_tail = "有什么我可以帮你的吗？无论是代码问题、项目调试、文件操作，还是其他开发相关的事情，随时告诉我。"
    llm = FakeStreamingLLMProvider([first, duplicate_tail])
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="hi")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content == first


@pytest.mark.anyio
async def test_agent_runtime_falls_back_when_terminal_stream_fails_before_chunks():
    llm = FakeFailingStreamingLLMProvider(responses=["fallback ok"])
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="你好")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content == "fallback ok"


@pytest.mark.anyio
async def test_agent_runtime_does_not_stream_tool_call_json_to_terminal():
    llm = FakeStreamingLLMProvider(['{"tool_calls":', '[{"tool":"filesystem.list_dir"}]}'])
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None, llm_provider=llm)
    events = []
    runtime.subscribe_events(lambda event: events.append(event))

    response = await runtime._complete_llm(
        [LLMMessage(role="user", content="列目录")],
        task_id="task-1",
        iteration=0,
        source="terminal:local:s1",
    )

    assert response.content.startswith('{"tool_calls"')
    assert events == []


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
async def test_skill_manager_skips_agent_container_but_loads_agent_owned_skill(tmp_path):
    skills_root = tmp_path / "skills"
    (skills_root / ".agent" / ".templates").mkdir(parents=True)
    agent_skill = skills_root / ".agent" / "debug-workflow"
    agent_skill.mkdir(parents=True)
    (agent_skill / "skill.toml").write_text(
        """
name = "debug-workflow"
version = "0.1.0"
description = "Debug workflow"
enabled = true
""",
        encoding="utf-8",
    )
    (agent_skill / "SKILL.md").write_text("# Debug Workflow\n", encoding="utf-8")

    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    await manager.load_all()

    loaded = {item["name"] for item in manager.list_skills()}
    assert loaded == {"debug-workflow"}


@pytest.mark.anyio
async def test_skill_manage_creates_patches_archives_and_restores_agent_skill(tmp_path):
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))

    created = await manager.manage(
        {
            "action": "create",
            "name": "debug-workflow",
            "description": "Reusable debugging workflow",
            "content": "# Debug Workflow\n\nFirst inspect logs.",
        }
    )
    patched = await manager.manage(
        {
            "action": "patch",
            "name": "debug-workflow",
            "old_text": "First inspect logs.",
            "new_text": "First inspect logs, then reproduce.",
        }
    )
    await manager.manage({"action": "pin", "name": "debug-workflow"})

    with pytest.raises(ValueError):
        await manager.manage({"action": "archive", "name": "debug-workflow"})

    await manager.manage({"action": "unpin", "name": "debug-workflow"})
    archived = await manager.manage({"action": "archive", "name": "debug-workflow"})
    restored = await manager.manage({"action": "restore", "name": "debug-workflow"})
    usage = await manager.manage({"action": "usage"})

    assert created["success"] is True
    assert patched["success"] is True
    assert archived["success"] is True
    assert restored["success"] is True
    assert manager.get_instructions("debug-workflow")
    assert usage["usage"]["debug-workflow"]["created_by"] == "agent"
    assert usage["usage"]["debug-workflow"]["state"] == "active"


@pytest.mark.anyio
async def test_skill_manager_lists_agent_owned_skill_usage(tmp_path):
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))

    await manager.manage(
        {
            "action": "create",
            "name": "review-checklist",
            "description": "Reusable review checklist",
            "content": "# Review Checklist\n\nInspect tests.",
        }
    )
    await manager.record_use("review-checklist", "view")
    await manager.manage({"action": "pin", "name": "review-checklist"})

    items = manager.list_agent_owned_skills()

    assert items == [
        {
            "name": "review-checklist",
            "state": "active",
            "pinned": True,
            "path": str(skills_root / ".agent" / "review-checklist"),
            "use_count": 0,
            "view_count": 1,
            "patch_count": 0,
            "created_at": items[0]["created_at"],
            "last_use_at": None,
            "last_view_at": items[0]["last_view_at"],
            "last_patch_at": None,
            "archived_at": None,
        }
    ]
    assert manager.agent_usage_snapshot()["review-checklist"]["created_by"] == "agent"


@pytest.mark.anyio
async def test_skill_curator_archives_stale_agent_skill(tmp_path):
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    manager.config.curator_stale_after_days = 1
    manager.config.curator_archive_after_days = 2
    await manager.manage(
        {
            "action": "create",
            "name": "old-workflow",
            "description": "Old workflow",
            "content": "# Old Workflow\n\nOld steps.",
        }
    )
    usage = manager._load_usage()
    usage["old-workflow"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    manager._save_usage(usage)

    result = await manager.run_curator()

    assert result["archived"] == 1
    assert (skills_root / ".agent" / ".archive" / "old-workflow").exists()
    assert manager._load_usage()["old-workflow"]["state"] == "archived"


@pytest.mark.anyio
async def test_skill_curator_report_is_dry_run_and_detects_duplicates(tmp_path):
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    await manager.manage(
        {
            "action": "create",
            "name": "debug-python",
            "description": "Debug Python workflow",
            "content": "# Debug Python\n\nInspect logs and reproduce Python failures.",
        }
    )
    await manager.manage(
        {
            "action": "create",
            "name": "python-debugging",
            "description": "Debug Python workflow",
            "content": "# Python Debugging\n\nInspect logs and reproduce Python failures.",
        }
    )
    usage = manager._load_usage()
    usage["debug-python"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    manager._save_usage(usage)
    manager.config.curator_stale_after_days = 1
    manager.config.curator_archive_after_days = 30

    report = manager.build_curator_report()

    assert report["dry_run"] is True
    assert (skills_root / ".agent" / "debug-python").exists()
    assert any(item["action"] == "mark_stale" for item in report["proposals"])
    assert any(item["action"] == "merge" for item in report["proposals"])
    assert (skills_root / ".agent" / ".curator" / "latest.json").exists()


@pytest.mark.anyio
async def test_skill_curator_applies_selected_report_proposals(tmp_path):
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    await manager.manage(
        {
            "action": "create",
            "name": "old-cleanup",
            "description": "Old cleanup",
            "content": "# Old Cleanup\n\nCleanup steps.",
        }
    )
    usage = manager._load_usage()
    usage["old-cleanup"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    manager._save_usage(usage)
    manager.config.curator_archive_after_days = 1
    report = manager.build_curator_report()
    archive_id = next(item["id"] for item in report["proposals"] if item["action"] == "archive")

    result = await manager.apply_curator_report(proposal_ids=[archive_id])

    assert result["results"][0]["status"] == "applied"
    assert not (skills_root / ".agent" / "old-cleanup").exists()
    assert (skills_root / ".agent" / ".archive" / "old-cleanup").exists()


@pytest.mark.anyio
async def test_agent_runtime_curator_report_uses_llm_suggestions(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            (
                '{"proposals":[{"action":"pin","target":"keep-me",'
                '"reason":"经常需要保留","confidence":0.9}]}'
            )
        ]
    )
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    await manager.manage(
        {
            "action": "create",
            "name": "keep-me",
            "description": "Important workflow",
            "content": "# Keep Me\n\nImportant steps.",
        }
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.llm.enabled = True
    runtime = AgentRuntime(config, plugins=None, skills=manager, llm_provider=llm)

    report = await runtime.generate_curator_report(use_llm=True)

    assert any(
        item["action"] == "pin" and item["source"] == "llm"
        for item in report["proposals"]
    )
    assert llm.messages


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
async def test_agent_runtime_keeps_short_term_history_per_terminal_session(tmp_path):
    llm = FakeLLMProvider(responses=['{"final":"你叫小明。"}', '{"final":"你叫小明。"}'])
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)
    source = "terminal:local:session-a"

    await runtime.run_task("我叫小明", source=source)
    await runtime.run_task("我叫什么？", source=source)

    second_messages = llm.messages[1]
    assert [message.role for message in second_messages[:4]] == ["system", "user", "assistant", "user"]
    assert second_messages[1].content == "我叫小明"
    assert second_messages[2].content == "你叫小明。"
    assert second_messages[3].content == "我叫什么？"


@pytest.mark.anyio
async def test_agent_runtime_short_term_history_is_scoped_by_source(tmp_path):
    llm = FakeLLMProvider(responses=['{"final":"记住了。"}', '{"final":"不知道。"}'])
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    await runtime.run_task("我叫小明", source="terminal:local:session-a")
    await runtime.run_task("我叫什么？", source="terminal:local:session-b")

    second_messages = llm.messages[1]
    assert [message.role for message in second_messages] == ["system", "user"]
    assert second_messages[1].content == "我叫什么？"


@pytest.mark.anyio
async def test_agent_runtime_compresses_old_short_term_history(tmp_path):
    llm = FakeLLMProvider(responses=['{"final":"一"}', '{"final":"二"}', '{"final":"三"}'])
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.short_term_recent_turns = 1
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)
    source = "terminal:local:session-a"

    await runtime.run_task("第一轮", source=source)
    await runtime.run_task("第二轮", source=source)
    await runtime.run_task("第三轮", source=source)

    third_messages = llm.messages[2]
    assert [message.role for message in third_messages] == ["system", "system", "user", "assistant", "user"]
    assert "Compressed earlier turns" in third_messages[1].content
    assert "第一轮" in third_messages[1].content
    assert [message.content for message in third_messages[2:]] == ["第二轮", "二", "第三轮"]


@pytest.mark.anyio
async def test_agent_runtime_compresses_short_term_history_by_token_budget(tmp_path):
    llm = FakeLLMProvider(responses=['{"final":"一"}', '{"final":"二"}', '{"final":"三"}'])
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.short_term_recent_turns = 0
    config.memory.short_term_max_tokens = 4
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)
    source = "terminal:local:session-a"

    await runtime.run_task("第一轮很长", source=source)
    await runtime.run_task("第二轮也长", source=source)
    await runtime.run_task("第三轮", source=source)

    third_messages = llm.messages[2]
    assert third_messages[1].role == "system"
    assert "Compressed earlier turns" in third_messages[1].content
    assert third_messages[-1].content == "第三轮"


@pytest.mark.anyio
async def test_agent_runtime_short_term_history_stores_actual_terminal_content(tmp_path):
    from xbot.cli.chat import build_terminal_agent_input

    llm = FakeLLMProvider(responses=['{"final":"记住了。"}', '{"final":"你叫小明。"}'])
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)
    source = "terminal:local:session-a"

    await runtime.run_task(
        build_terminal_agent_input("我叫小明", session_id="session-a", cwd=tmp_path),
        source=source,
    )
    await runtime.run_task(
        build_terminal_agent_input("我叫什么？", session_id="session-a", cwd=tmp_path),
        source=source,
    )

    second_messages = llm.messages[1]
    assert second_messages[1].content == "我叫小明"
    assert second_messages[-1].content.startswith("Terminal message received.")


@pytest.mark.anyio
async def test_agent_runtime_exposes_curated_memory_tools(tmp_path):
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.directory = str(tmp_path / "memories")
    runtime = AgentRuntime(config, plugins=None, skills=None)

    added = await runtime.execute_tool(
        "memory.add",
        {"target": "user", "content": "用户喜欢直接、简洁的中文回复。"},
    )
    read = await runtime.execute_tool("memory.read", {"target": "user"})

    assert added.status == "completed"
    assert read.output["entries"] == ["用户喜欢直接、简洁的中文回复。"]
    assert (tmp_path / "memories" / "USER.md").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_agent_runtime_exposes_wiki_manage_tool(tmp_path):
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.wiki.directory = str(tmp_path / "wiki")
    runtime = AgentRuntime(config, plugins=None, skills=None)

    result = await runtime.execute_tool(
        "wiki.manage",
        {
            "action": "write_page",
            "wiki": "xbot",
            "page": "architecture",
            "content": "# Architecture\n\nUses Markdown wiki.",
        },
    )
    query = await runtime.execute_tool(
        "wiki.manage",
        {"action": "query", "wiki": "xbot", "query": "Markdown wiki"},
    )

    assert result.status == "completed"
    assert result.output["success"] is True
    assert query.status == "completed"
    assert query.output["matches"][0]["page"] == "architecture"


@pytest.mark.anyio
async def test_agent_runtime_injects_memory_snapshot_at_start(tmp_path):
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()
    (memory_dir / "USER.md").write_text("用户讨厌重复解释。", encoding="utf-8")
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.directory = str(memory_dir)
    runtime = AgentRuntime(config, plugins=None, skills=None)

    prompt = runtime._agent_system_prompt(source="api")

    assert "USER PROFILE" in prompt
    assert "用户讨厌重复解释。" in prompt


def test_memory_store_creates_templates_without_injecting_template_text(tmp_path):
    from xbot.agent.memory import MemoryStore

    memory = MemoryStore(tmp_path / "memories")

    assert (tmp_path / "memories" / "MEMORY.md").exists()
    assert (tmp_path / "memories" / "USER.md").exists()
    assert memory.read_curated("memory")["entries"] == []
    assert memory.read_curated("user")["entries"] == []
    assert memory.format_for_system_prompt() == ""


@pytest.mark.anyio
async def test_agent_runtime_starts_background_memory_review(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"final":"我会按你的要求简洁回复。"}',
            (
                '{"tool_calls":[{"tool":"memory.add","payload":{"target":"user",'
                '"content":"用户偏好简洁直接的中文回复。"}}]}'
            ),
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.directory = str(tmp_path / "memories")
    config.memory.review_interval = 1
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("以后回复简洁一点", source="terminal:local:test")

    for _ in range(50):
        reviews = [item for item in runtime.background.list() if item.kind == "memory_review"]
        if reviews and reviews[0].status == "completed":
            break
        await anyio.sleep(0.02)

    assert result.output == "我会按你的要求简洁回复。"
    assert "用户偏好简洁直接的中文回复。" in (tmp_path / "memories" / "USER.md").read_text(
        encoding="utf-8"
    )
    assert reviews[0].result["results"][0]["tool"] == "memory.add"


@pytest.mark.anyio
async def test_background_memory_review_skips_non_memory_tools(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"final":"完成。"}',
            '{"tool_calls":[{"tool":"shell.exec","payload":{"command":"echo bad"}}]}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.directory = str(tmp_path / "memories")
    config.memory.review_interval = 1
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    await runtime.run_task("做完后复盘", source="terminal:local:test")

    for _ in range(50):
        reviews = [item for item in runtime.background.list() if item.kind == "memory_review"]
        if reviews and reviews[0].status == "completed":
            break
        await anyio.sleep(0.02)

    assert reviews[0].result["results"][0]["status"] == "skipped"
    assert not (tmp_path / "bad").exists()


@pytest.mark.anyio
async def test_background_review_can_create_agent_owned_skill(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"final":"完成。"}',
            (
                '{"tool_calls":[{"tool":"skill.manage","payload":{"action":"create",'
                '"name":"terminal-display-tuning","description":"Tune terminal display",'
                '"content":"# Terminal Display Tuning\\n\\nKeep terminal output compact."}}]}'
            ),
        ]
    )
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.directory = str(tmp_path / "memories")
    config.memory.review_interval = 1
    runtime = AgentRuntime(config, plugins=None, skills=manager, llm_provider=llm)

    await runtime.run_task("终端显示优化完成", source="terminal:local:test")

    for _ in range(50):
        reviews = [item for item in runtime.background.list() if item.kind == "memory_review"]
        if reviews and reviews[0].status == "completed":
            break
        await anyio.sleep(0.02)

    skill_path = skills_root / ".agent" / "terminal-display-tuning" / "SKILL.md"
    assert skill_path.exists()
    assert manager.get_instructions("terminal-display-tuning")
    assert reviews[0].result["results"][0]["tool"] == "skill.manage"


@pytest.mark.anyio
async def test_agent_runtime_flushes_memory_on_boundary(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"final":"完成。"}',
            '{"tool_calls":[{"tool":"memory.add","payload":{"target":"user","content":"用户要求边界前保存记忆。"}}]}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.directory = str(tmp_path / "memories")
    config.memory.review_interval = 0
    config.memory.flush_min_turns = 1
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    await runtime.run_task("请记住边界前保存", source="terminal:local:test")
    result = await runtime.flush_memory(reason="test")

    assert result["results"][0]["tool"] == "memory.add"
    assert "用户要求边界前保存记忆。" in (tmp_path / "memories" / "USER.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.anyio
async def test_agent_runtime_runs_curator_on_interval(tmp_path):
    llm = FakeLLMProvider(responses=['{"final":"完成。"}'])
    skills_root = tmp_path / "skills"
    manager = SkillManager(SkillConfig(directory=str(skills_root)))
    manager.config.curator_interval_turns = 1
    manager.config.curator_archive_after_days = 1
    await manager.manage(
        {
            "action": "create",
            "name": "auto-archive-me",
            "description": "Old workflow",
            "content": "# Old Workflow\n\nOld steps.",
        }
    )
    usage = manager._load_usage()
    usage["auto-archive-me"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    manager._save_usage(usage)
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    config.memory.review_interval = 0
    runtime = AgentRuntime(config, plugins=None, skills=manager, llm_provider=llm)

    await runtime.run_task("触发 curator", source="terminal:local:test")

    for _ in range(50):
        tasks = [item for item in runtime.background.list() if item.kind == "curator"]
        if tasks and tasks[0].status == "completed":
            break
        await anyio.sleep(0.02)

    assert tasks[0].result["archived"] == 1
    assert (skills_root / ".agent" / ".archive" / "auto-archive-me").exists()


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
async def test_agent_registers_plugin_manifest_tool_provider(tmp_path):
    plugin_dir = tmp_path / "manifest_tool"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(
        '''
name = "manifest_tool"
version = "0.1.0"
entry = "main:ManifestToolPlugin"
enabled = true

[[agent_tools]]
name = "plugin.manifest_echo"
handler = "echo_tool"
description = "Echo through manifest-declared tool."
risk_level = "read"
toolset = "plugin"
cacheable = true
'''.strip(),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        '''
from xbot.plugins.base import PluginBase


class ManifestToolPlugin(PluginBase):
    async def echo_tool(self, payload):
        return {"echo": payload.get("text")}
'''.strip(),
        encoding="utf-8",
    )
    plugins = PluginManager(PluginConfig(directory=str(tmp_path)))
    await plugins.load_all()
    runtime = AgentRuntime(AgentConfig(), plugins=plugins, skills=None)
    await runtime.start()

    tool = runtime.tools.get("plugin.manifest_echo")
    result = await runtime.execute_tool("plugin.manifest_echo", {"text": "hello"})

    assert tool is not None
    assert tool.source == "plugin:manifest_tool"
    assert tool.metadata["plugin"] == "manifest_tool"
    assert result.output == {"echo": "hello"}


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


def test_second_stage_provider_tools_are_registered():
    from xbot.agent.tools.database_provider import register_database_tools

    class FakeStorage:
        session_factory = None

    runtime = AgentRuntime(AgentConfig(mode="admin", admin_mode_allowed=True), plugins=None, skills=None)
    register_database_tools(runtime.tools, storage=FakeStorage())
    tools = {item["name"]: item for item in runtime.tools.list_tools()}

    assert tools["browser.run_actions"]["toolset"] == "browser"
    assert tools["database.schema"]["toolset"] == "database"
    assert tools["github.issue_list"]["source"] == "github"
    assert tools["github.issue_create"]["risk_level"] == "write"
    assert tools["github.pr_view"]["toolset"] == "git"
    assert tools["browser.session_open"]["metadata"]["session_persistent"] is True
    assert tools["browser.session_actions"]["metadata"]["background_candidate"] is True
    assert tools["skill.run"]["metadata"]["background_candidate"] is True
    assert tools["github.graphql"]["source"] == "github"
    assert tools["github.workflow_list"]["toolset"] == "git"
    assert tools["github.run_logs"]["risk_level"] == "read"
    assert tools["github.run_logs"]["metadata"]["background_candidate"] is True
    assert tools["github.run_rerun"]["risk_level"] == "write"
    assert tools["environment.snapshot"]["toolset"] == "environment"
    assert tools["environment.which"]["cacheable"] is True
    assert tools["task.start"]["toolset"] == "task"


@pytest.mark.anyio
async def test_database_schema_uses_sqlalchemy_inspector(monkeypatch):
    from xbot.agent.tools import database_provider

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "sqlite"})()

    class FakeSyncSession:
        def connection(self):
            return FakeConnection()

    class FakeInspector:
        default_schema_name = "main"

        def get_schema_names(self):
            return ["main"]

        def get_table_names(self, schema=None):
            assert schema == "main"
            return ["users"]

        def get_columns(self, table_name, schema=None):
            assert table_name == "users"
            return [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR", "nullable": True, "default": None},
            ]

        def get_pk_constraint(self, table_name, schema=None):
            return {"name": "pk_users", "constrained_columns": ["id"]}

        def get_indexes(self, table_name, schema=None):
            return [{"name": "ix_users_name", "column_names": ["name"], "unique": False}]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def run_sync(self, fn):
            return fn(FakeSyncSession())

    class FakeStorage:
        def session_factory(self):
            return FakeSession()

    monkeypatch.setattr(database_provider, "inspect", lambda connection: FakeInspector())

    result = await database_provider._schema({}, storage=FakeStorage())

    assert result["dialect"] == "sqlite"
    assert result["schema"] == "main"
    assert result["tables"][0]["columns"][0]["primary_key"] is True
    assert result["tables"][0]["indexes"][0]["name"] == "ix_users_name"


@pytest.mark.anyio
async def test_plugin_manager_lists_manifest_tool_permissions(tmp_path):
    plugin_dir = tmp_path / "permission_tool"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(
        '''
name = "permission_tool"
version = "0.1.0"
entry = "main:PermissionToolPlugin"
enabled = true

[[agent_tools]]
name = "plugin.permission_echo"
handler = "echo_tool"
description = "Echo with manifest permissions."
risk_level = "read"
toolset = "plugin"
platforms = ["wechat"]
scopes = ["private"]
modes = ["admin"]
'''.strip(),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        '''
from xbot.plugins.base import PluginBase


class PermissionToolPlugin(PluginBase):
    async def echo_tool(self, payload):
        return {"echo": payload.get("text")}
'''.strip(),
        encoding="utf-8",
    )
    plugins = PluginManager(PluginConfig(directory=str(tmp_path)))
    await plugins.load_all()

    tools = plugins.list_agent_tools("permission_tool")

    assert tools[0]["name"] == "plugin.permission_echo"
    assert tools[0]["enabled"] is True
    assert tools[0]["metadata"]["platforms"] == ["wechat"]
    assert tools[0]["metadata"]["scopes"] == ["private"]
    assert tools[0]["metadata"]["modes"] == ["admin"]


@pytest.mark.anyio
async def test_manage_plugin_lists_plugins_from_chat_command():
    replies = []
    plugins = PluginManager(PluginConfig(directory="plugins"))

    async def send_reply(reply):
        replies.append(reply)

    plugins.attach_runtime(send_reply=send_reply)
    await plugins.load_all()
    message = Message(
        platform="wechat",
        adapter="wechat869",
        conversation_id="44694849727@chatroom",
        sender_id="xianan96928",
        content="插件列表",
        raw={"scope": "group", "sender_wxid": "xianan96928"},
    )

    await plugins.dispatch_message(message)

    assert replies
    assert "插件列表" in replies[0].content
    assert "manage_plugin" in replies[0].content
    assert "agent_chat" in replies[0].content


@pytest.mark.anyio
async def test_plugin_manager_reload_reloads_code_and_unloads_old_instance(tmp_path):
    plugin_dir = tmp_path / "hot_plugin"
    marker = tmp_path / "unloaded.txt"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(
        '''
name = "hot_plugin"
version = "0.1.0"
entry = "main:HotPlugin"
enabled = true
'''.strip(),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        f'''
from pathlib import Path
from xbot.plugins.base import PluginBase


class HotPlugin(PluginBase):
    version = "one"

    async def on_unload(self):
        Path(r"{marker}").write_text("old unloaded", encoding="utf-8")
'''.strip(),
        encoding="utf-8",
    )
    plugins = PluginManager(PluginConfig(directory=str(tmp_path)))
    await plugins.load_all()
    assert plugins._plugins["hot_plugin"].version == "one"

    (plugin_dir / "main.py").write_text(
        '''
from xbot.plugins.base import PluginBase


class HotPlugin(PluginBase):
    version = "two"
'''.strip(),
        encoding="utf-8",
    )

    assert await plugins.reload("hot_plugin") is True

    assert marker.read_text(encoding="utf-8") == "old unloaded"
    assert plugins._plugins["hot_plugin"].version == "two"


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


@pytest.mark.anyio
async def test_agent_runtime_does_not_force_tool_call_failure_for_plain_final(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"final":"正在查看 skill 目录..."}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("列出skill目录所有skill名称", source="test")

    assert result.output == "正在查看 skill 目录..."
    assert len(llm.messages) == 1


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
async def test_agent_runtime_extracts_malformed_tool_call_json(tmp_path):
    (tmp_path / "src").mkdir()
    llm = FakeLLMProvider(
        responses=[
            (
                '{"tool_calls":[{"tool":"filesystem.list_dir","payload":{"path":"src"}},'
                '{"tool":"filesystem.list_dir","payload":{"path":"src"}]}'
            ),
            '{"final":"已查看 src 目录。"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("你好", source="test")

    assert result.output == "已查看 src 目录。"
    assert "tool_calls" not in result.output
    assert len(llm.messages) == 2


@pytest.mark.anyio
async def test_agent_runtime_executes_standalone_tool_call_json(tmp_path):
    target = tmp_path / "project.txt"
    target.write_text("xbot", encoding="utf-8")
    llm = FakeLLMProvider(
        responses=[
            '{"tool":"filesystem.read_file","payload":{"path":"project.txt"}}',
            '{"final":"文件内容是 xbot"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task("读取文件", source="test")

    assert result.output == "文件内容是 xbot"
    assert len(llm.messages) == 2


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
async def test_agent_runtime_accepts_plain_final_without_forcing_tool_call(tmp_path):
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

    assert result.output == "正在查看 skill 目录..."
    assert len(llm.messages) == 1


@pytest.mark.anyio
async def test_filesystem_read_file_reports_directory_error(tmp_path):
    (tmp_path / "configs").mkdir()
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)

    result = await runtime.execute_tool("filesystem.read_file", {"path": "configs"})

    assert result.status == "failed"
    assert "use filesystem.list_dir" in result.error
    assert result.error_type == "directory_as_file"
    assert result.fallback["suggested_tool"] == "filesystem.list_dir"
    assert result.fallback["auto_result"]["status"] == "completed"
    assert result.fallback["auto_result"]["output"] == []


@pytest.mark.anyio
async def test_environment_snapshot_reports_runtime(tmp_path):
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)

    result = await runtime.execute_tool(
        "environment.snapshot",
        {"commands": ["python"], "ports": [1]},
    )

    assert result.status == "completed"
    assert result.output["python"]["version"]
    assert result.output["commands"]["python"]["available"] is True
    assert result.output["workspace"]["root"] == str(tmp_path.resolve())


@pytest.mark.anyio
async def test_task_start_runs_tool_in_background(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("background ok", encoding="utf-8")
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)

    started = await runtime.execute_tool(
        "task.start",
        {"tool": "filesystem.read_file", "payload": {"path": "notes.txt"}},
    )
    task_id = started.output["id"]

    for _ in range(20):
        record = runtime.background.get(task_id)
        if record.status == "completed":
            break
        await anyio.sleep(0.01)

    status = await runtime.execute_tool("task.status", {"task_id": task_id})

    assert status.output["status"] == "completed"
    assert status.output["result"]["output"] == "background ok"


@pytest.mark.anyio
async def test_task_agent_start_runs_child_agent_and_notifies_wechat(tmp_path):
    replies = []
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"task.agent_start","payload":{"input":"写一段说明","ack":"我先安排子代理去写，完成后把结果发你。"}}]}',
            '{"final":"子代理完成：说明已写好。"}',
            '{"final":"我整理好了：说明已写好。"}',
        ]
    )

    async def send_reply(reply):
        replies.append(reply)

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)
    runtime.attach_reply_sender(send_reply)

    result = await runtime.run_task(
        "Channel message received.\nmessage_id: wx-msg-1\ncontent: 写一段说明",
        source="channel:wechat:wechat869:room@chatroom",
    )

    for _ in range(50):
        if replies:
            break
        await anyio.sleep(0.02)

    tasks = runtime.background.list()
    assert result.output == "我先安排子代理去写，完成后把结果发你。"
    assert "任务ID" not in result.output
    assert tasks[0].kind == "agent"
    assert tasks[0].metadata["ack"] == "我先安排子代理去写，完成后把结果发你。"
    assert tasks[0].metadata["notify_mode"] == "parent_agent"
    assert tasks[0].metadata["notify"]["conversation_id"] == "room@chatroom"
    assert tasks[0].metadata["notify"]["quote_message_id"] == "wx-msg-1"
    assert replies[0].conversation_id == "room@chatroom"
    assert replies[0].quote_message_id == "wx-msg-1"
    assert replies[0].content == "我整理好了：说明已写好。"
    assert "Child agent task completed" in llm.messages[-1][-1].content


@pytest.mark.anyio
async def test_background_task_persists_and_sends_completion_reply(tmp_path):
    repo = FakeAgentRepository()
    replies = []
    target = tmp_path / "notes.txt"
    target.write_text("notify ok", encoding="utf-8")

    @asynccontextmanager
    async def provider():
        yield repo

    async def send_reply(reply):
        replies.append(reply)

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, repository_provider=provider)
    runtime.attach_reply_sender(send_reply)

    started = await runtime.execute_tool(
        "task.start",
        {
            "tool": "filesystem.read_file",
            "payload": {"path": "notes.txt"},
            "notify": {
                "platform": "web",
                "adapter": "web",
                "conversation_id": "c1",
                "quote_message_id": "m1",
            },
        },
    )
    task_id = started.output["id"]

    for _ in range(50):
        record = runtime.background.get(task_id)
        if record.status == "completed" and replies and repo.background_tasks.get(task_id):
            break
        await anyio.sleep(0.02)

    persisted = await runtime.get_background_task(task_id)

    assert persisted.status == "completed"
    assert persisted.result["output"] == "notify ok"
    assert replies[0].conversation_id == "c1"
    assert replies[0].quote_message_id == "m1"
    assert replies[0].content == "notify ok"


@pytest.mark.anyio
async def test_background_task_persists_same_task_serially():
    from xbot.agent.background import BackgroundTaskManager

    class SlowBackgroundRepo:
        def __init__(self):
            self.active = set()
            self.violations = 0
            self.calls = 0

        async def upsert_background_task(self, item):
            self.calls += 1
            if item.id in self.active:
                self.violations += 1
            self.active.add(item.id)
            await anyio.sleep(0.02)
            self.active.remove(item.id)

    repo = SlowBackgroundRepo()

    @asynccontextmanager
    async def provider():
        yield repo

    async def runner():
        await anyio.sleep(0.01)
        return {"output": "ok"}

    manager = BackgroundTaskManager(repository_provider=provider)
    record = manager.start(kind="tool", runner=runner)

    for _ in range(50):
        current = manager.get(record.id)
        if current and current.status == "completed" and not repo.active and repo.calls >= 3:
            break
        await anyio.sleep(0.02)

    assert repo.violations == 0
    assert repo.calls >= 3


@pytest.mark.anyio
async def test_background_task_subscriber_receives_completion():
    from xbot.agent.background import BackgroundTaskManager

    seen = []

    async def runner():
        return {"output": "done"}

    async def subscriber(record):
        seen.append((record.id, record.status, record.result))

    manager = BackgroundTaskManager()
    manager.subscribe(subscriber)
    record = manager.start(kind="tool", runner=runner, description="test")

    for _ in range(50):
        if seen:
            break
        await anyio.sleep(0.02)

    assert seen == [(record.id, "completed", {"output": "done"})]


@pytest.mark.anyio
async def test_channel_task_start_auto_injects_notification_target(tmp_path):
    replies = []
    target = tmp_path / "notes.txt"
    target.write_text("channel notify ok", encoding="utf-8")
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"task.start","payload":{"tool":"filesystem.read_file","payload":{"path":"notes.txt"}}}]}',
            '{"final":"后台任务已开始。"}',
        ]
    )

    async def send_reply(reply):
        replies.append(reply)

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)
    runtime.attach_reply_sender(send_reply)

    result = await runtime.run_task(
        "Channel message received.\nmessage_id: msg-1\ncontent: 读取文件",
        source="channel:web:web:conversation-1",
    )

    for _ in range(50):
        if replies:
            break
        await anyio.sleep(0.02)

    assert result.output.startswith("后台任务已开始")
    assert replies[0].conversation_id == "conversation-1"
    assert replies[0].quote_message_id == "msg-1"
    assert replies[0].content == "channel notify ok"


@pytest.mark.anyio
async def test_channel_send_text_skill_does_not_start_background(tmp_path):
    calls = []
    llm = FakeLLMProvider(
        responses=[
            (
                '{"tool_calls":[{"tool":"task.start","payload":{"tool":"skill.run",'
                '"payload":{"skill":"wechat-869-media-sender","action":"send-text",'
                '"args":{"to":"room@chatroom","text":"你好"}}}}]}'
            ),
            '{"final":"已发送。"}',
        ]
    )

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    async def fake_execute(tool_name, payload):
        calls.append((tool_name, payload))
        return {"ok": True}

    runtime.executor.execute = fake_execute

    result = await runtime.run_task(
        "Channel message received.\ncontent: 发送文字",
        source="channel:wechat:wechat869:room@chatroom",
    )

    assert result.output == "已发送。"
    assert calls[0][0] == "skill.run"
    assert calls[0][1]["args"]["text"] == "你好"
    assert not runtime.background.list(limit=5)


@pytest.mark.anyio
async def test_wechat_send_text_routes_to_current_channel(tmp_path):
    replies = []
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"wechat.send_text","payload":{"text":"主动发送"}}]}',
            '{"final":"已发送。"}',
        ]
    )
    runtime = AgentRuntime(
        AgentConfig(
            workspace_root=str(tmp_path),
            workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        ),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )

    async def fake_send_reply(reply):
        replies.append(reply)

    runtime.attach_reply_sender(fake_send_reply)

    result = await runtime.run_task(
        "Channel message received.\nmessage_id: msg-1\ncontent: 发送文字",
        source="channel:wechat:wechat_ilink:ilink:u1",
    )

    assert result.output == "已发送。"
    assert result.suppress_channel_reply is True
    assert replies == [
        Reply(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            type="text",
            content="主动发送",
            quote_message_id="msg-1",
        )
    ]
    assert len(llm.messages) == 1


@pytest.mark.anyio
async def test_wechat_send_image_routes_869_to_media_skill(tmp_path):
    calls = []
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"wechat.send_image","payload":{"path":"out.png"}}]}',
            '{"final":"已发送图片。"}',
        ]
    )
    runtime = AgentRuntime(
        AgentConfig(
            workspace_root=str(tmp_path),
            workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        ),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )

    async def fake_run_skill(payload):
        calls.append(payload)
        return {"output": "ok"}

    runtime.skill_tools.run_skill = fake_run_skill

    result = await runtime.run_task(
        "Channel message received.\nreply_target_wxid: room@chatroom\ncontent: 发图片",
        source="channel:wechat:wechat869:wechat:wechat869:group:room@chatroom",
    )

    assert result.output == "已发送图片。"
    assert result.suppress_channel_reply is False
    assert calls[0]["skill"] == "wechat-869-media-sender"
    assert calls[0]["action"] == "send-image"
    assert calls[0]["args"]["to"] == "room@chatroom"
    assert calls[0]["args"]["path"] == "out.png"
    assert len(llm.messages) == 2


@pytest.mark.anyio
async def test_wechat_send_file_routes_ilink_to_current_channel(tmp_path):
    replies = []
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"wechat.send_file","payload":{"path":"a.zip"}}]}',
            '{"final":"已发送文件。"}',
        ]
    )
    runtime = AgentRuntime(
        AgentConfig(
            workspace_root=str(tmp_path),
            workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        ),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )

    async def fake_send_reply(reply):
        replies.append(reply)

    runtime.attach_reply_sender(fake_send_reply)

    result = await runtime.run_task(
        "Channel message received.\ncontent: 发文件",
        source="channel:wechat:wechat_ilink:ilink:u1",
    )

    assert result.output == "已发送文件。"
    assert result.suppress_channel_reply is False
    assert replies == [
        Reply(
            platform="wechat",
            adapter="wechat_ilink",
            conversation_id="ilink:u1",
            type="file",
            content="a.zip",
            quote_message_id=None,
        )
    ]
    assert len(llm.messages) == 2


@pytest.mark.anyio
async def test_agent_runtime_maps_bare_tool_aliases(tmp_path):
    target = tmp_path / "hello.txt"
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"write_file","payload":{"path":"hello.txt","content":"ok"}}]}',
            '{"final":"写好了。"}',
        ]
    )
    runtime = AgentRuntime(
        AgentConfig(
            workspace_root=str(tmp_path),
            workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
            allow_shell=True,
        ),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )

    result = await runtime.run_task("写一个测试文件", source="api")

    assert result.output == "写好了。"
    assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.anyio
async def test_agent_runtime_returns_failed_tool_result_for_unknown_tool(tmp_path):
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"missing_tool","payload":{}}]}',
            '{"final":"工具不存在，无法执行。"}',
        ]
    )
    runtime = AgentRuntime(
        AgentConfig(
            workspace_root=str(tmp_path),
            workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
        ),
        plugins=None,
        skills=None,
        llm_provider=llm,
    )

    result = await runtime.run_task("调用不存在工具", source="api")

    assert result.output == "工具不存在，无法执行。"
    assert "Tool not found: missing_tool" in llm.messages[-1][-1].content


@pytest.mark.anyio
async def test_skill_run_accepts_flat_wechat_text_args(tmp_path):
    commands = []

    class FakeWorkspace:
        async def run_shell(self, command, **kwargs):
            commands.append(command)
            return {"output": "ok"}

    class FakeSkills:
        def get_path(self, name):
            assert name == "wechat-869-media-sender"
            return tmp_path

    provider = SkillToolProvider(workspace=FakeWorkspace(), skills=FakeSkills())

    result = await provider.run_skill(
        {
            "skill": "wechat-869-media-sender",
            "action": "send-text",
            "to": "room@chatroom",
            "text": "你好",
        }
    )

    assert result == {"output": "ok"}
    assert "--to room@chatroom" in commands[0]
    assert "--text" in commands[0]


def test_planner_cleans_lenient_final_json_with_inner_quotes():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        '{"final":"已回复！虽然被调侃"蠢"，但态度还是很友好的~"}'
    )

    assert output == '已回复！虽然被调侃"蠢"，但态度还是很友好的~'


def test_planner_parses_minimax_tool_call_xml():
    planner = AgentPlanner()

    plan = planner.parse_llm_response(
        '<minimax:tool_call>\n'
        '<invoke name="memory.read","payload":{"target": "user"}}\n'
        '</minimax:tool_call>'
    )

    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].tool == "memory.read"
    assert plan.tool_calls[0].payload == {"target": "user"}
    assert plan.final is None


def test_planner_strips_minimax_tool_call_from_final_output():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        '<minimax:tool_call>\n'
        '<invoke name="memory.add","payload":{"target":"memory","content":"Agent 名字：老夏"}}\n'
        '</minimax:tool_call>\n'
        "记住了，我以后叫老夏。"
    )

    assert output == "记住了，我以后叫老夏。"
    assert "minimax:tool_call" not in output
    assert "memory.add" not in output


def test_planner_strips_reasoning_tags_from_final_output():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        "<think>用户在群里@了我，需要中文回复。</think>\n\n"
        "哈哈，没关系呀！芯儿这个名字也挺好听的。"
    )

    assert output == "哈哈，没关系呀！芯儿这个名字也挺好听的。"
    assert "<think>" not in output


def test_planner_strips_reasoning_tags_from_json_final():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        '{"final":"<thinking>先分析用户意图</thinking>\\n已更新。"}'
    )

    assert output == "已更新。"
    assert "thinking" not in output


def test_planner_strips_reasoning_fences_from_final_output():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        "```reasoning\n"
        "这里是模型内部推理。\n"
        "```\n"
        "可以，我来处理。"
    )

    assert output == "可以，我来处理。"
    assert "内部推理" not in output


def test_planner_parses_openai_function_call_shape():
    planner = AgentPlanner()

    plan = planner.parse_llm_response(
        '{"tool_calls":[{"function":{"name":"memory.read","arguments":"{\\"target\\":\\"user\\"}"}}]}'
    )

    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].tool == "memory.read"
    assert plan.tool_calls[0].payload == {"target": "user"}


def test_planner_parses_function_call_xml_shape():
    planner = AgentPlanner()

    plan = planner.parse_llm_response(
        '<function_call name="wiki.manage">{"action":"query","query":"memory"}</function_call>'
    )

    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].tool == "wiki.manage"
    assert plan.tool_calls[0].payload == {"action": "query", "query": "memory"}


def test_planner_parses_tool_arguments_text_shape():
    planner = AgentPlanner()

    plan = planner.parse_llm_response(
        'Tool: memory.read\nArguments: {"target":"memory"}'
    )

    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].tool == "memory.read"
    assert plan.tool_calls[0].payload == {"target": "memory"}


def test_planner_strips_generic_tool_blocks_from_final_output():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        '<function_call name="memory.read">{"target":"user"}</function_call>\n'
        '读取完成。'
    )

    assert output == "读取完成。"
    assert "function_call" not in output


def test_planner_parses_bracket_tool_call_hashrocket_shape():
    planner = AgentPlanner()

    plan = planner.parse_llm_response(
        '[TOOL_CALL]\n'
        '{tool => "skill.describe", payload => {"skill": "xbot-self-evolution"}}\n'
        '[/TOOL_CALL]\n'
        '[TOOL_CALL]\n'
        r'{tool => "filesystem.list_dir", payload => {"path": "C:\\Users\\Administrator\\Desktop\\xbot-next\\skills\\.agent"}}'
        '\n[/TOOL_CALL]'
    )

    assert len(plan.tool_calls) == 2
    assert plan.tool_calls[0].tool == "skill.describe"
    assert plan.tool_calls[0].payload == {"skill": "xbot-self-evolution"}
    assert plan.tool_calls[1].tool == "filesystem.list_dir"
    assert plan.tool_calls[1].payload["path"].endswith(r"skills\.agent")


def test_planner_strips_bracket_tool_call_blocks_from_final_output():
    planner = AgentPlanner()

    output = planner.clean_final_output(
        '[TOOL_CALL]\n'
        '{tool => "skill.describe", payload => {"skill": "xbot-self-evolution"}}\n'
        '[/TOOL_CALL]\n'
        "我已经查看自我进化 skill。"
    )

    assert output == "我已经查看自我进化 skill。"
    assert "TOOL_CALL" not in output
    assert "skill.describe" not in output


@pytest.mark.anyio
async def test_background_task_replays_interrupted_read_task(tmp_path):
    repo = FakeAgentRepository()
    target = tmp_path / "notes.txt"
    target.write_text("replayed ok", encoding="utf-8")

    record = BackgroundTaskRecord(
        id="bg-replay",
        kind="tool",
        status="running",
        source="agent",
        description="Replay read",
        metadata={
            "tool": "filesystem.read_file",
            "payload": {"path": "notes.txt"},
            "replayable": True,
        },
    )
    repo.background_tasks[record.id] = record

    @asynccontextmanager
    async def provider():
        yield repo

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, repository_provider=provider)
    await runtime.start()

    for _ in range(50):
        replayed = runtime.background.get("bg-replay")
        if replayed and replayed.status == "completed":
            break
        await anyio.sleep(0.02)

    replayed = await runtime.get_background_task("bg-replay")

    assert replayed.status == "completed"
    assert replayed.result["output"] == "replayed ok"
    assert replayed.metadata["replayed"] is True
    assert replayed.metadata["replay_count"] == 1


@pytest.mark.anyio
async def test_timeout_fallback_starts_read_tool_in_background(tmp_path):
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None)

    async def slow_read(payload):
        await anyio.sleep(0.05)
        return {"ok": True}

    runtime.tools.register(
        ToolDefinition(
            name="test.slow_read",
            description="Slow read test tool.",
            risk_level="read",
            handler=slow_read,
            toolset="core",
            source="test",
            timeout_seconds=0.01,
            metadata={"background_candidate": True},
            input_schema={"type": "object", "properties": {}},
        )
    )

    result = await runtime.execute_tool("test.slow_read", {})

    assert result.status == "failed"
    assert result.error_type == "timeout"
    assert result.fallback["auto_result"]["tool"] == "task.start"
    task_id = result.fallback["auto_result"]["output"]["id"]
    assert runtime.background.get(task_id).metadata["tool"] == "test.slow_read"


@pytest.mark.anyio
async def test_background_task_overview_lists_candidates_and_replayable(tmp_path):
    repo = FakeAgentRepository()
    record = BackgroundTaskRecord(
        id="bg-overview",
        kind="tool",
        status="failed",
        source="agent",
        description="Replayable read",
        metadata={
            "tool": "filesystem.read_file",
            "payload": {"path": "missing.txt"},
            "replayable": True,
        },
    )
    repo.background_tasks[record.id] = record

    @asynccontextmanager
    async def provider():
        yield repo

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, repository_provider=provider)

    overview = await runtime.background_task_overview()

    assert overview["counts"]["failed"] == 1
    assert overview["replayable"][0]["id"] == "bg-overview"
    candidate_names = {item["name"] for item in overview["background_candidate_tools"]}
    assert "browser.run_actions" in candidate_names
    assert "skill.run" in candidate_names


@pytest.mark.anyio
async def test_replay_background_task_api_path_requeues_failed_read(tmp_path):
    repo = FakeAgentRepository()
    target = tmp_path / "notes.txt"
    target.write_text("manual replay ok", encoding="utf-8")
    record = BackgroundTaskRecord(
        id="bg-manual-replay",
        kind="tool",
        status="failed",
        source="agent",
        description="Manual replay read",
        metadata={
            "tool": "filesystem.read_file",
            "payload": {"path": "notes.txt"},
            "replayable": True,
        },
    )
    repo.background_tasks[record.id] = record

    @asynccontextmanager
    async def provider():
        yield repo

    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, repository_provider=provider)

    replayed = await runtime.replay_background_task("bg-manual-replay")
    for _ in range(50):
        if replayed.status == "completed":
            break
        await anyio.sleep(0.02)

    assert replayed.status == "completed"
    assert replayed.result["output"] == "manual replay ok"
    assert replayed.metadata["replay_count"] == 1


@pytest.mark.anyio
async def test_channel_metadata_candidate_tool_auto_runs_in_background(tmp_path):
    calls = []
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"test.long_read","payload":{"value":"x"}}]}',
            '{"final":"后台任务已开始。"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    async def long_read(payload):
        calls.append(payload)
        return f"long {payload['value']}"

    runtime.tools.register(
        ToolDefinition(
            name="test.long_read",
            description="Long read test tool.",
            risk_level="read",
            handler=long_read,
            toolset="core",
            source="test",
            timeout_seconds=30,
            metadata={"background_candidate": True},
            input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        )
    )

    result = await runtime.run_task(
        "Channel message received.\nmessage_id: m1\ncontent: run long",
        source="channel:web:web:c1",
    )

    for _ in range(50):
        if calls:
            break
        await anyio.sleep(0.02)
    tasks = runtime.background.list()

    assert result.output.startswith("后台任务已开始")
    assert calls == [{"value": "x"}]
    assert tasks[0].metadata["tool"] == "test.long_read"
    assert tasks[0].metadata["notify"]["conversation_id"] == "c1"


@pytest.mark.anyio
async def test_wechat869_background_task_does_not_auto_notify_and_waits_for_final(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("wechat background ok", encoding="utf-8")
    llm = FakeLLMProvider(
        responses=[
            '{"tool_calls":[{"tool":"task.start","payload":{"tool":"filesystem.read_file","payload":{"path":"notes.txt"}}}]}',
            '{"final":"我已经开始处理，稍后根据结果回复。"}',
        ]
    )
    config = AgentConfig(
        workspace_root=str(tmp_path),
        workspace=AgentWorkspaceConfig(roots=[str(tmp_path)]),
    )
    runtime = AgentRuntime(config, plugins=None, skills=None, llm_provider=llm)

    result = await runtime.run_task(
        "Channel message received.\nmessage_id: m1\ncontent: 读取文件",
        source="channel:wechat:wechat869:44694849727@chatroom",
    )

    for _ in range(50):
        tasks = runtime.background.list()
        if tasks and tasks[0].status == "completed":
            break
        await anyio.sleep(0.02)
    tasks = runtime.background.list()

    assert result.output == "我已经开始处理，稍后根据结果回复。"
    assert tasks[0].metadata["tool"] == "filesystem.read_file"
    assert tasks[0].metadata.get("notify") is None
    assert len(llm.messages) == 2

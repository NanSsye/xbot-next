from pathlib import Path

import pytest

from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.runtime import AgentResult, AgentRuntimeEvent
from xbot.agent.runtime import AgentRuntime
from xbot.cli.chat import (
    TerminalChatOptions,
    TerminalChatSession,
    TerminalDisplayState,
    TerminalRenderer,
    ToolProgressRenderer,
    build_terminal_agent_input,
)
from xbot.cli.bridge import TerminalBridgeOptions, TerminalBridgeSession
from xbot.cli.tui import TerminalTuiRenderer
from xbot.core.config import AgentConfig
from xbot.core.logging import configure_terminal_logging, logger


def test_terminal_agent_input_contains_terminal_context(tmp_path):
    text = build_terminal_agent_input("列出插件", session_id="s1", cwd=tmp_path)

    assert "Terminal message received." in text
    assert "platform: terminal" in text
    assert "adapter: cli" in text
    assert "session_id: s1" in text
    assert f"cwd: {tmp_path}" in text
    assert "content: 列出插件" in text


def test_agent_visible_tools_exposes_hermes_catalog():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    tools = {item["name"] for item in runtime.visible_tools(source="terminal:local:s1")}

    assert "read_file" in tools
    assert "terminal" in tools
    assert "skill_manage" in tools


def test_terminal_chat_uses_plain_input_by_default(tmp_path):
    session = TerminalChatSession(
        ctx=object(),
        options=TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )

    assert session._prompt_session is None


def test_terminal_renderer_welcome_body_contains_home_sections(tmp_path):
    renderer = TerminalRenderer()
    if renderer.console is None:
        pytest.skip("rich is not installed")

    body = renderer._welcome_body(
        TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
        [("model", "fake:m1"), ("tools_count", "2"), ("skills_count", "1")],
        {"tools": ["core: filesystem.list_dir"], "skills": ["code_assistant"]},
    )

    assert body is not None


def test_terminal_chat_fancy_input_builds_toolbar(tmp_path):
    class FakeAgent:
        def llm_status(self):
            return {"model": "m1"}

    class FakeContext:
        pass

    ctx = FakeContext()
    ctx.agent = FakeAgent()
    session = TerminalChatSession(
        ctx=ctx,
        options=TerminalChatOptions(session_id="session-1234", cwd=Path(tmp_path), fancy_input=True),
    )

    assert "session session-" in session._bottom_toolbar()
    assert "model m1" in session._bottom_toolbar()


def test_terminal_logging_writes_to_file(tmp_path):
    configure_terminal_logging(cwd=tmp_path)

    logger.info("terminal log test")
    logger.complete()

    assert (tmp_path / "logs" / "xbot-terminal.log").exists()
    assert "terminal log test" in (tmp_path / "logs" / "xbot-terminal.log").read_text(
        encoding="utf-8"
    )


@pytest.mark.anyio
async def test_agent_runtime_event_subscription_receives_events():
    runtime = AgentRuntime(AgentConfig(), plugins=None, skills=None)
    events = []

    async def subscriber(event):
        events.append((event.task_id, event.type, event.content))

    unsubscribe = runtime.subscribe_events(subscriber)
    await runtime._add_event("task-1", "tool.started", {"tool": "filesystem.list_dir"})
    unsubscribe()
    await runtime._add_event("task-1", "tool.completed", {"tool": "filesystem.list_dir"})

    assert events == [("task-1", "tool.started", {"tool": "filesystem.list_dir"})]


@pytest.mark.anyio
async def test_terminal_chat_session_handles_new_and_unknown_commands(tmp_path):
    class FakeContext:
        pass

    ctx = FakeContext()
    ctx.agent = None
    ctx.engine = None
    ctx.message_queue = None
    ctx.storage = None
    session = TerminalChatSession(
        ctx,
        TerminalChatOptions(session_id="old", cwd=Path(tmp_path)),
    )

    assert await session.handle_command("/new") is True
    assert session.options.session_id != "old"
    assert session.source.startswith("terminal:local:")
    assert await session.handle_command("/unknown") is True


@pytest.mark.anyio
async def test_terminal_chat_session_streams_agent_events(tmp_path):
    class FakeAgent:
        def __init__(self):
            self.subscriber = None

        def subscribe_events(self, subscriber):
            self.subscriber = subscriber

            def unsubscribe():
                self.subscriber = None

            return unsubscribe

        async def run_task(self, input_text: str, source: str):
            await self.subscriber(
                AgentRuntimeEvent(
                    task_id="task-1",
                    type="tool.started",
                    content={"tool": "filesystem.list_dir"},
                )
            )
            await self.subscriber(
                AgentRuntimeEvent(
                    task_id="task-1",
                    type="tool.completed",
                    content={"tool": "filesystem.list_dir"},
                )
            )
            return AgentResult(task_id="task-1", source=source, status="completed", output="完成")

    class FakeRenderer:
        def __init__(self):
            self.events = []
            self.outputs = []

        def event(self, event):
            self.events.append(event.type)

        def assistant(self, text):
            self.outputs.append(text)

        def system(self, text):
            self.outputs.append(text)

    class FakeContext:
        pass

    ctx = FakeContext()
    ctx.agent = FakeAgent()
    session = TerminalChatSession(
        ctx,
        TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )
    renderer = FakeRenderer()
    session.renderer = renderer

    await session.run_agent_turn("列目录")

    assert renderer.events == ["tool.started", "tool.completed"]
    assert renderer.outputs == ["完成"]
    assert [event.type for event in session._events] == ["tool.started", "tool.completed"]


@pytest.mark.anyio
async def test_terminal_chat_session_does_not_store_llm_delta_events(tmp_path):
    class FakeAgent:
        def __init__(self):
            self.subscriber = None

        def subscribe_events(self, subscriber):
            self.subscriber = subscriber

            def unsubscribe():
                self.subscriber = None

            return unsubscribe

        async def run_task(self, input_text: str, source: str):
            await self.subscriber(
                AgentRuntimeEvent(
                    task_id="task-1",
                    type="llm.delta",
                    content={"text": "你好"},
                )
            )
            await self.subscriber(
                AgentRuntimeEvent(
                    task_id="task-1",
                    type="llm.completed",
                    content={"iteration": 0},
                )
            )
            return AgentResult(task_id="task-1", source=source, status="completed", output="你好")

    class FakeRenderer:
        def __init__(self):
            self.events = []
            self.outputs = []

        def event(self, event):
            self.events.append(event.type)

        def assistant(self, text):
            self.outputs.append(text)

    class FakeContext:
        pass

    ctx = FakeContext()
    ctx.agent = FakeAgent()
    session = TerminalChatSession(
        ctx,
        TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )
    renderer = FakeRenderer()
    session.renderer = renderer

    await session.run_agent_turn("你好")

    assert renderer.events == ["llm.delta", "llm.completed"]
    assert [event.type for event in session._events] == ["llm.completed"]
    assert renderer.outputs == ["你好"]


@pytest.mark.anyio
async def test_terminal_chat_session_keeps_background_history(tmp_path):
    class FakeBackground:
        def subscribe(self, subscriber):
            self.subscriber = subscriber

            def unsubscribe():
                self.subscriber = None

            return unsubscribe

    class FakeAgent:
        def __init__(self):
            self.background = FakeBackground()

    class FakeRenderer:
        def __init__(self):
            self.records = []

        def background_task(self, record):
            self.records.append(record.id)

    class FakeContext:
        pass

    ctx = FakeContext()
    ctx.agent = FakeAgent()
    session = TerminalChatSession(
        ctx,
        TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )
    renderer = FakeRenderer()
    session.renderer = renderer
    record = BackgroundTaskRecord(
        id="bg-1",
        kind="tool",
        status="completed",
        description="Read file",
        result={"output": "done"},
    )

    await session._on_background_task(record)

    assert session._background_events == [record]
    assert renderer.records == ["bg-1"]


@pytest.mark.anyio
async def test_terminal_chat_session_handles_events_and_logs_commands(tmp_path):
    class FakeAgent:
        pass

    class FakeContext:
        pass

    class FakeRenderer:
        def __init__(self):
            self.agent_history = []
            self.background_calls = []

        def event_history(self, events, *, limit=20):
            self.agent_history.append((list(events[-limit:]), limit))

        def background_history(self, records, *, limit=20):
            self.background_calls.append((list(records[-limit:]), limit))

    ctx = FakeContext()
    ctx.agent = FakeAgent()
    session = TerminalChatSession(
        ctx,
        TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )
    renderer = FakeRenderer()
    session.renderer = renderer
    event = AgentRuntimeEvent(task_id="task-1", type="tool.started", content={"tool": "x"})
    background = BackgroundTaskRecord(
        id="bg-1",
        kind="tool",
        status="completed",
        description="Read file",
    )
    session._remember_event(event)
    session._background_events.append(background)

    assert await session.handle_command("/events 1") is True
    assert await session.handle_command("/logs 2") is True

    assert renderer.agent_history[0] == ([event], 1)
    assert renderer.agent_history[1] == ([event], 2)
    assert renderer.background_calls == [([background], 2)]


def test_terminal_renderer_formats_background_task_completion():
    from xbot.cli.chat import TerminalRenderer

    renderer = TerminalRenderer()
    renderer.console = None
    record = BackgroundTaskRecord(
        id="bg-1",
        kind="tool",
        status="completed",
        description="Read file",
        result={"output": "done"},
    )

    assert renderer._background_task_output(record) == "done"
    assert "description: Read file" in renderer._background_task_body(record)


def test_terminal_renderer_compacts_default_events():
    renderer = TerminalRenderer()
    renderer.console = None

    event = AgentRuntimeEvent(task_id="t1", type="llm.started", content={"iteration": 0})
    renderer.event(event)
    assert renderer._display_state.thinking is True
    assert renderer._should_show_event(
        AgentRuntimeEvent(task_id="t1", type="tool.started", content={"tool": "filesystem.list_dir"})
    ) is False
    assert renderer._should_show_event(
        AgentRuntimeEvent(
            task_id="t1",
            type="tool.completed",
            content={"tool": "filesystem.list_dir"},
        )
    ) is False


def test_tool_progress_renderer_records_completed_tool():
    progress = ToolProgressRenderer()
    state = TerminalDisplayState(started_at=0.0)

    progress.consume(
        AgentRuntimeEvent(task_id="t1", type="tool.started", content={"tool": "filesystem.list_dir"}),
        state,
    )
    progress.consume(
        AgentRuntimeEvent(task_id="t1", type="tool.completed", content={"tool": "filesystem.list_dir"}),
        state,
    )

    assert len(state.tools) == 1
    assert state.tools[0].name == "filesystem.list_dir"
    assert state.tools[0].status == "ok"
    assert state.tools[0].duration_seconds is not None


def test_tool_progress_renderer_keeps_input_output_previews():
    progress = ToolProgressRenderer()
    state = TerminalDisplayState(started_at=0.0)

    progress.consume(
        AgentRuntimeEvent(
            task_id="t1",
            type="tool.started",
            content={"tool": "shell.exec", "input": {"command": "dir"}},
        ),
        state,
    )
    progress.consume(
        AgentRuntimeEvent(
            task_id="t1",
            type="tool.completed",
            content={"tool": "shell.exec", "output": {"output": "ok"}},
        ),
        state,
    )

    assert "command" in state.tools[0].input_preview
    assert "ok" in state.tools[0].output_preview


def test_terminal_renderer_activity_body_contains_tool_summary():
    renderer = TerminalRenderer()
    renderer.begin_turn()
    renderer.event(AgentRuntimeEvent(task_id="task-1", type="llm.started", content={}))
    renderer.event(
        AgentRuntimeEvent(task_id="task-1", type="tool.started", content={"tool": "filesystem.list_dir"})
    )
    renderer.event(
        AgentRuntimeEvent(
            task_id="task-1",
            type="tool.completed",
            content={"tool": "filesystem.list_dir"},
        )
    )

    body = renderer._activity_body()

    assert "thinking" in body
    assert "filesystem.list_dir" in body
    assert "OK" in body


def test_terminal_renderer_status_bar_uses_token_usage(capsys):
    renderer = TerminalRenderer()
    renderer.console = None
    renderer._display_state.usage_total_tokens = 17_900
    renderer._display_state.llm_elapsed_seconds = 3

    renderer.status_bar(
        model="mimo-v2.5-pro",
        context_window=1_000_000,
        elapsed_seconds=180,
        output_text="ignored when usage is present",
    )

    captured = capsys.readouterr().out
    assert "mimo-v2.5-pro" in captured
    assert "17.9K/1M" in captured
    assert "2%" in captured
    assert "3m" in captured


def test_terminal_renderer_stream_delta_skips_duplicate_final(capsys):
    renderer = TerminalRenderer()
    renderer.console = None

    renderer.event(
        AgentRuntimeEvent(
            task_id="task-1",
            type="llm.delta",
            content={"text": "你好"},
        )
    )
    renderer.assistant("你好")

    captured = capsys.readouterr().out
    assert captured.count("你好") == 1


def test_terminal_renderer_formats_plain_user_and_assistant(capsys):
    renderer = TerminalRenderer()
    renderer.console = None

    renderer.user("你好")
    renderer.assistant("可以")

    captured = capsys.readouterr().out
    assert "> 你好" in captured
    assert "xbot" in captured
    assert "你好" in captured
    assert "可以" in captured


def test_terminal_renderer_stream_delta_skips_contained_final(capsys):
    renderer = TerminalRenderer()
    renderer.console = None
    renderer._stream_buffer = "重复前缀\n最终回复"

    renderer.assistant("最终回复")

    captured = capsys.readouterr().out
    assert "assistant>" not in captured


def test_terminal_renderer_stream_delta_skips_final_inside_stream(capsys):
    renderer = TerminalRenderer()
    renderer.console = None
    renderer._stream_buffer = "最终回复\n重复内容"

    renderer.assistant("最终回复")

    captured = capsys.readouterr().out
    assert "assistant>" not in captured


def test_terminal_chat_session_builds_overview_rows(tmp_path):
    class FakeAgent:
        def llm_status(self):
            return {"provider": "fake", "model": "m1"}

        def visible_tools(self, *, source):
            return [
                {"name": "filesystem.list_dir", "toolset": "filesystem"},
                {"name": "shell.exec", "toolset": "shell"},
            ]

    class FakePlugins:
        def list_plugins(self):
            return [{"name": "agent_chat", "enabled": True}, {"name": "disabled", "enabled": False}]

    class FakeSkills:
        def list_skills(self):
            return [{"name": "code_assistant", "enabled": True}]

    class FakeContext:
        pass

    ctx = FakeContext()
    ctx.agent = FakeAgent()
    ctx.plugins = FakePlugins()
    ctx.skills = FakeSkills()
    session = TerminalChatSession(
        ctx,
        TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )

    rows = dict(session._overview_rows())

    assert rows["model"] == "fake:m1"
    assert rows["tools"].startswith("2")
    assert rows["plugins"].startswith("1")
    assert rows["skills"].startswith("1")
    sections = session._home_sections()
    assert "filesystem" in sections["tools"][0]
    assert "code_assistant" in sections["skills"]


@pytest.mark.anyio
async def test_terminal_bridge_emit_writes_json(capsys, tmp_path):
    class FakeContext:
        pass

    session = TerminalBridgeSession(
        FakeContext(),
        TerminalBridgeOptions(session_id="bridge-1", cwd=Path(tmp_path)),
    )

    await session.emit("ready", {"session_id": "bridge-1"})

    captured = capsys.readouterr().out
    assert '"type": "ready"' in captured
    assert '"session_id": "bridge-1"' in captured


def test_terminal_tui_renderer_writes_event_and_background_output():
    class FakeOptions:
        verbose = False
        debug = False

    class FakeSession:
        options = FakeOptions()

    class FakeApp:
        session = FakeSession()

        def __init__(self):
            self.chat = []
            self.events = []
            self.status = []

        def write_chat(self, text):
            self.chat.append(text)

        def write_events(self, text):
            self.events.append(text)

        def set_status(self, text):
            self.status.append(text)

        def clear_logs(self):
            self.chat.clear()
            self.events.clear()

    app = FakeApp()
    renderer = TerminalTuiRenderer(app)

    renderer.assistant("完成")
    renderer.event(
        AgentRuntimeEvent(
            task_id="task-1",
            type="tool.started",
            content={"tool": "filesystem.list_dir"},
        )
    )
    renderer.background_task(
        BackgroundTaskRecord(
            id="bg-1",
            kind="tool",
            status="completed",
            description="Read file",
            result={"output": "done"},
        )
    )

    assert "完成" in app.chat[0]
    assert "filesystem.list_dir" in app.events[0]
    assert "done" in app.events[1]

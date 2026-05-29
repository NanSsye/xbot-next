from pathlib import Path

import pytest

from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.runtime import AgentResult, AgentRuntimeEvent
from xbot.agent.runtime import AgentRuntime
from xbot.agent.tools.toolsets import toolsets_for_source
from xbot.cli.chat import TerminalChatOptions, TerminalChatSession, build_terminal_agent_input
from xbot.cli.tui import TerminalTuiRenderer
from xbot.core.config import AgentConfig, AgentToolsetConfig
from xbot.core.logging import configure_terminal_logging, logger


def test_terminal_agent_input_contains_terminal_context(tmp_path):
    text = build_terminal_agent_input("列出插件", session_id="s1", cwd=tmp_path)

    assert "Terminal message received." in text
    assert "platform: terminal" in text
    assert "adapter: cli" in text
    assert "session_id: s1" in text
    assert f"cwd: {tmp_path}" in text
    assert "content: 列出插件" in text


def test_terminal_source_uses_terminal_toolset():
    config = AgentConfig(
        toolsets=AgentToolsetConfig(
            terminal=["core", "filesystem", "shell"],
            api=["core"],
        )
    )

    assert toolsets_for_source(config, "terminal:local:s1") == {"core", "filesystem", "shell"}
    assert toolsets_for_source(config, "api") == {"core"}


def test_agent_visible_tools_uses_terminal_toolset():
    runtime = AgentRuntime(
        AgentConfig(
            toolsets=AgentToolsetConfig(
                terminal=["core", "filesystem"],
                api=["core"],
            )
        ),
        plugins=None,
        skills=None,
    )
    tools = {item["name"] for item in runtime.visible_tools(source="terminal:local:s1")}

    assert "filesystem.read_file" in tools
    assert "shell.exec" not in tools


def test_terminal_chat_uses_plain_input_by_default(tmp_path):
    session = TerminalChatSession(
        ctx=object(),
        options=TerminalChatOptions(session_id="s1", cwd=Path(tmp_path)),
    )

    assert session._prompt_session is None


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
    from xbot.cli.chat import TerminalRenderer

    renderer = TerminalRenderer()
    renderer.console = None

    assert renderer._format_event(
        AgentRuntimeEvent(task_id="t1", type="llm.started", content={"iteration": 0})
    ) == "[cyan]thinking...[/cyan]"
    assert renderer._format_event(
        AgentRuntimeEvent(task_id="t1", type="llm.started", content={"iteration": 1})
    ) == ""
    assert renderer._should_show_event(
        AgentRuntimeEvent(task_id="t1", type="tool.started", content={"tool": "filesystem.list_dir"})
    ) is False
    assert "OK" in renderer._format_event(
        AgentRuntimeEvent(
            task_id="t1",
            type="tool.completed",
            content={"tool": "filesystem.list_dir"},
        )
    )


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

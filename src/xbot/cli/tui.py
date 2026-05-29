from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import typer

from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.runtime import AgentRuntimeEvent
from xbot.cli.chat import TerminalChatOptions, TerminalChatSession
from xbot.core.config import Settings, load_settings
from xbot.core.logging import configure_terminal_logging
from xbot.runtime.context import build_context
from xbot.storage.bootstrap import ensure_storage_ready

try:  # pragma: no cover - exercised when textual is installed
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal
    from textual.widgets import Footer, Header, Input, RichLog, Static
except Exception:  # pragma: no cover - clean fallback when dependency is absent
    App = None
    ComposeResult = object
    Container = None
    Horizontal = None
    Footer = None
    Header = None
    Input = None
    RichLog = None
    Static = None


class TerminalTuiRenderer:
    def __init__(self, app: "TerminalTuiApp") -> None:
        self.app = app
        self.verbose = app.session.options.verbose
        self.debug = app.session.options.debug

    def welcome(self, options: TerminalChatOptions) -> None:
        self.system(f"session={options.session_id} cwd={options.cwd}")

    def assistant(self, text: str) -> None:
        self.app.write_chat(f"[bold green]assistant[/bold green]\n{text.strip() or '(empty)'}")

    def system(self, text: str) -> None:
        self.app.write_chat(f"[cyan]system>[/cyan] {text}")

    def error(self, text: str) -> None:
        self.app.write_chat(f"[red]error>[/red] {text}")

    def table(self, rows: list[tuple[str, str]]) -> None:
        for key, value in rows:
            self.app.write_chat(f"[cyan]{key}[/cyan]  {value}")

    def tool_list(self, tools: list[dict]) -> None:
        if not tools:
            self.system("no visible tools")
            return
        self.app.write_chat("[bold cyan]visible tools[/bold cyan]")
        for item in tools:
            self.app.write_chat(
                f"- {item['name']} [{item.get('toolset', 'core')}] {item.get('risk_level', '')}"
            )

    def task_list(self, tasks) -> None:
        if not tasks:
            self.system("no background tasks")
            return
        self.app.write_chat("[bold cyan]background tasks[/bold cyan]")
        for item in tasks:
            self.app.write_chat(f"- {item.id} {item.status} {item.description}")

    def event_history(self, events: list[AgentRuntimeEvent], *, limit: int = 20) -> None:
        recent = events[-limit:]
        if not recent:
            self.system("no agent events in this terminal session")
            return
        self.app.write_events(f"[bold cyan]recent agent events ({len(recent)})[/bold cyan]")
        for event in recent:
            self.app.write_events(self._format_event_history(event))

    def background_history(self, records: list[BackgroundTaskRecord], *, limit: int = 20) -> None:
        recent = records[-limit:]
        if not recent:
            self.system("no background task events in this terminal session")
            return
        self.app.write_events(f"[bold cyan]recent background events ({len(recent)})[/bold cyan]")
        for record in recent:
            output = self._background_task_output(record)
            suffix = f" output={output}" if output else ""
            self.app.write_events(f"{record.id[:8]} {record.status} {record.description}{suffix}")

    def background_task(self, record: BackgroundTaskRecord) -> None:
        if record.status not in {"completed", "failed", "cancelled"}:
            return
        self.app.write_events(
            f"[bold]{record.status}[/bold] {record.id[:8]} {record.description} "
            f"{self._background_task_output(record)}"
        )

    def clear(self) -> None:
        self.app.clear_logs()

    async def run_with_status(self, message: str, func):
        self.app.set_status(message)
        try:
            return await func()
        finally:
            self.app.set_status("ready")

    def event(self, event: AgentRuntimeEvent) -> None:
        if not self._should_show_event(event):
            return
        self.app.write_events(self._format_event(event))

    def _should_show_event(self, event: AgentRuntimeEvent) -> bool:
        if event.type.startswith("tool."):
            return True
        if self.verbose and (event.type.startswith("llm.") or event.type.startswith("task.")):
            return True
        return self.debug

    def _format_event(self, event: AgentRuntimeEvent) -> str:
        content = event.content if isinstance(event.content, dict) else {}
        detail = self._event_detail(event)
        if event.type == "tool.started":
            return f"[yellow]tool[/yellow] {detail} started"
        if event.type == "tool.completed":
            return f"[green]tool[/green] {detail} completed"
        if event.type == "tool.failed":
            return f"[red]tool[/red] {detail} failed"
        if event.type == "tool.denied":
            return f"[red]tool[/red] {detail} denied"
        if event.type == "tool.cache_hit":
            return f"[cyan]tool[/cyan] {detail} cache hit"
        if "iteration" in content:
            return f"[cyan]{event.type}[/cyan] iteration={content.get('iteration')}"
        return f"[dim]{event.type} {detail}[/dim]"

    def _format_event_history(self, event: AgentRuntimeEvent) -> str:
        return (
            f"{event.created_at.strftime('%H:%M:%S')} {event.task_id[:8]} "
            f"{event.type} {self._event_detail(event)}"
        )

    def _event_detail(self, event: AgentRuntimeEvent) -> str:
        content = event.content if isinstance(event.content, dict) else {}
        if "tool" in content:
            detail = str(content.get("tool", ""))
            if content.get("error"):
                detail = f"{detail}: {content.get('error')}"
            return detail[:160]
        if content:
            return str(content)[:160]
        return ""

    def _background_task_output(self, record: BackgroundTaskRecord) -> str:
        result = record.result
        if isinstance(result, dict):
            output = result.get("output")
            if output is not None:
                return str(output)[:500]
        if isinstance(result, str):
            return result[:500]
        if record.error:
            return record.error[:500]
        return ""


if App is not None:

    class TerminalTuiApp(App):
        CSS = """
        Screen {
            layout: vertical;
        }

        #body {
            height: 1fr;
        }

        #main {
            width: 2fr;
            height: 1fr;
            border: solid $accent;
        }

        #side {
            width: 1fr;
            height: 1fr;
            border: solid $secondary;
        }

        #status {
            height: 3;
            padding: 0 1;
            border-bottom: solid $secondary;
        }

        #chat-log, #event-log {
            height: 1fr;
            padding: 0 1;
        }

        #input {
            height: 3;
        }
        """

        BINDINGS = [
            ("ctrl+c", "quit", "Quit"),
            ("ctrl+l", "clear", "Clear"),
        ]

        def __init__(self, session: TerminalChatSession) -> None:
            super().__init__()
            self.session = session
            self.session.renderer = TerminalTuiRenderer(self)
            self._started = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                with Container(id="main"):
                    yield RichLog(id="chat-log", markup=True, wrap=True, highlight=True)
                    yield Input(placeholder="输入消息，或 /help /tools /tasks /events /logs /exit", id="input")
                with Container(id="side"):
                    yield Static("status: starting", id="status")
                    yield RichLog(id="event-log", markup=True, wrap=True, highlight=True)
            yield Footer()

        async def on_mount(self) -> None:
            await self.session.start()
            self._started = True
            self.session.renderer.welcome(self.session.options)
            self.set_status("ready")
            self.query_one("#input", Input).focus()

        async def on_unmount(self) -> None:
            if self._started:
                await self.session.stop()
                self._started = False

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            input_widget = event.input
            input_widget.value = ""
            if not text:
                return
            if text.startswith("/"):
                should_continue = await self.session.handle_command(text)
                if not should_continue:
                    self.exit()
                return
            self.write_chat(f"[bold blue]user[/bold blue]\n{text}")
            input_widget.disabled = True
            self.set_status("agent running")
            try:
                await self.session.run_agent_turn(text)
            except Exception as exc:
                self.session.renderer.error(str(exc))
            finally:
                self.set_status("ready")
                input_widget.disabled = False
                input_widget.focus()

        def action_clear(self) -> None:
            self.clear_logs()

        def write_chat(self, text: str) -> None:
            self.query_one("#chat-log", RichLog).write(text)

        def write_events(self, text: str) -> None:
            self.query_one("#event-log", RichLog).write(text)

        def clear_logs(self) -> None:
            self.query_one("#chat-log", RichLog).clear()
            self.query_one("#event-log", RichLog).clear()

        def set_status(self, text: str) -> None:
            self.query_one("#status", Static).update(
                f"status: {text}\nsession: {self.session.options.session_id}\nsource: {self.session.source}"
            )

else:

    class TerminalTuiApp:  # pragma: no cover
        def __init__(self, session: TerminalChatSession) -> None:
            self.session = session


async def run_terminal_tui(
    *,
    config_file: str | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
    verbose: bool = False,
    debug: bool = False,
    fancy_input: bool = False,
    start_runtime: bool = False,
) -> None:
    if App is None:
        raise typer.BadParameter(
            "Textual is not installed. Run: python -m pip install -e \".[dev]\""
        )
    resolved_cwd = Path(cwd or Path.cwd()).resolve()
    configure_terminal_logging(debug=debug, cwd=resolved_cwd)
    settings: Settings = load_settings(config_file)
    await ensure_storage_ready(settings)
    ctx = build_context(settings)
    options = TerminalChatOptions(
        session_id=session_id or str(uuid4()),
        cwd=resolved_cwd,
        verbose=verbose,
        debug=debug,
        fancy_input=fancy_input,
        start_runtime=start_runtime,
    )
    session = TerminalChatSession(ctx, options)
    await TerminalTuiApp(session).run_async()

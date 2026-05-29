from __future__ import annotations

import asyncio
import os
import platform
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import anyio
import typer

from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.runtime import AgentRuntimeEvent
from xbot.core.config import Settings, load_settings
from xbot.core.logging import configure_terminal_logging
from xbot.runtime.context import AppContext, build_context
from xbot.storage.bootstrap import ensure_storage_ready

try:  # pragma: no cover - exercised when optional terminal UI deps are installed
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import FileHistory
except Exception:  # pragma: no cover - fallback path for minimal installs
    PromptSession = None
    WordCompleter = None
    FileHistory = None

try:  # pragma: no cover - exercised when rich is installed
    from rich import box
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # pragma: no cover
    box = None
    Console = None
    Markdown = None
    Panel = None
    Table = None


SLASH_COMMANDS = (
    "/help",
    "/exit",
    "/quit",
    "/q",
    "/status",
    "/tools",
    "/tasks",
    "/task",
    "/replay",
    "/events",
    "/logs",
    "/clear",
    "/new",
)


@dataclass(slots=True)
class TerminalChatOptions:
    session_id: str
    cwd: Path
    verbose: bool = False
    debug: bool = False
    start_runtime: bool = False
    fancy_input: bool = False


class TerminalRenderer:
    def __init__(self, *, verbose: bool = False, debug: bool = False) -> None:
        self.verbose = verbose
        self.debug = debug
        self.console = Console() if Console else None
        self._thinking_shown = False
        self._tool_header_shown = False
        self._tool_lines: list[str] = []

    def begin_turn(self) -> None:
        self._thinking_shown = False
        self._tool_header_shown = False
        self._tool_lines = []

    def welcome(self, options: TerminalChatOptions) -> None:
        if self.console and Panel:
            body = (
                f"[dim]session[/dim] {options.session_id}\n"
                f"[dim]cwd[/dim]     {options.cwd}\n"
                "[dim]/help commands  /exit quit  --verbose details[/dim]"
            )
            self.console.print(
                Panel(
                    body,
                    title="[bold cyan]xbot[/bold cyan]",
                    border_style="cyan",
                    box=box.ROUNDED if box else None,
                    padding=(0, 1),
                )
            )
            return
        typer.echo("xbot terminal chat")
        typer.echo(f"session: {options.session_id}")
        typer.echo(f"cwd: {options.cwd}")
        typer.echo("type /help for commands, /exit to quit")

    def assistant(self, text: str) -> None:
        content = text.strip() if text else "(empty)"
        if self.console and Panel:
            renderable = Markdown(content) if Markdown else content
            self.console.print()
            self.console.print(
                Panel(
                    renderable,
                    title="[bold green]assistant[/bold green]",
                    border_style="green",
                    box=box.ROUNDED if box else None,
                    padding=(0, 1),
                )
            )
            return
        typer.echo(f"\nassistant> {text.strip() if text else '(empty)'}")

    def system(self, text: str) -> None:
        if self.console:
            self.console.print(f"[cyan]system>[/cyan] {text}")
            return
        typer.echo(f"system> {text}")

    def error(self, text: str) -> None:
        if self.console:
            self.console.print(f"[red]error>[/red] {text}")
            return
        typer.secho(f"error> {text}", fg=typer.colors.RED)

    def table(self, rows: list[tuple[str, str]]) -> None:
        if self.console and Table:
            table = Table(show_header=False, box=None)
            table.add_column("key", style="cyan")
            table.add_column("value")
            for key, value in rows:
                table.add_row(key, value)
            self.console.print(table)
            return
        width = max((len(key) for key, _ in rows), default=0)
        for key, value in rows:
            typer.echo(f"{key.ljust(width)}  {value}")

    def tool_list(self, tools: list[dict]) -> None:
        if self.console and Table:
            table = Table(title="visible tools")
            table.add_column("name", style="green")
            table.add_column("toolset", style="cyan")
            table.add_column("risk")
            for item in tools:
                table.add_row(
                    str(item["name"]),
                    str(item.get("toolset", "core")),
                    str(item.get("risk_level", "")),
                )
            self.console.print(table)
            return
        for item in tools:
            typer.echo(f"- {item['name']} [{item.get('toolset', 'core')}]")

    def task_list(self, tasks) -> None:
        if self.console and Table:
            table = Table(title="background tasks")
            table.add_column("id", style="cyan")
            table.add_column("status")
            table.add_column("description")
            for item in tasks:
                table.add_row(item.id, item.status, item.description)
            self.console.print(table)
            return
        for item in tasks:
            typer.echo(f"- {item.id} {item.status} {item.description}")

    def event_history(self, events: list[AgentRuntimeEvent], *, limit: int = 20) -> None:
        recent = events[-limit:]
        if not recent:
            self.system("no agent events in this terminal session")
            return
        if self.console and Table:
            table = Table(title=f"recent agent events ({len(recent)})")
            table.add_column("time", style="cyan")
            table.add_column("task")
            table.add_column("type")
            table.add_column("detail")
            for event in recent:
                table.add_row(
                    event.created_at.strftime("%H:%M:%S"),
                    event.task_id[:8],
                    event.type,
                    self._event_detail(event),
                )
            self.console.print(table)
            return
        for event in recent:
            typer.echo(
                f"- {event.created_at.strftime('%H:%M:%S')} "
                f"{event.task_id[:8]} {event.type} {self._event_detail(event)}"
            )

    def background_history(self, records: list[BackgroundTaskRecord], *, limit: int = 20) -> None:
        recent = records[-limit:]
        if not recent:
            self.system("no background task events in this terminal session")
            return
        if self.console and Table:
            table = Table(title=f"recent background task events ({len(recent)})")
            table.add_column("time", style="cyan")
            table.add_column("id")
            table.add_column("status")
            table.add_column("description")
            table.add_column("result")
            for record in recent:
                table.add_row(
                    self._background_task_time(record),
                    record.id[:8],
                    record.status,
                    record.description,
                    self._background_task_output(record),
                )
            self.console.print(table)
            return
        for record in recent:
            typer.echo(
                f"- {self._background_task_time(record)} {record.id[:8]} "
                f"{record.status} {record.description} {self._background_task_output(record)}"
            )

    def background_task(self, record: BackgroundTaskRecord) -> None:
        if record.status not in {"completed", "failed", "cancelled"}:
            return
        if self.console and Panel:
            style = {
                "completed": "green",
                "failed": "red",
                "cancelled": "yellow",
            }.get(record.status, "cyan")
            body = self._background_task_body(record)
            self.console.print(Panel(body, title=f"background {record.status}", border_style=style))
            return
        typer.echo(f"background> {record.status} {record.id} {record.description}")

    def _background_task_body(self, record: BackgroundTaskRecord) -> str:
        lines = [
            f"id: {record.id}",
            f"description: {record.description}",
        ]
        if record.error:
            lines.append(f"error: {record.error}")
        output = self._background_task_output(record)
        if output:
            lines.append(f"output: {output}")
        return "\n".join(lines)

    def _background_task_output(self, record: BackgroundTaskRecord) -> str:
        result = record.result
        if isinstance(result, dict):
            output = result.get("output")
            if isinstance(output, str):
                return output[:1000]
            if output is not None:
                return str(output)[:1000]
        if isinstance(result, str):
            return result[:1000]
        return ""

    def _background_task_time(self, record: BackgroundTaskRecord) -> str:
        value = record.finished_at or record.started_at or record.created_at
        if value is None:
            return ""
        return value.strftime("%H:%M:%S")

    def clear(self) -> None:
        if self.console:
            self.console.clear()
            return
        os.system("cls" if os.name == "nt" else "clear")

    async def run_with_status(self, message: str, func):
        if self.console:
            with self.console.status(message, spinner="dots"):
                return await func()
        self.system(message)
        return await func()

    def event(self, event: AgentRuntimeEvent) -> None:
        if not self._should_show_event(event):
            return
        text = self._format_event(event)
        if not text:
            return
        if self.console:
            self.console.print(text)
            return
        typer.echo(text)

    def _should_show_event(self, event: AgentRuntimeEvent) -> bool:
        if self.verbose and (event.type.startswith("llm.") or event.type.startswith("task.")):
            return True
        if event.type == "llm.started":
            return True
        if event.type in {"tool.completed", "tool.failed", "tool.denied", "tool.cache_hit"}:
            return True
        if self.verbose and event.type == "tool.started":
            return True
        return self.debug

    def _format_event(self, event: AgentRuntimeEvent) -> str:
        content = event.content if isinstance(event.content, dict) else {}
        tool = str(content.get("tool", ""))
        if event.type == "tool.started":
            if self.verbose:
                return self._tool_line("START", tool, style="dim")
            return ""
        if event.type == "tool.completed":
            return self._tool_line("OK", tool, style="green")
        if event.type == "tool.failed":
            return self._tool_line("ERR", tool, str(content.get("error", "")), style="red")
        if event.type == "tool.denied":
            return self._tool_line("DENY", tool, str(content.get("error", "")), style="red")
        if event.type == "tool.cache_hit":
            return self._tool_line("CACHE", tool, style="cyan")
        if event.type == "llm.started":
            if self.verbose:
                return f"[cyan]llm[/cyan] started iteration={content.get('iteration', '')}"
            if self._thinking_shown:
                return ""
            self._thinking_shown = True
            return "[cyan]thinking...[/cyan]"
        if event.type == "llm.completed":
            return f"[cyan]llm[/cyan] completed iteration={content.get('iteration', '')}"
        if event.type == "task.received":
            return f"[cyan]task[/cyan] received {event.task_id[:8]}"
        if event.type == "task.completed":
            return f"[cyan]task[/cyan] completed {event.task_id[:8]}"
        if self.debug:
            return f"[dim]event> {event.type} {event.content}[/dim]"
        return ""

    def _tool_line(self, status: str, tool: str, detail: str = "", *, style: str) -> str:
        status_text = f"[{style}]{status:<5}[/{style}]"
        line = f"{status_text} {tool}"
        if detail:
            line = f"{line}  [dim]{detail[:180]}[/dim]"
        self._tool_lines.append(line)
        return line

    def _event_detail(self, event: AgentRuntimeEvent) -> str:
        content = event.content if isinstance(event.content, dict) else {}
        if "tool" in content:
            detail = str(content.get("tool", ""))
            if content.get("error"):
                detail = f"{detail}: {content.get('error')}"
            return detail[:160]
        if "iteration" in content:
            return f"iteration={content.get('iteration')}"
        if content:
            return str(content)[:160]
        return ""


class TerminalChatSession:
    def __init__(self, ctx: AppContext, options: TerminalChatOptions) -> None:
        self.ctx = ctx
        self.options = options
        self.renderer = TerminalRenderer(verbose=options.verbose, debug=options.debug)
        self.source = f"terminal:local:{options.session_id}"
        self._prompt_session = self._create_prompt_session()
        self._background_unsubscribe = None
        self._events: list[AgentRuntimeEvent] = []
        self._background_events: list[BackgroundTaskRecord] = []
        self._history_limit = 200

    async def start(self) -> None:
        if self.options.start_runtime:
            await self.ctx.engine.start()
            self._background_unsubscribe = self.ctx.agent.background.subscribe(self._on_background_task)
            return
        if self.ctx.settings.plugins.auto_load:
            await self.ctx.plugins.load_all()
        if self.ctx.settings.skills.auto_load:
            await self.ctx.skills.load_all()
        if self.ctx.settings.agent.enabled:
            await self.ctx.agent.start()
        self._background_unsubscribe = self.ctx.agent.background.subscribe(self._on_background_task)

    async def stop(self) -> None:
        if self._background_unsubscribe:
            self._background_unsubscribe()
            self._background_unsubscribe = None
        if self.options.start_runtime:
            await self.ctx.engine.stop()
            return
        await self.ctx.agent.stop()
        await self.ctx.message_queue.close()
        await self.ctx.storage.close()

    async def run(self) -> None:
        self.renderer.welcome(self.options)
        while True:
            try:
                raw = await self._read_input()
            except (EOFError, KeyboardInterrupt):
                self.renderer.system("bye")
                return
            text = raw.strip()
            if not text:
                continue
            if text.startswith("/"):
                should_continue = await self.handle_command(text)
                if not should_continue:
                    return
                continue
            await self.run_agent_turn(text)

    async def run_agent_turn(self, text: str) -> None:
        begin_turn = getattr(self.renderer, "begin_turn", None)
        if begin_turn:
            begin_turn()
        event_queue: asyncio.Queue[AgentRuntimeEvent] = asyncio.Queue()

        async def on_event(event: AgentRuntimeEvent) -> None:
            await event_queue.put(event)

        unsubscribe = self.ctx.agent.subscribe_events(on_event)
        started = time.monotonic()
        task = asyncio.create_task(
            self.ctx.agent.run_task(self.build_agent_input(text), source=self.source),
            name=f"xbot-terminal-agent-{self.options.session_id}",
        )
        try:
            while not task.done() or not event_queue.empty():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                self._remember_event(event)
                self.renderer.event(event)
            result = await task
        finally:
            unsubscribe()
        if self.options.verbose:
            elapsed = time.monotonic() - started
            self.renderer.system(f"task_id={result.task_id} elapsed={elapsed:.2f}s")
        self.renderer.assistant(result.output)

    async def handle_command(self, command_line: str) -> bool:
        command, _, arg = command_line.partition(" ")
        command = command.lower()
        arg = arg.strip()
        if command in {"/exit", "/quit", "/q"}:
            self.renderer.system("bye")
            return False
        if command == "/help":
            self.renderer.system(
                "/help /exit /status /tools /tasks /task <id> /replay <id> "
                "/events [n] /logs [n] /clear /new"
            )
            return True
        if command == "/status":
            self.renderer.table(
                [
                    ("runtime", self.ctx.engine.status().state),
                    ("llm", str(self.ctx.agent.llm_status())),
                    ("mcp", str(self.ctx.agent.mcp_status())),
                    ("source", self.source),
                ]
            )
            return True
        if command == "/tools":
            tools = self.ctx.agent.visible_tools(source=self.source)
            self.renderer.tool_list(tools)
            return True
        if command == "/tasks":
            tasks = await self.ctx.agent.list_background_tasks()
            if not tasks:
                self.renderer.system("no background tasks")
                return True
            self.renderer.task_list(tasks)
            return True
        if command == "/events":
            self.renderer.event_history(self._events, limit=self._parse_limit(arg))
            return True
        if command == "/logs":
            limit = self._parse_limit(arg)
            self.renderer.event_history(self._events, limit=limit)
            self.renderer.background_history(self._background_events, limit=limit)
            return True
        if command == "/clear":
            self.renderer.clear()
            return True
        if command == "/task":
            if not arg:
                self.renderer.error("usage: /task <id>")
                return True
            task = await self.ctx.agent.get_background_task(arg)
            if not task:
                self.renderer.error(f"task not found: {arg}")
                return True
            self.renderer.table(
                [
                    ("id", task.id),
                    ("status", task.status),
                    ("description", task.description),
                    ("error", task.error or ""),
                ]
            )
            return True
        if command == "/replay":
            if not arg:
                self.renderer.error("usage: /replay <id>")
                return True
            try:
                task = await self.ctx.agent.replay_background_task(arg)
            except Exception as exc:
                self.renderer.error(str(exc))
                return True
            self.renderer.system(f"replayed task: {task.id}")
            return True
        if command == "/new":
            self.options.session_id = str(uuid4())
            self.source = f"terminal:local:{self.options.session_id}"
            self.renderer.system(f"new session: {self.options.session_id}")
            return True
        self.renderer.error(f"unknown command: {command}")
        return True

    def _remember_event(self, event: AgentRuntimeEvent) -> None:
        self._events.append(event)
        if len(self._events) > self._history_limit:
            del self._events[: len(self._events) - self._history_limit]

    async def _on_background_task(self, record: BackgroundTaskRecord) -> None:
        self._background_events.append(record)
        if len(self._background_events) > self._history_limit:
            del self._background_events[: len(self._background_events) - self._history_limit]
        self.renderer.background_task(record)

    def _parse_limit(self, value: str, *, default: int = 20) -> int:
        if not value:
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(1, min(parsed, self._history_limit))

    async def _read_input(self) -> str:
        if self._prompt_session is None:
            return await anyio.to_thread.run_sync(lambda: typer.prompt("\nxbot", prompt_suffix="> "))
        return await anyio.to_thread.run_sync(lambda: self._prompt_session.prompt("\nxbot> "))

    def _create_prompt_session(self):
        if not self.options.fancy_input or PromptSession is None:
            return None
        history_path = self.options.cwd / ".xbot_terminal_history"
        completer = WordCompleter(SLASH_COMMANDS, ignore_case=True) if WordCompleter else None
        history = FileHistory(str(history_path)) if FileHistory else None
        return PromptSession(completer=completer, history=history)

    def build_agent_input(self, content: str) -> str:
        return build_terminal_agent_input(
            content,
            session_id=self.options.session_id,
            cwd=self.options.cwd,
        )


def build_terminal_agent_input(content: str, *, session_id: str, cwd: Path) -> str:
    return (
        "Terminal message received.\n"
        "platform: terminal\n"
        "adapter: cli\n"
        f"session_id: {session_id}\n"
        f"cwd: {cwd}\n"
        f"shell: {os.environ.get('ComSpec') or os.environ.get('SHELL') or ''}\n"
        f"os: {platform.platform()}\n"
        f"hostname: {socket.gethostname()}\n"
        f"python_venv: {os.environ.get('VIRTUAL_ENV') or ''}\n"
        f"content: {content}\n"
        "Use terminal context as the user's local development environment. "
        "Use tools when the request depends on current files, runtime state, or system state. "
        "Reply in Chinese unless the user asks for another language."
    )


async def run_terminal_chat(
    *,
    config_file: str | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
    verbose: bool = False,
    debug: bool = False,
    fancy_input: bool = False,
    start_runtime: bool = False,
) -> None:
    settings: Settings = load_settings(config_file)
    configure_terminal_logging(debug=debug, cwd=Path(cwd or os.getcwd()).resolve())
    await ensure_storage_ready(settings)
    ctx = build_context(settings)
    options = TerminalChatOptions(
        session_id=session_id or str(uuid4()),
        cwd=Path(cwd or os.getcwd()).resolve(),
        verbose=verbose,
        debug=debug,
        fancy_input=fancy_input,
        start_runtime=start_runtime,
    )
    session = TerminalChatSession(ctx, options)
    await session.start()
    try:
        await session.run()
    finally:
        await session.stop()

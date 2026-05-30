from __future__ import annotations

import asyncio
from contextlib import suppress
import os
import platform
import sys
import socket
import time
from dataclasses import dataclass
from datetime import datetime
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
    from prompt_toolkit.patch_stdout import patch_stdout
except Exception:  # pragma: no cover - fallback path for minimal installs
    PromptSession = None
    WordCompleter = None
    FileHistory = None
    patch_stdout = None

try:  # pragma: no cover - exercised when rich is installed
    from rich import box
    from rich.align import Align
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover
    box = None
    Align = None
    Columns = None
    Console = None
    Group = None
    Live = None
    Markdown = None
    Panel = None
    Table = None
    Text = None


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


@dataclass(slots=True)
class ToolProgressRecord:
    name: str
    status: str
    started_at: float | None = None
    finished_at: float | None = None
    error: str = ""
    cache_hit: bool = False
    input_preview: str = ""
    output_preview: str = ""

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return max(0.0, self.finished_at - self.started_at)


@dataclass(slots=True)
class TerminalDisplayState:
    started_at: float
    task_id: str = ""
    thinking: bool = False
    llm_iterations: int = 0
    llm_started_at: float | None = None
    llm_elapsed_seconds: float = 0.0
    usage_total_tokens: int = 0
    input_chars: int = 0
    output_chars: int = 0
    tools: list[ToolProgressRecord] | None = None

    def __post_init__(self) -> None:
        if self.tools is None:
            self.tools = []


class ToolProgressRenderer:
    def __init__(self) -> None:
        self._running: dict[str, list[ToolProgressRecord]] = {}

    def consume(self, event: AgentRuntimeEvent, state: TerminalDisplayState) -> None:
        content = event.content if isinstance(event.content, dict) else {}
        tool = str(content.get("tool") or "")
        if not tool:
            return
        now = time.monotonic()
        if event.type == "tool.started":
            record = ToolProgressRecord(
                name=tool,
                status="running",
                started_at=now,
                input_preview=self._preview(content.get("input")),
            )
            self._running.setdefault(tool, []).append(record)
            return
        record = self._pop_running(tool)
        if record is None:
            record = ToolProgressRecord(name=tool, status="running", started_at=None)
        record.finished_at = now
        if event.type == "tool.completed":
            record.status = "ok"
            record.output_preview = self._preview(content.get("output"))
        elif event.type == "tool.failed":
            record.status = "error"
            record.error = str(content.get("error") or "")
        elif event.type == "tool.denied":
            record.status = "denied"
            record.error = str(content.get("error") or "")
        elif event.type == "tool.cache_hit":
            record.status = "cache"
            record.cache_hit = True
        else:
            return
        state.tools.append(record)

    def _preview(self, value: object) -> str:
        if value is None:
            return ""
        text = value if isinstance(value, str) else str(value)
        return text.replace("\n", " ")[:220]

    def _pop_running(self, tool: str) -> ToolProgressRecord | None:
        records = self._running.get(tool)
        if not records:
            return None
        record = records.pop(0)
        if not records:
            self._running.pop(tool, None)
        return record


class TerminalRenderer:
    def __init__(self, *, verbose: bool = False, debug: bool = False) -> None:
        self.verbose = verbose
        self.debug = debug
        self.console = Console() if Console else None
        self._thinking_shown = False
        self._tool_header_shown = False
        self._tool_lines: list[str] = []
        self._display_state = TerminalDisplayState(started_at=time.monotonic())
        self._tool_progress = ToolProgressRenderer()
        self._stream_buffer = ""
        self._stream_live = None
        self._plain_stream_started = False
        self._stream_block_open = False
        self._stream_line_open = False

    def begin_turn(self) -> None:
        self._stop_stream()
        self._thinking_shown = False
        self._tool_header_shown = False
        self._tool_lines = []
        self._display_state = TerminalDisplayState(started_at=time.monotonic())
        self._tool_progress = ToolProgressRenderer()
        self._stream_buffer = ""
        self._plain_stream_started = False
        self._stream_block_open = False
        self._stream_line_open = False

    def welcome(
        self,
        options: TerminalChatOptions,
        *,
        overview_rows: list[tuple[str, str]] | None = None,
        home_sections: dict[str, list[str]] | None = None,
    ) -> None:
        if self.console and Panel and Table and Group and Text:
            self.console.print(
                Panel(
                    self._welcome_body(options, overview_rows or [], home_sections or {}),
                    title="[bold cyan]xbot terminal[/bold cyan]",
                    subtitle="[dim]/help commands  /exit quit  --verbose details[/dim]",
                    border_style="cyan",
                    box=box.ROUNDED if box else None,
                    padding=(0, 1),
                )
            )
            self.console.print("\n[bold]Welcome to xbot terminal.[/bold] Type your message or /help.")
            self.console.print("[dim]Tip: xbot chat --fancy-input enables multiline input and history.[/dim]")
            return
        typer.echo("xbot terminal chat")
        typer.echo(f"session: {options.session_id}")
        typer.echo(f"cwd: {options.cwd}")
        typer.echo("type /help for commands, /exit to quit")

    def _welcome_body(
        self,
        options: TerminalChatOptions,
        overview_rows: list[tuple[str, str]],
        home_sections: dict[str, list[str]],
    ):
        logo = Text.from_markup(self._xbot_logo_markup())
        left = Table.grid(padding=(0, 1))
        left.add_column(justify="left")
        left.add_row(logo)
        left.add_row("")
        left.add_row("[green][READY][/green] local agent console")
        model = dict(overview_rows).get("model", "unknown")
        left.add_row(f"[cyan]{model}[/cyan]")
        left.add_row(f"[dim]Session:[/dim] {options.session_id[:8]}")
        left.add_row(f"[dim]Cwd:[/dim]     {self._fit_text(str(options.cwd), 26)}")
        counts = dict(overview_rows)
        left.add_row(
            f"[dim]{counts.get('tools_count', '0')} tools {self._sep()} "
            f"{counts.get('skills_count', '0')} skills[/dim]"
        )

        right = Table.grid(padding=(0, 2))
        right.add_column(ratio=1)
        right.add_row("[bold]Available Tools[/bold]")
        for line in home_sections.get("tools", [])[:9]:
            right.add_row(line)
        if len(home_sections.get("tools", [])) > 9:
            right.add_row(f"[dim](and {len(home_sections['tools']) - 9} more toolsets...)[/dim]")
        right.add_row("")
        right.add_row("[bold]Available Skills[/bold]")
        for line in home_sections.get("skills", [])[:13]:
            right.add_row(line)
        if len(home_sections.get("skills", [])) > 13:
            right.add_row(f"[dim](and {len(home_sections['skills']) - 13} more skills...)[/dim]")
        right.add_row("")
        right.add_row(
            f"[dim]{counts.get('tools_count', '0')} tools {self._sep()} "
            f"{counts.get('skills_count', '0')} skills {self._sep()} /help for commands[/dim]"
        )

        layout = Table.grid(expand=True)
        layout.add_column(width=38)
        layout.add_column(ratio=4)
        layout.add_row(left, right)
        return layout

    def _sep(self) -> str:
        return "·" if self._unicode_output() else "|"

    def _fit_text(self, value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return "..." + value[-max(0, width - 3):]

    def _xbot_logo_markup(self) -> str:
        if self._unicode_output():
            return (
                "[bold cyan]          _           _[/bold cyan]\n"
                "[bold cyan]__  _____| |__   ___ | |_[/bold cyan]\n"
                "[bold cyan]\\ \\/ / _ \\ '_ \\ / _ \\| __|[/bold cyan]\n"
                "[bold cyan] >  <  __/ |_) | (_) | |_[/bold cyan]\n"
                "[bold cyan]/_/\\_\\___|_.__/ \\___/ \\__|[/bold cyan]\n"
                "[dim]    async agent backend[/dim]"
            )
        return (
            "[bold cyan]          _           _[/bold cyan]\n"
            "[bold cyan]__  _____| |__   ___ | |_[/bold cyan]\n"
            "[bold cyan]\\ \\/ / _ \\ '_ \\ / _ \\| __|[/bold cyan]\n"
            "[bold cyan] >  <  __/ |_) | (_) | |_[/bold cyan]\n"
            "[bold cyan]/_/\\_\\___|_.__/ \\___/ \\__|[/bold cyan]\n"
            "[dim]    async agent backend[/dim]"
        )

    def overview(self, rows: list[tuple[str, str]]) -> None:
        if self.console and Table:
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("key", style="cyan")
            table.add_column("value")
            for key, value in rows:
                table.add_row(key, value)
            self.console.print(table)
            return
        self.table(rows)

    def assistant(self, text: str) -> None:
        content = text.strip() if text else "(empty)"
        streamed = self._stream_buffer.strip()
        if streamed:
            self._stop_stream()
            if self._same_assistant_output(streamed, content):
                if not self.console:
                    typer.echo()
                return
        if self.console:
            self._assistant_block(content)
            return
        self._plain_assistant_block(content)

    def user(self, text: str) -> None:
        content = text.strip() if text else "(empty)"
        if self.console:
            self.turn_separator(short=True)
            bullet = "●" if self._unicode_output() else ">"
            self.console.print(f"\n[bold blue]{bullet}[/bold blue] {content}")
            return
        self.turn_separator(short=True)
        typer.echo(f"\n> {content}")

    def turn_separator(self, *, short: bool = False) -> None:
        width = 40 if short else self._block_width()
        if self.console:
            char = "─" if self._unicode_output() else "-"
            self.console.print(f"[dim]{char * width}[/dim]")
            return
        typer.echo("-" * width)

    def _assistant_block(self, content: str) -> None:
        self._open_assistant_block()
        self._print_assistant_content(content)
        self._close_assistant_block()

    def _plain_assistant_block(self, content: str) -> None:
        width = self._block_width()
        typer.echo()
        typer.echo(self._block_top("xbot", width))
        for line in content.splitlines() or [""]:
            typer.echo(f"    {line}")
        typer.echo(self._block_bottom(width))

    def _open_assistant_block(self) -> None:
        if not self.console:
            self._plain_stream_started = True
            typer.echo()
            typer.echo(self._block_top("xbot", self._block_width()))
            return
        self.console.print()
        self.console.print(f"[green]{self._block_top('xbot', self._block_width())}[/green]")

    def _close_assistant_block(self) -> None:
        if not self.console:
            typer.echo(self._block_bottom(self._block_width()))
            return
        self.console.print(f"[green]{self._block_bottom(self._block_width())}[/green]")

    def _print_assistant_content(self, content: str) -> None:
        lines = content.splitlines() or [""]
        if not self.console:
            for line in lines:
                typer.echo(f"    {line}")
            return
        for line in lines:
            self.console.print(f"    {line}", markup=False, highlight=False)

    def _block_width(self) -> int:
        width = self.console.width if self.console else 80
        return max(36, min(width, 100))

    def _block_top(self, label: str, width: int) -> str:
        label_text = f" {label} "
        if self._unicode_output():
            fill = max(width - len(label_text) - 3, 0)
            return f"╭─{label_text}{'─' * fill}╮"
        fill = max(width - len(label_text) - 3, 0)
        return f"+-{label_text}{'-' * fill}+"

    def _block_bottom(self, width: int) -> str:
        if self._unicode_output():
            return f"╰{'─' * (width - 2)}╯"
        return f"+{'-' * (width - 2)}+"

    def _unicode_output(self) -> bool:
        encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
        return "utf" in encoding

    def system(self, text: str) -> None:
        if self.console and len(text) <= 80 and "\n" not in text:
            self.console.print(f"[cyan]system[/cyan] [dim]{text}[/dim]")
            return
        if self.console and Panel:
            self.console.print(
                Panel(
                    text,
                    title="[bold cyan]system[/bold cyan]",
                    border_style="cyan",
                    box=box.SIMPLE if box else None,
                    padding=(0, 1),
                )
            )
            return
        typer.echo(f"\n[system] {text}")

    def error(self, text: str) -> None:
        if self.console and Panel:
            self.console.print(
                Panel(
                    text,
                    title="[bold red]error[/bold red]",
                    border_style="red",
                    box=box.SIMPLE if box else None,
                    padding=(0, 1),
                )
            )
            return
        typer.secho(f"\n[error] {text}", fg=typer.colors.RED)

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
        if event.type == "llm.delta":
            self._stream_delta(event)
            return
        self._capture_event(event)
        if not self._should_show_event(event):
            return
        text = self._format_event(event)
        if not text:
            return
        if self.console:
            self.console.print(text)
            return
        typer.echo(text)

    def finish_turn(self) -> None:
        if self._stream_buffer:
            self._stop_stream()
        if not self.console or not Panel:
            return
        body = self._activity_body()
        if not body:
            return
        self.console.print(
            Panel(
                body,
                title="[bold cyan]activity[/bold cyan]",
                border_style="cyan",
                box=box.ROUNDED if box else None,
                padding=(0, 1),
            )
        )

    def status_bar(
        self,
        *,
        model: str,
        context_window: int,
        elapsed_seconds: float,
        output_text: str = "",
    ) -> None:
        used = self._context_used_tokens(output_text)
        percent = 0 if context_window <= 0 else min(100, round((used / context_window) * 100))
        bar = self._usage_bar(percent)
        line = (
            f"{model} {self._sep()} {self._format_token_count(used)}/"
            f"{self._format_token_count(context_window)} {self._sep()} {bar} {percent}% "
            f"{self._sep()} {self._format_duration(elapsed_seconds)} "
            f"{self._sep()} {self._timer_label()} {self._format_duration(self._display_state.llm_elapsed_seconds)}"
        )
        self.turn_separator()
        if self.console:
            self.console.print(f"[cyan]{line}[/cyan]")
            self.turn_separator()
            return
        typer.echo(line)
        self.turn_separator()

    def _capture_event(self, event: AgentRuntimeEvent) -> None:
        content = event.content if isinstance(event.content, dict) else {}
        if event.task_id:
            self._display_state.task_id = event.task_id
        if event.type == "llm.started":
            self._display_state.thinking = True
            self._display_state.llm_iterations += 1
            self._display_state.llm_started_at = time.monotonic()
        if event.type == "llm.completed":
            started = self._display_state.llm_started_at
            if started is not None:
                self._display_state.llm_elapsed_seconds += max(0.0, time.monotonic() - started)
            usage = content.get("usage") if isinstance(content, dict) else None
            if isinstance(usage, dict):
                total = usage.get("total_tokens") or usage.get("total")
                if isinstance(total, int):
                    self._display_state.usage_total_tokens = max(
                        self._display_state.usage_total_tokens,
                        total,
                    )
        if event.type == "task.received" and isinstance(event.content, str):
            self._display_state.input_chars = max(
                self._display_state.input_chars,
                len(event.content),
            )
        if event.type == "task.completed" and isinstance(event.content, str):
            self._display_state.output_chars = max(
                self._display_state.output_chars,
                len(event.content),
            )
        if event.type.startswith("tool."):
            self._tool_progress.consume(event, self._display_state)

    def _stream_delta(self, event: AgentRuntimeEvent) -> None:
        content = event.content if isinstance(event.content, dict) else {}
        text = str(content.get("text") or "")
        if not text:
            return
        self._stream_buffer += text
        self._emit_stream_text(text)

    def _stop_stream(self) -> None:
        if self._stream_live is not None:
            self._stream_live.stop()
            self._stream_live = None
        if self._stream_block_open:
            if self._stream_line_open:
                if self.console:
                    self.console.print()
                else:
                    typer.echo()
                self._stream_line_open = False
            self._close_assistant_block()
            self._stream_block_open = False

    def _emit_stream_text(self, text: str) -> None:
        if not self._stream_block_open:
            self._open_assistant_block()
            self._stream_block_open = True
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if index > 0:
                if self.console:
                    self.console.print()
                else:
                    typer.echo()
                self._stream_line_open = False
            if not part:
                continue
            prefix = "    " if not self._stream_line_open else ""
            if self.console:
                self.console.print(prefix + part, end="", markup=False, highlight=False)
            else:
                typer.echo(prefix + part, nl=False)
            self._stream_line_open = True

    def _same_assistant_output(self, streamed: str, final: str) -> bool:
        streamed_text = streamed.strip()
        final_text = final.strip()
        if streamed_text == final_text:
            return True
        if not streamed_text or not final_text:
            return False
        return (
            final_text in streamed_text
            or streamed_text in final_text
            or streamed_text.endswith(final_text)
            or final_text.endswith(streamed_text)
        )

    def _activity_body(self) -> str:
        state = self._display_state
        elapsed = time.monotonic() - state.started_at
        lines: list[str] = []
        task = state.task_id[:8] if state.task_id else ""
        header = f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]"
        if task:
            header += f"  [dim]task[/dim] {task}"
        header += f"  [dim]elapsed[/dim] {elapsed:.1f}s"
        lines.append(header)
        if state.thinking:
            iterations = max(1, state.llm_iterations)
            lines.append(f"[cyan]thinking[/cyan] {iterations} llm call{'s' if iterations != 1 else ''}")
        for record in state.tools:
            lines.append(self._format_tool_record(record))
        return "\n".join(lines)

    def _context_used_tokens(self, output_text: str) -> int:
        if self._display_state.usage_total_tokens > 0:
            return self._display_state.usage_total_tokens
        chars = self._display_state.input_chars + self._display_state.output_chars + len(output_text or "")
        return max(1, int(chars / 4))

    def _usage_bar(self, percent: int, *, width: int = 10) -> str:
        filled = max(0, min(width, round((percent / 100) * width)))
        if self._unicode_output():
            return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"
        return "[" + ("#" * filled) + ("." * (width - filled)) + "]"

    def _format_token_count(self, value: int) -> str:
        if value >= 1_000_000:
            number = value / 1_000_000
            return f"{number:.1f}M".replace(".0M", "M")
        if value >= 1000:
            number = value / 1000
            return f"{number:.1f}K".replace(".0K", "K")
        return str(value)

    def _format_duration(self, seconds: float) -> str:
        seconds = max(0.0, seconds)
        if seconds >= 60:
            minutes = int(seconds // 60)
            remainder = int(seconds % 60)
            return f"{minutes}m{remainder:02d}s" if remainder else f"{minutes}m"
        return f"{seconds:.0f}s" if seconds >= 10 else f"{seconds:.1f}s"

    def _timer_label(self) -> str:
        return "⏲" if self._unicode_output() else "llm"

    def _format_tool_record(self, record: ToolProgressRecord) -> str:
        status_styles = {
            "ok": ("OK", "green"),
            "error": ("ERR", "red"),
            "denied": ("DENY", "red"),
            "cache": ("CACHE", "cyan"),
        }
        label, style = status_styles.get(record.status, (record.status.upper(), "dim"))
        duration = ""
        if record.duration_seconds is not None:
            duration = f" [dim]{record.duration_seconds:.2f}s[/dim]"
        detail = f" [dim]{record.error[:180]}[/dim]" if record.error else ""
        line = f"[{style}]{label:<5}[/{style}] {record.name}{duration}{detail}"
        if self.verbose and record.input_preview:
            line += f"\n      [dim]input  {record.input_preview}[/dim]"
        if self.debug and record.output_preview:
            line += f"\n      [dim]output {record.output_preview}[/dim]"
        return line

    def _should_show_event(self, event: AgentRuntimeEvent) -> bool:
        if self.verbose and (event.type.startswith("llm.") or event.type.startswith("task.")):
            return True
        if event.type in {"tool.completed", "tool.failed", "tool.denied", "tool.cache_hit"}:
            return self.verbose
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
        self._turns = 0

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
        self.renderer.welcome(
            self.options,
            overview_rows=self._overview_rows(),
            home_sections=self._home_sections(),
        )
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
            try:
                await self.run_agent_turn(text)
            except KeyboardInterrupt:
                self.renderer.system("current task cancelled")

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
                if event.type != "llm.delta":
                    self._remember_event(event)
                self.renderer.event(event)
            result = await task
        except (KeyboardInterrupt, asyncio.CancelledError):
            task.cancel()
            with suppress(Exception, asyncio.CancelledError):
                await task
            self.renderer.system("current task cancelled")
            return
        finally:
            unsubscribe()
        if self.options.verbose:
            elapsed = time.monotonic() - started
            self.renderer.system(f"task_id={result.task_id} elapsed={elapsed:.2f}s")
        self._turns += 1
        self.renderer.assistant(result.output)
        status_bar = getattr(self.renderer, "status_bar", None)
        if status_bar:
            status_bar(
                model=self._model_label(),
                context_window=self._context_window_tokens(),
                elapsed_seconds=time.monotonic() - started,
                output_text=result.output,
            )
        finish_turn = getattr(self.renderer, "finish_turn", None)
        if finish_turn and self.options.verbose:
            finish_turn()

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
                "/events [n] /logs [n] /memory [user] "
                "/curator <status|report|apply|run|archive|restore|pin|unpin> "
                "/skills agent /clear /new"
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
        if command == "/memory":
            target = arg.strip() or "memory"
            if target not in {"memory", "user"}:
                self.renderer.error("usage: /memory [memory|user]")
                return True
            result = self.ctx.agent.memory.read_curated(target)
            rows = [("target", target), ("usage", result.get("usage", ""))]
            for index, entry in enumerate(result.get("entries", []), start=1):
                rows.append((str(index), entry))
            self.renderer.table(rows)
            return True
        if command == "/skills" and arg.strip() == "agent":
            if not self.ctx.skills or not hasattr(self.ctx.skills, "manage"):
                self.renderer.error("skill manager is not available")
                return True
            result = await self.ctx.skills.manage({"action": "usage"})
            usage = result.get("usage", {})
            if not usage:
                self.renderer.system("no agent-owned skills")
                return True
            rows = [
                (
                    name,
                    f"{item.get('state', 'active')} pinned={bool(item.get('pinned'))} "
                    f"use={item.get('use_count', 0)} patch={item.get('patch_count', 0)}",
                )
                for name, item in sorted(usage.items())
            ]
            self.renderer.table(rows)
            return True
        if command == "/curator":
            await self._handle_curator_command(arg)
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
            with suppress(Exception):
                await self.ctx.agent.flush_memory(reason="/new")
            with suppress(Exception):
                self.ctx.agent.clear_session_history(self.source)
            self.options.session_id = str(uuid4())
            self.source = f"terminal:local:{self.options.session_id}"
            self.renderer.system(f"new session: {self.options.session_id}")
            return True
        self.renderer.error(f"unknown command: {command}")
        return True

    async def _handle_curator_command(self, arg: str) -> None:
        parts = arg.split()
        action = parts[0] if parts else "status"
        name = parts[1] if len(parts) > 1 else ""
        if action == "report":
            use_llm = "--no-llm" not in parts
            report = await self.ctx.agent.generate_curator_report(use_llm=use_llm)
            summary = report.get("summary", {})
            rows = [
                ("report", str(report.get("id", ""))),
                ("skills", str(summary.get("skill_count", 0))),
                ("proposals", str(summary.get("proposal_count", 0))),
            ]
            for item in report.get("proposals", []):
                rows.append(
                    (
                        str(item.get("id")),
                        (
                            f"{item.get('action')} {item.get('target')}"
                            f" <- {item.get('source_skill') or '-'} "
                            f"confidence={item.get('confidence')} {item.get('reason')}"
                        ),
                    )
                )
            self.renderer.table(rows)
            return
        if action == "apply":
            proposal_ids = parts[1:] if len(parts) > 1 else []
            try:
                result = await self.ctx.agent.apply_curator_report(proposal_ids=proposal_ids or None)
            except Exception as exc:
                self.renderer.error(str(exc))
                return
            rows = [("report", str(result.get("report_id", "")))]
            for item in result.get("results", []):
                rows.append((str(item.get("id")), f"{item.get('status')} {item.get('reason', '')}"))
            self.renderer.table(rows)
            return
        if action == "run":
            self.renderer.table(list((await self.ctx.agent.run_curator()).items()))
            return
        if action == "status":
            if not self.ctx.skills or not hasattr(self.ctx.skills, "manage"):
                self.renderer.error("skill manager is not available")
                return
            usage = (await self.ctx.skills.manage({"action": "usage"})).get("usage", {})
            counts: dict[str, int] = {}
            for item in usage.values():
                counts[str(item.get("state") or "active")] = counts.get(str(item.get("state") or "active"), 0) + 1
            self.renderer.table(sorted(counts.items()) or [("agent skills", "0")])
            return
        if action in {"archive", "restore", "pin", "unpin"}:
            if not name:
                self.renderer.error(f"usage: /curator {action} <skill>")
                return
            try:
                result = await self.ctx.skills.manage({"action": action, "name": name})
            except Exception as exc:
                self.renderer.error(str(exc))
                return
            self.renderer.table(list(result.items()))
            return
        self.renderer.error("usage: /curator [status|report|apply|run|archive|restore|pin|unpin]")

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
            return await anyio.to_thread.run_sync(
                lambda: typer.prompt(f"\n{self._prompt_label()}", prompt_suffix=" ")
            )
        return await anyio.to_thread.run_sync(self._prompt_input)

    def _prompt_input(self) -> str:
        if self._prompt_session is None:
            return typer.prompt(f"\n{self._prompt_label()}", prompt_suffix=" ")
        if patch_stdout is None:
            return self._prompt_session.prompt(f"\n{self._prompt_label()} ")
        with patch_stdout(raw=True):
            return self._prompt_session.prompt(f"\n{self._prompt_label()} ")

    def _prompt_label(self) -> str:
        encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
        return "❯" if "utf" in encoding else "xbot>"

    def _create_prompt_session(self):
        if not self.options.fancy_input or PromptSession is None:
            return None
        history_path = self.options.cwd / ".xbot_terminal_history"
        completer = WordCompleter(SLASH_COMMANDS, ignore_case=True) if WordCompleter else None
        history = FileHistory(str(history_path)) if FileHistory else None
        return PromptSession(
            completer=completer,
            history=history,
            multiline=True,
            bottom_toolbar=self._bottom_toolbar,
        )

    def build_agent_input(self, content: str) -> str:
        return build_terminal_agent_input(
            content,
            session_id=self.options.session_id,
            cwd=self.options.cwd,
        )

    def _overview_rows(self) -> list[tuple[str, str]]:
        tools = self.ctx.agent.visible_tools(source=self.source)
        plugins = self.ctx.plugins.list_plugins()
        skills = self.ctx.skills.list_skills()
        enabled_plugins = [item for item in plugins if item.get("enabled")]
        enabled_skills = [item for item in skills if item.get("enabled")]
        model = self.ctx.agent.llm_status()
        return [
            ("model", f"{model.get('provider', 'unknown')}:{model.get('model', 'unknown')}"),
            ("tools", self._count_with_preview(tools, "name")),
            ("tools_count", str(len(tools))),
            ("plugins", self._count_with_preview(enabled_plugins, "name")),
            ("skills", self._count_with_preview(enabled_skills, "name")),
            ("skills_count", str(len(enabled_skills))),
        ]

    def _home_sections(self) -> dict[str, list[str]]:
        tools = self.ctx.agent.visible_tools(source=self.source)
        toolsets: dict[str, list[str]] = {}
        for item in tools:
            toolsets.setdefault(str(item.get("toolset") or "core"), []).append(str(item.get("name")))
        tool_lines = []
        for name in sorted(toolsets):
            tool_lines.append(f"[cyan]{name}[/cyan]: {self._comma_preview(toolsets[name], limit=3)}")

        plugins = [item for item in self.ctx.plugins.list_plugins() if item.get("enabled")]
        skills = [item for item in self.ctx.skills.list_skills() if item.get("enabled")]
        skill_lines = [f"[cyan]plugins[/cyan]: {self._comma_preview([str(item.get('name')) for item in plugins], limit=4)}"]
        skill_lines.extend(str(item.get("name")) for item in skills[:12])
        return {"tools": tool_lines, "skills": skill_lines}

    def _comma_preview(self, names: list[str], *, limit: int) -> str:
        cleaned = [name for name in names if name]
        preview = ", ".join(cleaned[:limit])
        if len(cleaned) > limit:
            return f"{preview}, ..."
        return preview or "-"

    def _bottom_toolbar(self) -> str:
        model = self.ctx.agent.llm_status() if getattr(self.ctx, "agent", None) else {}
        model_name = model.get("model", "unknown")
        return (
            f"session {self.options.session_id[:8]} | cwd {self.options.cwd} | "
            f"model {model_name} | turns {self._turns} | Enter newline, Esc+Enter submit"
        )

    def _model_label(self) -> str:
        status = self.ctx.agent.llm_status() if getattr(self.ctx, "agent", None) else {}
        return str(status.get("model") or status.get("provider") or "unknown")

    def _context_window_tokens(self) -> int:
        status = self.ctx.agent.llm_status() if getattr(self.ctx, "agent", None) else {}
        configured = status.get("context_window_tokens")
        if isinstance(configured, int) and configured > 0:
            return configured
        model = str(status.get("model") or "").lower()
        if "minimax-m2" in model or "mimo" in model:
            return 1_000_000
        if "gpt-4.1" in model or "gpt-4o" in model:
            return 128_000
        if "claude" in model:
            return 200_000
        return 128_000

    def _count_with_preview(self, items: list[dict], key: str) -> str:
        names = [str(item.get(key) or "") for item in items if item.get(key)]
        preview = ", ".join(names[:5])
        suffix = "" if len(names) <= 5 else f", +{len(names) - 5}"
        return f"{len(names)}" + (f"  {preview}{suffix}" if preview else "")


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
    await session.renderer.run_with_status("starting xbot terminal...", session.start)
    try:
        await session.run()
    finally:
        await session.stop()

from __future__ import annotations

import os
import platform
import subprocess

import uvicorn
import typer
from alembic import command
from alembic.config import Config
from pathlib import Path

import anyio
from rich.console import Console
from rich.table import Table

from xbot.cli.bridge import run_terminal_bridge
from xbot.cli.chat import run_terminal_chat
from xbot.cli.setup import run_setup
from xbot.cli.tui import run_terminal_tui
from xbot.core.config import load_settings
from xbot.runtime.context import build_context
from xbot.storage.bootstrap import ensure_storage_ready

app = typer.Typer(help="xbot backend CLI", invoke_without_command=True)
schedule_app = typer.Typer(help="Manage scheduled Agent jobs.")
app.add_typer(schedule_app, name="schedule")


@app.callback()
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    anyio.run(_run_chat_command, None, None, None, False, False, False, False, True)


@app.command()
def run() -> None:
    settings = load_settings()
    uvicorn.run(
        "xbot.app.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.xbot.debug,
    )


@app.command()
def status() -> None:
    settings = load_settings()
    typer.echo(f"xbot config: {settings.config_file}")
    typer.echo(f"server: {settings.server.host}:{settings.server.port}")
    typer.echo(f"storage: {settings.storage.type} {settings.storage.url}")


@app.command("ui-build")
def ui_build(
    install: bool = typer.Option(True, "--install/--no-install", help="Install frontend dependencies before building."),
) -> None:
    """Build the Web Control UI into ui/dist for backend static serving."""

    root = Path(__file__).resolve().parents[3]
    ui_dir = root / "ui"
    package_lock = ui_dir / "package-lock.json"
    if not (ui_dir / "package.json").exists():
        raise typer.BadParameter(f"ui package not found: {ui_dir}")
    npm = "npm.cmd" if platform.system().lower().startswith("windows") else "npm"
    if install:
        install_cmd = [npm, "ci" if package_lock.exists() else "install"]
        raise_code = subprocess.call(install_cmd, cwd=ui_dir, env=os.environ.copy())
        if raise_code != 0:
            raise typer.Exit(raise_code)
    build_code = subprocess.call([npm, "run", "build"], cwd=ui_dir, env=os.environ.copy())
    raise typer.Exit(build_code)


@schedule_app.command("list")
def schedule_list(
    include_disabled: bool = typer.Option(False, "--all", help="Include disabled jobs."),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum jobs to show."),
) -> None:
    anyio.run(_schedule_list_command, include_disabled, limit)


@schedule_app.command("add")
def schedule_add(
    schedule: str = typer.Argument(..., help="Schedule expression: 30m, every 2h, daily 09:00, cron."),
    input_text: str = typer.Argument(..., help="Agent task input to run."),
    name: str | None = typer.Option(None, "--name", help="Job name."),
    max_runs: int | None = typer.Option(None, "--max-runs", help="Maximum run count."),
) -> None:
    anyio.run(_schedule_add_command, schedule, input_text, name, max_runs)


@schedule_app.command("pause")
def schedule_pause(job_id: str) -> None:
    anyio.run(_schedule_simple_command, "pause", job_id)


@schedule_app.command("resume")
def schedule_resume(job_id: str) -> None:
    anyio.run(_schedule_simple_command, "resume", job_id)


@schedule_app.command("delete")
def schedule_delete(job_id: str) -> None:
    anyio.run(_schedule_simple_command, "delete", job_id)


@schedule_app.command("run")
def schedule_run(job_id: str) -> None:
    anyio.run(_schedule_simple_command, "run", job_id)


@app.command("setup")
def setup(
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Runtime profile: local or production.",
    ),
    wechat: str | None = typer.Option(
        None,
        "--wechat",
        help="WeChat channel: none, ilink, 869, or both.",
    ),
    env_path: str | None = typer.Option(None, "--env", help="Path to .env file."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Use defaults without prompting."),
) -> None:
    run_setup(profile=profile, wechat=wechat, env_path=env_path, yes=yes)


@app.command("upgrade")
def upgrade() -> None:
    """Upgrade an installed xbot checkout without overwriting user data."""

    root = Path(__file__).resolve().parents[3]
    if platform.system().lower().startswith("windows"):
        script = root / "scripts" / "upgrade.ps1"
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
    else:
        script = root / "scripts" / "upgrade.sh"
        cmd = ["bash", str(script)]
    if not script.exists():
        raise typer.BadParameter(f"upgrade script not found: {script}")
    raise typer.Exit(subprocess.call(cmd, env=os.environ.copy()))


@app.command()
def chat(
    config: str | None = typer.Option(None, "--config", "-c", help="Path to xbot config file."),
    session: str | None = typer.Option(None, "--session", "-s", help="Continue a terminal chat session id."),
    cwd: str | None = typer.Option(None, "--cwd", help="Working directory to include in terminal context."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show more terminal runtime details."),
    debug: bool = typer.Option(False, "--debug", help="Show debug terminal runtime details."),
    fancy_input: bool = typer.Option(
        False,
        "--fancy-input",
        help="Use prompt_toolkit input with completion/history. Plain input is default for better IME support.",
    ),
    start_runtime: bool = typer.Option(
        False,
        "--start-runtime",
        help="Start full engine including adapters and message consumer. Defaults to Agent-only terminal mode.",
    ),
    tui: bool = typer.Option(False, "--tui", help="Use fullscreen Textual terminal UI."),
) -> None:
    anyio.run(_run_chat_command, config, session, cwd, verbose, debug, fancy_input, start_runtime, tui)


@app.command("chat-bridge")
def chat_bridge(
    config: str | None = typer.Option(None, "--config", "-c", help="Path to xbot config file."),
    session: str | None = typer.Option(None, "--session", "-s", help="Bridge session id."),
    cwd: str | None = typer.Option(None, "--cwd", help="Working directory to include in terminal context."),
) -> None:
    """Run JSONL stdin/stdout bridge for an external terminal UI process."""

    anyio.run(_run_bridge_command, config, session, cwd)


@app.command("db-init")
def db_init() -> None:
    db_upgrade()


@app.command("db-bootstrap")
def db_bootstrap() -> None:
    anyio.run(ensure_storage_ready, load_settings())
    typer.echo("database bootstrap completed")


@app.command("db-upgrade")
def db_upgrade(revision: str = "head") -> None:
    command.upgrade(_alembic_config(), revision)
    typer.echo(f"database upgraded to {revision}")


@app.command("db-current")
def db_current() -> None:
    command.current(_alembic_config())


@app.command("db-downgrade")
def db_downgrade(revision: str = "-1") -> None:
    command.downgrade(_alembic_config(), revision)
    typer.echo(f"database downgraded to {revision}")


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return cfg


async def _run_chat_command(
    config: str | None,
    session: str | None,
    cwd: str | None,
    verbose: bool,
    debug: bool,
    fancy_input: bool,
    start_runtime: bool,
    tui: bool,
) -> None:
    if tui:
        await run_terminal_tui(
            config_file=config,
            session_id=session,
            cwd=cwd,
            verbose=verbose,
            debug=debug,
            fancy_input=fancy_input,
            start_runtime=start_runtime,
        )
        return
    await run_terminal_chat(
        config_file=config,
        session_id=session,
        cwd=cwd,
        verbose=verbose,
        debug=debug,
        fancy_input=fancy_input,
        start_runtime=start_runtime,
    )


async def _run_bridge_command(
    config: str | None,
    session: str | None,
    cwd: str | None,
) -> None:
    await run_terminal_bridge(config_file=config, session_id=session, cwd=cwd)


async def _schedule_context():
    settings = load_settings()
    await ensure_storage_ready(settings)
    return build_context(settings)


async def _schedule_list_command(include_disabled: bool, limit: int) -> None:
    ctx = await _schedule_context()
    try:
        jobs = await ctx.agent.scheduler.list(include_disabled=include_disabled, limit=limit)
        table = Table(title="xbot scheduled jobs")
        table.add_column("id")
        table.add_column("enabled")
        table.add_column("name")
        table.add_column("schedule")
        table.add_column("next_run_at")
        table.add_column("runs")
        table.add_column("last_status")
        for job in jobs:
            table.add_row(
                job.id,
                "yes" if job.enabled else "no",
                job.name,
                job.schedule_display,
                job.next_run_at.isoformat() if job.next_run_at else "-",
                str(job.run_count),
                job.last_status or "-",
            )
        Console().print(table)
    finally:
        await ctx.storage.close()


async def _schedule_add_command(
    schedule: str,
    input_text: str,
    name: str | None,
    max_runs: int | None,
) -> None:
    ctx = await _schedule_context()
    try:
        job = await ctx.agent.scheduler.create(
            input_text=input_text,
            schedule=schedule,
            name=name,
            source="terminal:schedule",
            max_runs=max_runs,
            reply_policy="none",
        )
        typer.echo(f"created scheduled job: {job.id}")
        typer.echo(f"next_run_at: {job.next_run_at.isoformat() if job.next_run_at else '-'}")
    finally:
        await ctx.storage.close()


async def _schedule_simple_command(action: str, job_id: str) -> None:
    ctx = await _schedule_context()
    try:
        if action == "pause":
            job = await ctx.agent.scheduler.pause(job_id)
            typer.echo(f"paused scheduled job: {job.id}")
        elif action == "resume":
            job = await ctx.agent.scheduler.resume(job_id)
            typer.echo(f"resumed scheduled job: {job.id}")
        elif action == "delete":
            deleted = await ctx.agent.scheduler.delete(job_id)
            typer.echo(f"deleted scheduled job: {job_id}" if deleted else f"scheduled job not found: {job_id}")
        elif action == "run":
            job = await ctx.agent.scheduler.run_now(job_id)
            typer.echo(f"started scheduled job now: {job.id}")
    finally:
        await ctx.storage.close()


if __name__ == "__main__":
    app()

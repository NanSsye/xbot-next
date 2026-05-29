from __future__ import annotations

import uvicorn
import typer
from alembic import command
from alembic.config import Config
from pathlib import Path

import anyio

from xbot.cli.chat import run_terminal_chat
from xbot.cli.tui import run_terminal_tui
from xbot.core.config import load_settings
from xbot.storage.bootstrap import ensure_storage_ready

app = typer.Typer(help="xbot backend CLI", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    anyio.run(_run_chat_command, None, None, None, False, False, False, False, False)


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


if __name__ == "__main__":
    app()

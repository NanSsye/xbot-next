from __future__ import annotations

import uvicorn
import typer
from alembic import command
from alembic.config import Config
from pathlib import Path

from xbot.core.config import load_settings
from xbot.storage.bootstrap import ensure_storage_ready

app = typer.Typer(help="xbot backend CLI")


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


@app.command("db-init")
def db_init() -> None:
    db_upgrade()


@app.command("db-bootstrap")
def db_bootstrap() -> None:
    import anyio

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


if __name__ == "__main__":
    app()

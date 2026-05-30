from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import anyio
import asyncpg
from alembic import command
from asyncpg import InvalidCatalogNameError, InvalidPasswordError
from sqlalchemy.engine import make_url

from xbot.core.config import Settings, StorageConfig


@dataclass(frozen=True)
class DatabaseTarget:
    database: str
    username: str | None
    password: str | None


class StorageBootstrapError(RuntimeError):
    pass


async def ensure_storage_ready(settings: Settings) -> None:
    config = settings.storage
    if not config.auto_bootstrap:
        return
    if config.type == "sqlite":
        _ensure_sqlite_parent_dir(config.url)
        if config.run_migrations_on_startup:
            await anyio.to_thread.run_sync(_run_upgrade)
        return

    if config.admin_url:
        await _bootstrap_database(config)
    else:
        try:
            await _check_application_connection(config.url)
        except InvalidCatalogNameError as exc:
            raise StorageBootstrapError(
                "Target PostgreSQL database does not exist and XBOT_ADMIN_DATABASE_URL is not set."
            ) from exc

    try:
        await _check_application_connection(config.url)
    except InvalidPasswordError as exc:
        raise StorageBootstrapError(
            "PostgreSQL role exists but the configured application password is invalid. "
            "Automatic bootstrap will not overwrite an existing role password."
        ) from exc

    if config.run_migrations_on_startup:
        await anyio.to_thread.run_sync(_run_upgrade)


async def _check_application_connection(url: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(url))
    await conn.close()


async def _bootstrap_database(config: StorageConfig) -> None:
    if not config.admin_url:
        raise StorageBootstrapError(
            "Target PostgreSQL database does not exist and XBOT_ADMIN_DATABASE_URL is not set."
        )

    target = _database_target(config.url)
    admin_dsn = _admin_maintenance_dsn(config.admin_url)
    conn = await asyncpg.connect(admin_dsn)
    try:
        if config.create_role and target.username:
            await _ensure_role(conn, target.username, target.password)
        if config.create_database:
            owner = target.username if target.username else None
            await _ensure_database(conn, target.database, owner)
    finally:
        await conn.close()

    if target.username:
        await _ensure_database_privileges(config.admin_url, target.database, target.username)

    await _check_application_connection(config.url)


async def _ensure_role(conn: asyncpg.Connection, username: str, password: str | None) -> None:
    exists = await conn.fetchval("select 1 from pg_roles where rolname = $1", username)
    if exists:
        return
    if password is None:
        await conn.execute(f"create role {_quote_ident(username)} login")
    else:
        await conn.execute(
            f"create role {_quote_ident(username)} login password {_quote_literal(password)}"
        )


async def _ensure_database(
    conn: asyncpg.Connection, database: str, owner: str | None = None
) -> None:
    exists = await conn.fetchval("select 1 from pg_database where datname = $1", database)
    if exists:
        return
    owner_sql = f" owner {_quote_ident(owner)}" if owner else ""
    await conn.execute(f"create database {_quote_ident(database)}{owner_sql}")


async def _ensure_database_privileges(admin_url: str, database: str, username: str) -> None:
    conn = await asyncpg.connect(_admin_database_dsn(admin_url, database))
    quoted_database = _quote_ident(database)
    quoted_username = _quote_ident(username)
    try:
        await conn.execute(f"grant connect, temporary on database {quoted_database} to {quoted_username}")
        await conn.execute(f"grant usage, create on schema public to {quoted_username}")
        await conn.execute(f"grant all privileges on all tables in schema public to {quoted_username}")
        await conn.execute(f"grant all privileges on all sequences in schema public to {quoted_username}")
        await conn.execute(f"grant all privileges on all functions in schema public to {quoted_username}")
        await conn.execute(
            f"alter default privileges in schema public grant all on tables to {quoted_username}"
        )
        await conn.execute(
            f"alter default privileges in schema public grant all on sequences to {quoted_username}"
        )
        await conn.execute(
            f"alter default privileges in schema public grant all on functions to {quoted_username}"
        )
    finally:
        await conn.close()


def _run_upgrade() -> None:
    from xbot.cli.main import _alembic_config

    command.upgrade(_alembic_config(), "head")


def _ensure_sqlite_parent_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.drivername not in {"sqlite", "sqlite+aiosqlite"}:
        return
    database = parsed.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _database_target(url: str) -> DatabaseTarget:
    parsed = make_url(url)
    if not parsed.database:
        raise StorageBootstrapError("XBOT_DATABASE_URL must include a database name.")
    return DatabaseTarget(
        database=parsed.database,
        username=parsed.username,
        password=parsed.password,
    )


def _admin_maintenance_dsn(url: str) -> str:
    parsed = make_url(url).set(drivername="postgresql")
    if not parsed.database:
        parsed = parsed.set(database="postgres")
    return parsed.render_as_string(hide_password=False)


def _admin_database_dsn(url: str, database: str) -> str:
    parsed = make_url(url).set(drivername="postgresql", database=database)
    return parsed.render_as_string(hide_password=False)


def _asyncpg_dsn(url: str) -> str:
    parsed = make_url(url).set(drivername="postgresql")
    return parsed.render_as_string(hide_password=False)


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

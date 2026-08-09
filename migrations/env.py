"""Alembic 迁移入口。

- 迁移目标是 xbot 当前配置的数据库（见 ``xbot.core.config.load_settings``）。
- PostgreSQL 下若配置了 admin_url，则通过 admin 连接执行迁移，
  避免应用角色缺少建表权限；SQLite 直接使用应用连接。
- 迁移连接使用 NullPool，迁移结束后立即释放，不占用应用连接池。
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from xbot.core.config import load_settings
from xbot.storage.models import Base

config = context.config

if config.config_file_name is not None and os.environ.get("XBOT_TERMINAL_LOGGING") != "1":
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    settings = load_settings()
    if settings.storage.type == "postgresql" and settings.storage.admin_url:
        target = make_url(settings.storage.url)
        return (
            make_url(settings.storage.admin_url)
            .set(drivername="postgresql+asyncpg", database=target.database)
            .render_as_string(hide_password=False)
        )
    return settings.storage.url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

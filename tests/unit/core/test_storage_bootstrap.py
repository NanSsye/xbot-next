from __future__ import annotations

from xbot.storage.bootstrap import _admin_maintenance_dsn, _asyncpg_dsn, _database_target


def test_database_target_parses_application_url() -> None:
    target = _database_target("postgresql+asyncpg://xbot:secret@db:5432/xbot")

    assert target.database == "xbot"
    assert target.username == "xbot"
    assert target.password == "secret"


def test_asyncpg_dsn_strips_sqlalchemy_async_driver() -> None:
    assert (
        _asyncpg_dsn("postgresql+asyncpg://xbot:secret@db:5432/xbot")
        == "postgresql://xbot:secret@db:5432/xbot"
    )


def test_admin_maintenance_dsn_defaults_to_postgres_database() -> None:
    assert (
        _admin_maintenance_dsn("postgresql+asyncpg://postgres:secret@db:5432")
        == "postgresql://postgres:secret@db:5432/postgres"
    )

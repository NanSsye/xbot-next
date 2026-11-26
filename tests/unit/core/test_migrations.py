from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from xbot.cli.main import _alembic_config
from xbot.storage.models import Base


def test_alembic_config_points_to_migrations():
    cfg = _alembic_config()
    assert isinstance(cfg, Config)
    assert Path(cfg.get_main_option("script_location")).name == "migrations"
    assert Path(cfg.config_file_name).name == "alembic.ini"


def test_clean_database_upgrade_and_downgrade(tmp_path, monkeypatch):
    database = tmp_path / "fresh.db"
    monkeypatch.setenv("XBOT_CONFIG_FILE", str(tmp_path / "unused.toml"))
    monkeypatch.setenv("XBOT_RUNTIME_CONFIG_FILE", str(tmp_path / "unused.json"))
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_STORAGE_TYPE", "sqlite")
    monkeypatch.setenv("XBOT_DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    cfg = _alembic_config()
    assert ScriptDirectory.from_config(cfg).get_heads() == ["fresh_0001"]
    command.upgrade(cfg, "head")
    command.check(cfg)
    engine = create_engine(f"sqlite:///{database}")
    try:
        assert set(inspect(engine).get_table_names()) == {*Base.metadata.tables, "alembic_version"}
        command.downgrade(cfg, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        command.upgrade(cfg, "head")
        command.check(cfg)
    finally:
        engine.dispose()

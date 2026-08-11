import importlib
from pathlib import Path
from types import SimpleNamespace

from alembic.config import Config

from xbot.cli.main import _alembic_config
from xbot.storage.models import Base


def test_alembic_config_points_to_migrations():
    cfg = _alembic_config()
    assert isinstance(cfg, Config)
    assert Path(cfg.get_main_option("script_location")).name == "migrations"
    assert Path(cfg.config_file_name).name == "alembic.ini"


def test_initial_revision_exists():
    assert Path("migrations/versions/0001_initial_schema.py").exists()


def test_migrations_mention_all_metadata_tables():
    revision_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("migrations/versions").glob("*.py"))
    )
    for table_name in Base.metadata.tables:
        assert f'"{table_name}"' in revision_text


def test_0009_skips_varchar_resize_on_sqlite(monkeypatch):
    migration = importlib.import_module("migrations.versions.0009_long_external_message_ids")
    bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    calls = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: calls.append((args, kwargs)))

    migration.upgrade()
    migration.downgrade()

    assert calls == []

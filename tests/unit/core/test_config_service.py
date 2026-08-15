import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import xbot.services.config_service as config_service_module
from xbot.core.config import load_settings
from xbot.services.config_service import ConfigConflictError, ConfigService


def write_config(path: Path) -> None:
    path.write_text(
        """
[xbot]
name = "test-bot"
timezone = "Asia/Shanghai"

[server]
host = "127.0.0.1"
port = 8548

[api]
auth_enabled = true
token = "initial-api-secret"

[storage]
type = "sqlite"
url = "sqlite+aiosqlite:///:memory:"
persist_runtime_events = false
auto_bootstrap = false

[queue]
type = "memory"

[adapters.qq]
enabled = false
app_id = "qq-app"
client_secret = "qq-client-secret"

[adapters.telegram]
enabled = false
bot_token = "telegram-bot-secret"
""".strip(),
        encoding="utf-8",
    )


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    config_file = tmp_path / "xbot.toml"
    runtime_file = tmp_path / "runtime-config.json"
    write_config(config_file)
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_RUNTIME_CONFIG_FILE", str(runtime_file))
    return config_file, runtime_file


def test_snapshot_masks_every_secret_and_reports_runtime_metadata(config_env):
    config_file, runtime_file = config_env
    settings = load_settings(config_file)

    snapshot = ConfigService(config_file).snapshot(settings)
    fields = {
        field["path"]: field
        for section in snapshot["sections"]
        for field in section["fields"]
    }

    assert snapshot["runtime_file"] == str(runtime_file.resolve())
    assert fields["api.token"]["value"] is None
    assert fields["api.token"]["masked_value"] == "已配置"
    assert fields["adapters.qq.client_secret"]["value"] is None
    assert fields["adapters.telegram.bot_token"]["value"] is None
    assert fields["adapters.telegram.bot_token"]["masked_value"] == "已配置"
    assert fields["storage.url"]["value"] is None
    assert fields["adapters.qq.app_id"]["value"] == "qq-app"
    assert fields["server.port"]["restart_required"] is True
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "initial-api-secret" not in serialized
    assert "qq-client-secret" not in serialized
    assert "telegram-bot-secret" not in serialized


@pytest.mark.anyio
async def test_apply_persists_live_override_and_uses_optimistic_revision(
    config_env,
    monkeypatch,
):
    config_file, runtime_file = config_env
    settings = load_settings(config_file)
    context = SimpleNamespace(settings=settings)
    app = SimpleNamespace(state=SimpleNamespace(context=context))
    service = ConfigService(config_file)
    initial = service.snapshot(settings)

    async def fake_ready(candidate):
        return None

    async def fake_replace(target_app, old_context, candidate):
        target_app.state.context = SimpleNamespace(settings=candidate)

    monkeypatch.setattr("xbot.services.config_service.ensure_storage_ready", fake_ready)
    monkeypatch.setattr(service, "_replace_context", fake_replace)

    result = await service.apply(
        app,
        revision=initial["revision"],
        changes=[{"path": "xbot.name", "value": "runtime-bot", "reset": False}],
    )

    assert result["applied"] == ["xbot.name"]
    assert result["restart_required"] == []
    assert app.state.context.settings.xbot.name == "runtime-bot"
    assert json.loads(runtime_file.read_text(encoding="utf-8"))["xbot"]["name"] == "runtime-bot"

    with pytest.raises(ConfigConflictError):
        await service.apply(
            app,
            revision=initial["revision"],
            changes=[{"path": "xbot.name", "value": "stale-write", "reset": False}],
        )


@pytest.mark.anyio
async def test_restart_only_change_is_saved_but_not_applied_to_current_runtime(config_env):
    config_file, runtime_file = config_env
    settings = load_settings(config_file)
    app = SimpleNamespace(state=SimpleNamespace(context=SimpleNamespace(settings=settings)))
    service = ConfigService(config_file)
    revision = service.snapshot(settings)["revision"]

    result = await service.apply(
        app,
        revision=revision,
        changes=[{"path": "server.port", "value": 9555, "reset": False}],
    )

    assert result["applied"] == []
    assert result["restart_required"] == ["server.port"]
    assert app.state.context.settings.server.port == 8548
    assert json.loads(runtime_file.read_text(encoding="utf-8"))["server"]["port"] == 9555
    assert result["snapshot"]["pending_restart"] == ["server.port"]


@pytest.mark.anyio
async def test_adapter_enabled_field_must_use_channel_toggle(config_env):
    config_file, _ = config_env
    settings = load_settings(config_file)
    app = SimpleNamespace(state=SimpleNamespace(context=SimpleNamespace(settings=settings)))
    service = ConfigService(config_file)

    with pytest.raises(ValueError, match="通道启停"):
        await service.apply(
            app,
            revision=service.snapshot(settings)["revision"],
            changes=[{"path": "adapters.qq.enabled", "value": True, "reset": False}],
        )


@pytest.mark.anyio
async def test_revision_rejects_stale_write_after_overrides_return_to_same_content(
    config_env,
    monkeypatch,
):
    config_file, _ = config_env
    settings = load_settings(config_file)
    app = SimpleNamespace(state=SimpleNamespace(context=SimpleNamespace(settings=settings)))
    service = ConfigService(config_file)
    initial_revision = service.snapshot(settings)["revision"]

    async def fake_ready(candidate):
        return None

    async def fake_replace(target_app, old_context, candidate):
        target_app.state.context = SimpleNamespace(settings=candidate)

    monkeypatch.setattr("xbot.services.config_service.ensure_storage_ready", fake_ready)
    monkeypatch.setattr(service, "_replace_context", fake_replace)

    changed = await service.apply(
        app,
        revision=initial_revision,
        changes=[{"path": "xbot.name", "value": "temporary-name", "reset": False}],
    )
    restored = await service.apply(
        app,
        revision=changed["snapshot"]["revision"],
        changes=[{"path": "xbot.name", "reset": True}],
    )

    assert restored["snapshot"]["revision"] != initial_revision
    with pytest.raises(ConfigConflictError):
        await service.apply(
            app,
            revision=initial_revision,
            changes=[{"path": "xbot.timezone", "value": "UTC", "reset": False}],
        )


@pytest.mark.anyio
async def test_replace_context_reconfigures_debug_logging_and_restores_on_failure(monkeypatch, config_env):
    config_file, _ = config_env
    old_settings = load_settings(config_file)
    candidate = old_settings.model_copy(deep=True)
    candidate.xbot.debug = True

    class Engine:
        def __init__(self, fail=False):
            self.fail = fail
            self.started = False

        async def start(self):
            if self.fail:
                raise RuntimeError("start failed")
            self.started = True

        async def stop(self):
            self.started = False

    class Storage:
        async def close(self):
            return None

    old_context = SimpleNamespace(settings=old_settings, engine=Engine(), storage=Storage())
    new_context = SimpleNamespace(settings=candidate, engine=Engine(), storage=Storage())
    rollback_context = SimpleNamespace(settings=old_settings, engine=Engine(), storage=Storage())
    contexts = iter([new_context, rollback_context])
    calls = []
    monkeypatch.setattr(config_service_module, "build_context", lambda settings: next(contexts))
    monkeypatch.setattr(config_service_module, "configure_logging", lambda debug: calls.append(bool(debug)))
    app = SimpleNamespace(state=SimpleNamespace(context=old_context))

    await ConfigService(config_file)._replace_context(app, old_context, candidate)
    assert app.state.context is new_context
    assert calls == [True]

    failing_context = SimpleNamespace(settings=candidate, engine=Engine(fail=True), storage=Storage())
    rollback_context = SimpleNamespace(settings=old_settings, engine=Engine(), storage=Storage())
    contexts = iter([failing_context, rollback_context])
    app.state.context = old_context
    calls.clear()
    with pytest.raises(RuntimeError, match="start failed"):
        await ConfigService(config_file)._replace_context(app, old_context, candidate)
    assert app.state.context is rollback_context
    assert calls == [False]

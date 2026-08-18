from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xbot.api.v1 import config as config_api
from xbot.app.deps import get_context
from xbot.core.config import load_settings
from xbot.services.config_service import ConfigService
from xbot.services.llm_model_service import LLMModelDiscoveryError, LLMModelDiscoveryService


def write_config(path: Path) -> None:
    path.write_text(
        """
[xbot]
name = "api-test-bot"

[api]
auth_enabled = false
token = "api-test-secret"

[storage]
type = "sqlite"
url = "sqlite+aiosqlite:///:memory:"
auto_bootstrap = false

[queue]
type = "memory"

[adapters.qq]
enabled = false
app_id = "qq-app"
client_secret = "qq-secret"
""".strip(),
        encoding="utf-8",
    )


def test_config_api_masks_secrets_applies_live_change_and_rejects_stale_revision(
    tmp_path,
    monkeypatch,
):
    config_file = tmp_path / "xbot.toml"
    runtime_file = tmp_path / "runtime-config.json"
    write_config(config_file)
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_RUNTIME_CONFIG_FILE", str(runtime_file))

    app = FastAPI()
    app.state.context = SimpleNamespace(settings=load_settings(config_file))
    app.dependency_overrides[get_context] = lambda: app.state.context
    app.include_router(config_api.router, prefix="/api/v1/config")

    async def fake_ready(candidate):
        return None

    async def fake_replace(self, target_app, old_context, candidate):
        target_app.state.context = SimpleNamespace(settings=candidate)

    monkeypatch.setattr("xbot.services.config_service.ensure_storage_ready", fake_ready)
    monkeypatch.setattr(ConfigService, "_replace_context", fake_replace)

    with TestClient(app) as client:
        snapshot_response = client.get("/api/v1/config")
        assert snapshot_response.status_code == 200
        snapshot = snapshot_response.json()["data"]
        serialized = snapshot_response.text
        assert "api-test-secret" not in serialized
        assert "qq-secret" not in serialized

        update_response = client.put(
            "/api/v1/config",
            json={
                "revision": snapshot["revision"],
                "changes": [{"path": "xbot.name", "value": "api-updated-bot"}],
            },
        )
        assert update_response.status_code == 200
        result = update_response.json()["data"]
        assert result["applied"] == ["xbot.name"]
        assert result["restart_required"] == []
        assert app.state.context.settings.xbot.name == "api-updated-bot"

        stale_response = client.put(
            "/api/v1/config",
            json={
                "revision": snapshot["revision"],
                "changes": [{"path": "xbot.name", "value": "stale-value"}],
            },
        )
        assert stale_response.status_code == 409
        assert "请刷新后重试" in stale_response.json()["detail"]


def test_model_discovery_api_returns_safe_result_and_safe_error(tmp_path, monkeypatch):
    config_file = tmp_path / "xbot.toml"
    runtime_file = tmp_path / "runtime-config.json"
    write_config(config_file)
    monkeypatch.setenv("XBOT_LOAD_DOTENV", "false")
    monkeypatch.setenv("XBOT_RUNTIME_CONFIG_FILE", str(runtime_file))

    app = FastAPI()
    app.state.context = SimpleNamespace(settings=load_settings(config_file))
    app.dependency_overrides[get_context] = lambda: app.state.context
    app.include_router(config_api.router, prefix="/api/v1/config")

    async def success(self, llm_config):
        return ["model-a", "model-b"]

    monkeypatch.setattr(LLMModelDiscoveryService, "discover", success)
    with TestClient(app) as client:
        response = client.post("/api/v1/config/llm/models/discover")
        assert response.status_code == 200
        assert response.json()["data"] == {"models": ["model-a", "model-b"], "count": 2}

    async def failure(self, llm_config):
        raise LLMModelDiscoveryError("无法连接模型服务，请检查 API 地址和网络")

    monkeypatch.setattr(LLMModelDiscoveryService, "discover", failure)
    with TestClient(app) as client:
        response = client.post("/api/v1/config/llm/models/discover")
        assert response.status_code == 422
        assert response.json()["detail"] == "无法连接模型服务，请检查 API 地址和网络"

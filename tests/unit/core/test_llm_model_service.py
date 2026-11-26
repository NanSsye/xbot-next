from __future__ import annotations

import httpx
import pytest

import xbot.services.llm_model_service as model_service_module
from xbot.core.config import AgentLLMConfig
from xbot.services.llm_model_service import LLMModelDiscoveryError, LLMModelDiscoveryService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def install_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient

    def factory(**kwargs):
        return async_client(transport=transport, **kwargs)

    monkeypatch.setattr(model_service_module.httpx, "AsyncClient", factory)


@pytest.mark.anyio
async def test_discovers_sorted_unique_openai_models_without_exposing_key(monkeypatch):
    secret = "private-model-key"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://models.example.test/v1/models"
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(200, json={"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-b"}]})

    install_transport(monkeypatch, handler)
    config = AgentLLMConfig(
        api_key=secret,
        base_url="https://models.example.test/v1",
        model="model-a",
        enabled_models=["model-a"],
    )

    models = await LLMModelDiscoveryService().discover(config)

    assert models == ["model-a", "model-b"]


@pytest.mark.anyio
async def test_discovery_failure_never_returns_upstream_body_or_key(monkeypatch):
    secret = "private-model-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid credential: {secret}")

    install_transport(monkeypatch, handler)
    config = AgentLLMConfig(
        api_key=secret,
        base_url="https://models.example.test/v1",
        model="model-a",
        enabled_models=["model-a"],
    )

    with pytest.raises(LLMModelDiscoveryError) as exc_info:
        await LLMModelDiscoveryService().discover(config)

    message = str(exc_info.value)
    assert secret not in message
    assert "invalid credential" not in message
    assert "请检查 API 地址" in message


@pytest.mark.anyio
async def test_anthropic_root_url_uses_v1_models_and_key_header(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.anthropic.com/v1/models"
        assert request.headers["x-api-key"] == "anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "claude-model"}]})

    install_transport(monkeypatch, handler)
    config = AgentLLMConfig(
        provider="anthropic",
        api_key="anthropic-key",
        base_url="https://api.anthropic.com",
        model="claude-model",
        enabled_models=["claude-model"],
    )

    assert await LLMModelDiscoveryService().discover(config) == ["claude-model"]

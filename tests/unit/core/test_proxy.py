import os

import pytest

import xbot.core.proxy as proxy_module
from xbot.adapters.qq.client import QQBotClient
from xbot.adapters.telegram.client import TelegramBotClient
from xbot.core.config import QQAdapterConfig, TelegramAdapterConfig
from xbot.core.proxy import (
    ProxyConfig,
    apply_proxy_environment,
    create_aiohttp_session,
    merge_proxy_env,
    validate_proxy_config,
)


def reset_proxy_state(monkeypatch) -> None:
    monkeypatch.setattr(proxy_module, "_managed_previous_env", None)
    monkeypatch.setattr(proxy_module, "_active_proxy_url", None)


def test_merge_proxy_env_and_validate_without_exposing_address():
    data = {}
    merge_proxy_env(
        data,
        {
            "XBOT_PROXY_ENABLED": "true",
            "XBOT_PROXY_URL": "socks5://proxy.internal:1080",
            "XBOT_PROXY_NO_PROXY": "localhost;127.0.0.1",
        },
    )
    config = ProxyConfig.model_validate(data["network"]["proxy"])
    validate_proxy_config(config)
    assert config.enabled is True
    assert config.no_proxy == ["localhost", "127.0.0.1"]
    validate_proxy_config(ProxyConfig(enabled=True, url="proxy.internal:1080"))

    with pytest.raises(ValueError, match="仅支持") as error:
        validate_proxy_config(ProxyConfig(enabled=True, url="ftp://secret@proxy.internal:21"))
    assert "secret" not in str(error.value)


@pytest.mark.anyio
async def test_proxy_environment_applies_live_and_http_session_uses_it(monkeypatch):
    reset_proxy_state(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://original.proxy:8080")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    config = ProxyConfig(
        enabled=True,
        url="http://runtime.proxy:1080",
        no_proxy=["localhost", "127.0.0.1"],
    )

    apply_proxy_environment(config)
    assert os.environ["HTTP_PROXY"] == "http://runtime.proxy:1080"
    assert os.environ["HTTPS_PROXY"] == "http://runtime.proxy:1080"
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"
    session = create_aiohttp_session()
    try:
        assert session._trust_env is True
    finally:
        await session.close()

    apply_proxy_environment(ProxyConfig())
    assert os.environ["HTTP_PROXY"] == "http://original.proxy:8080"
    assert "HTTPS_PROXY" not in os.environ


@pytest.mark.anyio
async def test_socks_proxy_builds_connector_without_network_access(monkeypatch):
    reset_proxy_state(monkeypatch)
    apply_proxy_environment(ProxyConfig(enabled=True, url="socks5://proxy.internal:1080"))
    session = create_aiohttp_session()
    try:
        assert session.connector.__class__.__module__.startswith("aiohttp_socks")
        assert session._trust_env is False
    finally:
        await session.close()
        apply_proxy_environment(ProxyConfig())


@pytest.mark.anyio
async def test_telegram_and_qq_clients_use_runtime_proxy_sessions(monkeypatch):
    reset_proxy_state(monkeypatch)
    apply_proxy_environment(ProxyConfig(enabled=True, url="proxy.internal:1080"))
    telegram = TelegramBotClient(TelegramAdapterConfig())
    qq = QQBotClient(QQAdapterConfig())
    try:
        assert (await telegram._get_session())._trust_env is True
        assert (await qq._get_session())._trust_env is True
    finally:
        await telegram.close()
        await qq.close()
        apply_proxy_environment(ProxyConfig())

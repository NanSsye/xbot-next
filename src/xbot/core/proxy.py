from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, Field


class ProxyConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    no_proxy: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"]
    )


class NetworkConfig(BaseModel):
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)


_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_NO_PROXY_KEYS = ("NO_PROXY", "no_proxy")
_managed_previous_env: dict[str, str | None] | None = None
_active_proxy_url: str | None = None


def merge_proxy_env(data: dict[str, Any], env: dict[str, str]) -> None:
    enabled = env.get("XBOT_PROXY_ENABLED")
    url = env.get("XBOT_PROXY_URL")
    no_proxy = env.get("XBOT_PROXY_NO_PROXY")
    if enabled is None and url is None and no_proxy is None:
        return
    target = data.setdefault("network", {}).setdefault("proxy", {})
    if enabled is not None:
        target["enabled"] = enabled.lower() in {"1", "true", "yes", "on"}
    if url is not None:
        target["url"] = url.strip()
    if no_proxy is not None:
        target["no_proxy"] = [item.strip() for item in no_proxy.replace(";", ",").split(",") if item.strip()]


def validate_proxy_config(config: ProxyConfig) -> None:
    if not config.enabled:
        return
    raw_value = config.url.strip()
    if not raw_value:
        raise ValueError("启用代理前必须填写代理地址")
    value = _normalized_proxy_url(raw_value)
    if len(value) > 2048:
        raise ValueError("代理地址过长")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("代理地址格式无效") from None
    if parsed.scheme.lower() not in {"http", "https", "socks4", "socks5"}:
        raise ValueError("代理地址仅支持 http、https、socks4 或 socks5")
    if not parsed.hostname or port is None:
        raise ValueError("代理地址必须包含主机和端口")


def apply_proxy_environment(config: ProxyConfig) -> None:
    global _active_proxy_url, _managed_previous_env
    validate_proxy_config(config)
    if config.enabled:
        if _managed_previous_env is None:
            _managed_previous_env = {
                key: os.environ.get(key) for key in (*_PROXY_KEYS, *_NO_PROXY_KEYS)
            }
        proxy_url = _normalized_proxy_url(config.url)
        for key in _PROXY_KEYS:
            os.environ[key] = proxy_url
        bypass = ",".join(dict.fromkeys(item.strip() for item in config.no_proxy if item.strip()))
        for key in _NO_PROXY_KEYS:
            if bypass:
                os.environ[key] = bypass
            else:
                os.environ.pop(key, None)
        _active_proxy_url = proxy_url
        return
    if _managed_previous_env is not None:
        for key, value in _managed_previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _managed_previous_env = None
    _active_proxy_url = None


def create_aiohttp_session(**kwargs: Any) -> aiohttp.ClientSession:
    proxy_url = _active_proxy_url or ""
    if proxy_url.lower().startswith(("socks4://", "socks5://")):
        try:
            from aiohttp_socks import ProxyConnector
        except ImportError:
            raise RuntimeError("SOCKS 代理依赖未安装，请重新构建服务") from None
        kwargs.setdefault("connector", ProxyConnector.from_url(proxy_url))
        kwargs.setdefault("trust_env", False)
    else:
        kwargs.setdefault("trust_env", True)
    return aiohttp.ClientSession(**kwargs)


def _normalized_proxy_url(value: str) -> str:
    normalized = value.strip()
    return normalized if "://" in normalized else f"http://{normalized}"

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from xbot.core.config import AgentLLMConfig

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_MODELS = 500


class LLMModelDiscoveryError(RuntimeError):
    pass


class LLMModelDiscoveryService:
    async def discover(self, config: AgentLLMConfig) -> list[str]:
        api_key = str(config.api_key or "").strip()
        if not api_key:
            raise LLMModelDiscoveryError("请先配置模型 API Key")
        url = self._models_url(config.base_url, config.provider)
        headers = self._headers(config.provider, api_key)
        timeout = httpx.Timeout(min(max(float(config.timeout_seconds), 3.0), 20.0))
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        raise LLMModelDiscoveryError(
                            "模型服务拒绝了请求，请检查 API 地址、协议和 API Key"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise LLMModelDiscoveryError("模型服务返回的数据过大，无法安全读取")
        except LLMModelDiscoveryError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMModelDiscoveryError("模型服务响应超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise LLMModelDiscoveryError("无法连接模型服务，请检查 API 地址和网络") from exc

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMModelDiscoveryError("模型服务返回了无法识别的模型列表") from exc
        models = self._model_ids(payload)
        if not models:
            raise LLMModelDiscoveryError("模型服务没有返回可用模型")
        return models

    @staticmethod
    def _models_url(base_url: str, provider: str) -> str:
        parts = urlsplit(str(base_url or "").strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise LLMModelDiscoveryError("模型 API 地址必须是有效的 HTTP(S) 地址")
        if parts.username or parts.password:
            raise LLMModelDiscoveryError("模型 API 地址不能包含账号或密码")
        base_path = parts.path.rstrip("/")
        if provider == "anthropic" and not base_path:
            base_path = "/v1"
        path = base_path + "/models"
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    @staticmethod
    def _headers(provider: str, api_key: str) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if provider == "anthropic":
            headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        else:
            headers["authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _model_ids(payload: Any) -> list[str]:
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        models: set[str] = set()
        for item in items:
            model = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
            if model and len(model) <= 256:
                models.add(model)
            if len(models) >= MAX_MODELS:
                break
        return sorted(models, key=str.casefold)

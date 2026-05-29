from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from xbot.core.config import AgentLLMConfig
from xbot.core.exceptions import XBotError


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, Any] = Field(default_factory=dict)
    raw_id: str | None = None


class LLMProvider(Protocol):
    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        ...

    def status(self) -> dict:
        ...


class DisabledLLMProvider:
    def __init__(self, reason: str = "LLM provider is disabled.") -> None:
        self.reason = reason

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        raise XBotError(self.reason)

    def status(self) -> dict:
        return {"enabled": False, "provider": "disabled", "reason": self.reason}


class OpenAICompatibleLLMProvider:
    def __init__(self, config: AgentLLMConfig) -> None:
        if not config.api_key:
            raise XBotError("LLM provider is enabled but XBOT_LLM_API_KEY is not configured.")
        self.config = config

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise XBotError("LLM response did not include choices.")
        content = choices[0].get("message", {}).get("content") or ""
        return LLMResponse(
            content=content,
            model=data.get("model") or self.config.model,
            provider="openai_compatible",
            usage=data.get("usage") or {},
            raw_id=data.get("id"),
        )

    async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_text = line.removeprefix("data:").strip()
                    if data_text == "[DONE]":
                        break
                    try:
                        data = json.loads(data_text)
                    except ValueError:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    def status(self) -> dict:
        return {
            "enabled": True,
            "provider": "openai_compatible",
            "base_url": self.config.base_url,
            "model": self.config.model,
            "context_window_tokens": self.config.context_window_tokens,
        }


def create_llm_provider(config: AgentLLMConfig) -> LLMProvider:
    if not config.enabled:
        return DisabledLLMProvider()
    if config.provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(config)
    return DisabledLLMProvider(f"Unsupported LLM provider: {config.provider}")

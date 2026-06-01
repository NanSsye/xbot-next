from __future__ import annotations

import base64
import json
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from xbot.core.config import AgentLLMConfig
from xbot.core.exceptions import XBotError


class LLMContentBlock(BaseModel):
    type: str
    text: str | None = None
    path: str | None = None
    url: str | None = None
    mime_type: str | None = None


class LLMMessage(BaseModel):
    role: str
    content: str | None = None
    content_blocks: list[LLMContentBlock] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai_message(self, config: AgentLLMConfig | None = None) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True, exclude={"content_blocks"})
        if self.content_blocks:
            payload["content"] = _openai_content_blocks(self.content_blocks, config=config)
        return payload


class LLMToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, Any] = Field(default_factory=dict)
    raw_id: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)


def _openai_content_blocks(
    blocks: list[LLMContentBlock],
    *,
    config: AgentLLMConfig | None = None,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for block in blocks:
        if block.type == "text":
            converted.append({"type": "text", "text": block.text or ""})
            continue
        if block.type == "image" and _can_send_image(config):
            image_url = block.url or _local_file_data_url(block)
            if image_url:
                converted.append({"type": "image_url", "image_url": {"url": image_url}})
    return converted or [{"type": "text", "text": ""}]


def _anthropic_content_blocks(
    blocks: list[LLMContentBlock],
    *,
    config: AgentLLMConfig | None = None,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for block in blocks:
        if block.type == "text":
            converted.append({"type": "text", "text": block.text or ""})
            continue
        if block.type == "image" and _can_send_image(config):
            source = _anthropic_image_source(block)
            if source:
                converted.append({"type": "image", "source": source})
    return converted or [{"type": "text", "text": ""}]


def _can_send_image(config: AgentLLMConfig | None) -> bool:
    return bool(config and config.multimodal_enabled and config.image_input_enabled)


def _local_file_data_url(block: LLMContentBlock) -> str:
    encoded = _local_file_base64(block)
    if not encoded:
        return ""
    return f"data:{_block_mime_type(block)};base64,{encoded}"


def _anthropic_image_source(block: LLMContentBlock) -> dict[str, Any]:
    if block.url:
        return {"type": "url", "url": block.url}
    encoded = _local_file_base64(block)
    if not encoded:
        return {}
    return {"type": "base64", "media_type": _block_mime_type(block), "data": encoded}


def _local_file_base64(block: LLMContentBlock) -> str:
    if not block.path:
        return ""
    path = Path(block.path)
    if not path.is_file():
        return ""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _block_mime_type(block: LLMContentBlock) -> str:
    if block.mime_type:
        return block.mime_type
    if block.path:
        guessed, _ = mimetypes.guess_type(block.path)
        if guessed:
            return guessed
    return "application/octet-stream"


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        ...

    def status(self) -> dict:
        ...


class DisabledLLMProvider:
    def __init__(self, reason: str = "LLM provider is disabled.") -> None:
        self.reason = reason

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise XBotError(self.reason)

    def status(self) -> dict:
        return {"enabled": False, "provider": "disabled", "reason": self.reason}


class OpenAICompatibleLLMProvider:
    def __init__(self, config: AgentLLMConfig) -> None:
        if not config.api_key:
            raise XBotError("LLM provider is enabled but XBOT_LLM_API_KEY is not configured.")
        self.config = config

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [message.to_openai_message(config=self.config) for message in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise XBotError("LLM response did not include choices.")
        message = choices[0].get("message", {}) or {}
        content = message.get("content") or ""
        return LLMResponse(
            content=content,
            model=data.get("model") or self.config.model,
            provider="openai_compatible",
            usage=data.get("usage") or {},
            raw_id=data.get("id"),
            tool_calls=self._parse_tool_calls(message.get("tool_calls") or []),
        )

    def _parse_tool_calls(self, raw_calls: list[dict[str, Any]]) -> list[LLMToolCall]:
        calls = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            name = str(function.get("name") or raw.get("name") or "").strip()
            if not name:
                continue
            arguments = function.get("arguments") or raw.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments.strip() else {}
                except ValueError:
                    arguments = {"_raw_arguments": arguments}
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
            calls.append(
                LLMToolCall(
                    id=str(raw.get("id") or "") or None,
                    name=name,
                    arguments=arguments,
                    raw=raw,
                )
            )
        return calls

    async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [message.to_openai_message(config=self.config) for message in messages],
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
            "multimodal_enabled": self.config.multimodal_enabled,
            "image_input_enabled": self.config.image_input_enabled,
        }


class AnthropicLLMProvider:
    def __init__(self, config: AgentLLMConfig) -> None:
        if not config.api_key:
            raise XBotError("Anthropic LLM provider is enabled but XBOT_LLM_API_KEY is not configured.")
        self.config = config

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        url = self._messages_url()
        payload = self._build_payload(messages, tools=tools)
        headers = {
            "x-api-key": str(self.config.api_key),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        content_blocks = data.get("content") or []
        text_parts = [
            str(block.get("text") or "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return LLMResponse(
            content="".join(text_parts),
            model=data.get("model") or self.config.model,
            provider="anthropic",
            usage=data.get("usage") or {},
            raw_id=data.get("id"),
            tool_calls=self._parse_tool_calls(content_blocks),
        )

    def _messages_url(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}/messages"
        return f"{base_url}/v1/messages"

    def _build_payload(self, messages: list[LLMMessage], *, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        system, anthropic_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if system:
            payload["system"] = system
        anthropic_tools = self._convert_tools(tools or [])
        if anthropic_tools:
            payload["tools"] = anthropic_tools
        return payload

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.role
            if role == "system":
                if message.content:
                    system_parts.append(message.content)
                continue
            if role == "tool":
                blocks = [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id or "",
                        "content": message.content or "",
                    }
                ]
                self._append_anthropic_message(converted, "user", blocks)
                continue
            if role == "assistant" and message.tool_calls:
                blocks = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for index, raw_call in enumerate(message.tool_calls):
                    blocks.append(self._tool_use_block(raw_call, index=index))
                self._append_anthropic_message(converted, "assistant", blocks)
                continue
            anthropic_role = "assistant" if role == "assistant" else "user"
            content: str | list[dict[str, Any]]
            if message.content_blocks:
                content = _anthropic_content_blocks(message.content_blocks, config=self.config)
            else:
                content = message.content or ""
            self._append_anthropic_message(converted, anthropic_role, content)
        return "\n\n".join(system_parts), converted

    def _append_anthropic_message(self, messages: list[dict[str, Any]], role: str, content: str | list[dict[str, Any]]) -> None:
        if not messages or messages[-1]["role"] != role:
            messages.append({"role": role, "content": content})
            return
        previous = messages[-1]["content"]
        previous_blocks = self._content_blocks(previous)
        next_blocks = self._content_blocks(content)
        messages[-1]["content"] = previous_blocks + next_blocks

    def _content_blocks(self, content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(content, list):
            return content
        return [{"type": "text", "text": content}]

    def _tool_use_block(self, raw_call: dict[str, Any], *, index: int) -> dict[str, Any]:
        if raw_call.get("type") == "tool_use":
            return {
                "type": "tool_use",
                "id": str(raw_call.get("id") or f"call_{index}"),
                "name": str(raw_call.get("name") or ""),
                "input": raw_call.get("input") if isinstance(raw_call.get("input"), dict) else {},
            }
        function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
        arguments = function.get("arguments") or raw_call.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                arguments = {"_raw_arguments": arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        return {
            "type": "tool_use",
            "id": str(raw_call.get("id") or f"call_{index}"),
            "name": str(function.get("name") or raw_call.get("name") or ""),
            "input": arguments,
        }

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = str(function.get("name") or tool.get("name") or "").strip()
            if not name:
                continue
            converted.append(
                {
                    "name": name,
                    "description": str(function.get("description") or tool.get("description") or ""),
                    "input_schema": function.get("parameters") or tool.get("input_schema") or {"type": "object"},
                }
            )
        return converted

    def _parse_tool_calls(self, content_blocks: list[Any]) -> list[LLMToolCall]:
        calls = []
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
            calls.append(
                LLMToolCall(
                    id=str(block.get("id") or "") or None,
                    name=str(block.get("name") or ""),
                    arguments=arguments,
                    raw=block,
                )
            )
        return calls

    def status(self) -> dict:
        return {
            "enabled": True,
            "provider": "anthropic",
            "base_url": self.config.base_url,
            "model": self.config.model,
            "context_window_tokens": self.config.context_window_tokens,
            "multimodal_enabled": self.config.multimodal_enabled,
            "image_input_enabled": self.config.image_input_enabled,
        }


def create_llm_provider(config: AgentLLMConfig) -> LLMProvider:
    if not config.enabled:
        return DisabledLLMProvider()
    if config.provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(config)
    if config.provider == "anthropic":
        return AnthropicLLMProvider(config)
    return DisabledLLMProvider(f"Unsupported LLM provider: {config.provider}")

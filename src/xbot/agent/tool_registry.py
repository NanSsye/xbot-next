from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

ToolCallable = Callable[[dict[str, Any]], Awaitable[Any] | Any]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    risk_level: str
    handler: ToolCallable
    input_schema: dict[str, Any] | None = None
    toolset: str = "core"
    source: str = "builtin"
    cacheable: bool = False
    timeout_seconds: int | None = None
    invalidates_cache: bool = False
    metadata: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._revision = 0

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        self._revision += 1

    def unregister(self, name: str) -> None:
        if name in self._tools:
            del self._tools[name]
            self._revision += 1

    def unregister_source(self, source: str) -> None:
        removed = [name for name, tool in self._tools.items() if tool.source == source]
        for name in removed:
            del self._tools[name]
        if removed:
            self._revision += 1

    def unregister_source_prefix(self, source_prefix: str) -> None:
        removed = [
            name for name, tool in self._tools.items() if tool.source.startswith(source_prefix)
        ]
        for name in removed:
            del self._tools[name]
        if removed:
            self._revision += 1

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def revision(self) -> int:
        return self._revision

    def list_tools(
        self,
        *,
        toolsets: set[str] | None = None,
        platform: str | None = None,
        scope: str | None = None,
        mode: str | None = None,
        include_metadata: bool = True,
    ) -> list[dict]:
        return [
            self._serialize_tool(tool, include_metadata=include_metadata)
            for tool in self._tools.values()
            if self._is_visible(tool, toolsets=toolsets, platform=platform, scope=scope, mode=mode)
        ]

    def _serialize_tool(self, tool: ToolDefinition, *, include_metadata: bool) -> dict:
        item = {
            "name": tool.name,
            "description": tool.description,
            "risk_level": tool.risk_level,
            "input_schema": tool.input_schema or {"type": "object"},
        }
        if include_metadata:
            item.update(
                {
                    "toolset": tool.toolset,
                    "source": tool.source,
                    "cacheable": tool.cacheable,
                    "timeout_seconds": tool.timeout_seconds,
                    "metadata": tool.metadata or {},
                }
            )
        return item

    def _is_visible(
        self,
        tool: ToolDefinition,
        *,
        toolsets: set[str] | None,
        platform: str | None,
        scope: str | None,
        mode: str | None,
    ) -> bool:
        if toolsets is not None and tool.toolset not in toolsets:
            return False
        metadata = tool.metadata or {}
        platforms = set(metadata.get("platforms") or [])
        scopes = set(metadata.get("scopes") or [])
        modes = set(metadata.get("modes") or [])
        if platforms and platform and platform not in platforms:
            return False
        if scopes and scope and scope not in scopes:
            return False
        if modes and mode and mode not in modes:
            return False
        return True

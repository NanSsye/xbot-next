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


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._revision = 0

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        self._revision += 1

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def revision(self) -> int:
        return self._revision

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "risk_level": tool.risk_level,
                "input_schema": tool.input_schema or {"type": "object"},
            }
            for tool in self._tools.values()
        ]

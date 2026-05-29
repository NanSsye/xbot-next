from __future__ import annotations

import inspect
from typing import Any

import anyio

from xbot.agent.tool_registry import ToolRegistry
from xbot.core.exceptions import XBotError


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, name: str, payload: dict[str, Any]) -> Any:
        tool = self.registry.get(name)
        if tool is None:
            raise XBotError(f"Tool not found: {name}")
        result = tool.handler(payload)
        if inspect.isawaitable(result):
            return await result
        return await anyio.to_thread.run_sync(lambda: result)


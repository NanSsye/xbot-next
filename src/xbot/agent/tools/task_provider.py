from __future__ import annotations

from typing import Any, Awaitable, Callable

from xbot.agent.background import BackgroundTaskManager
from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.exceptions import XBotError

ToolExecutorCallback = Callable[[str, dict[str, Any]], Awaitable[Any]]
AgentRunnerCallback = Callable[[str, str], Awaitable[Any]]


def register_task_tools(
    registry: ToolRegistry,
    *,
    background: BackgroundTaskManager,
    execute_tool: ToolExecutorCallback,
    run_agent: AgentRunnerCallback,
) -> None:
    provider = TaskToolProvider(background=background, execute_tool=execute_tool, run_agent=run_agent)
    for tool in provider.tools():
        registry.register(tool)


class TaskToolProvider:
    def __init__(
        self,
        *,
        background: BackgroundTaskManager,
        execute_tool: ToolExecutorCallback,
        run_agent: AgentRunnerCallback,
    ) -> None:
        self.background = background
        self.execute_tool = execute_tool
        self.run_agent = run_agent

    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="task.start",
                description="Start a tool call as a background task and return immediately.",
                risk_level="execute",
                handler=self.start,
                toolset="task",
                source="task",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["tool", "payload"],
                    "properties": {
                        "tool": {"type": "string"},
                        "payload": {"type": "object"},
                        "description": {"type": "string"},
                        "notify": {"type": "object"},
                        "replayable": {"type": "boolean", "default": True},
                    },
                },
            ),
            ToolDefinition(
                name="task.status",
                description="Return background task status and metadata.",
                risk_level="read",
                handler=self.status,
                toolset="task",
                source="task",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="task.agent_start",
                description=(
                    "Start a full child Agent task in the background and return immediately. "
                    "Use this when the user asks for longer work that should continue after the first reply."
                ),
                risk_level="execute",
                handler=self.agent_start,
                toolset="task",
                source="task",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["input"],
                    "properties": {
                        "input": {"type": "string"},
                        "source": {"type": "string", "default": "background"},
                        "description": {"type": "string"},
                        "notify": {"type": "object"},
                        "replayable": {"type": "boolean", "default": True},
                    },
                },
            ),
            ToolDefinition(
                name="task.list",
                description="List recent background tasks.",
                risk_level="read",
                handler=self.list_tasks,
                toolset="task",
                source="task",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 20}},
                },
            ),
            ToolDefinition(
                name="task.cancel",
                description="Cancel a running background task.",
                risk_level="execute",
                handler=self.cancel,
                toolset="task",
                source="task",
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": {"type": "string"}},
                },
            ),
        ]

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool = str(payload["tool"])
        if tool.startswith("task."):
            raise XBotError("task.start cannot start another task.* tool.")
        tool_payload = payload.get("payload") or {}
        if not isinstance(tool_payload, dict):
            raise XBotError("task.start payload must be an object.")

        async def runner():
            return await self.execute_tool(tool, tool_payload)

        record = self.background.start(
            kind="tool",
            runner=runner,
            source="agent",
            description=str(payload.get("description") or f"Run {tool}"),
            metadata={
                "tool": tool,
                "payload": tool_payload,
                "notify": payload.get("notify") if isinstance(payload.get("notify"), dict) else None,
                "replayable": bool(payload.get("replayable", True)),
            },
        )
        return record.model_dump(mode="json")

    async def agent_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        input_text = str(payload.get("input") or "").strip()
        if not input_text:
            raise XBotError("task.agent_start input is required.")
        source = str(payload.get("source") or "background")
        if source.startswith("channel:") or source.startswith("terminal:"):
            source = "background"

        async def runner():
            return await self.run_agent(input_text, source)

        record = self.background.start(
            kind="agent",
            runner=runner,
            source="agent",
            description=str(payload.get("description") or "Run child Agent task"),
            metadata={
                "input": input_text,
                "source": source,
                "notify": payload.get("notify") if isinstance(payload.get("notify"), dict) else None,
                "replayable": bool(payload.get("replayable", True)),
            },
        )
        return record.model_dump(mode="json")

    async def status(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.background.get(str(payload["task_id"]))
        if record is None:
            raise XBotError(f"Background task not found: {payload['task_id']}")
        return record.model_dump(mode="json")

    async def list_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit = int(payload.get("limit", 20))
        return {
            "tasks": [record.model_dump(mode="json") for record in self.background.list(limit)],
        }

    async def cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = await self.background.cancel(str(payload["task_id"]))
        if record is None:
            raise XBotError(f"Background task not found: {payload['task_id']}")
        return record.model_dump(mode="json")

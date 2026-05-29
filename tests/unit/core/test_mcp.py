from types import SimpleNamespace

import pytest

from xbot.agent.mcp import MCPClientManager, MCPServerConnection
from xbot.agent.tool_registry import ToolRegistry
from xbot.core.config import AgentMCPConfig, AgentMCPServerConfig


def test_mcp_tool_names_are_sanitized():
    manager = MCPClientManager(AgentMCPConfig(), ToolRegistry())

    assert manager._tool_name("my-api", "fetch.data") == "mcp_my_api_fetch_data"


@pytest.mark.anyio
async def test_mcp_registers_discovered_tools():
    registry = ToolRegistry()
    manager = MCPClientManager(AgentMCPConfig(), registry)

    class FakeConnection:
        name = "time"
        tools = [
            SimpleNamespace(
                name="get-current-time",
                description="Get current time",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

        async def call_tool(self, tool_name, payload):
            return {"tool": tool_name, "payload": payload}

    manager._register_tools(FakeConnection())
    tool = registry.get("mcp_time_get_current_time")

    assert tool is not None
    assert tool.description == "[MCP:time] Get current time"
    assert await tool.handler({"timezone": "UTC"}) == {
        "tool": "get-current-time",
        "payload": {"timezone": "UTC"},
    }


def test_mcp_stdio_env_is_filtered(monkeypatch):
    monkeypatch.setenv("PATH", "safe")
    monkeypatch.setenv("SECRET_TOKEN", "hidden")
    connection = MCPServerConnection(
        "test",
        AgentMCPServerConfig(command="cmd", env={"EXPLICIT_TOKEN": "allowed"}),
    )

    env = connection._filtered_env()

    assert env["PATH"] == "safe"
    assert env["EXPLICIT_TOKEN"] == "allowed"
    assert "SECRET_TOKEN" not in env

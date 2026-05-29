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
    assert tool.toolset == "mcp"
    assert tool.source == "mcp:time"


@pytest.mark.anyio
async def test_mcp_include_exclude_filters_discovered_tools():
    registry = ToolRegistry()
    config = AgentMCPConfig(
        servers={
            "time": AgentMCPServerConfig(
                include_tools=["get-*"],
                exclude_tools=["get-secret"],
            )
        }
    )
    manager = MCPClientManager(config, registry)
    server_config = config.servers["time"]

    class FakeConnection:
        name = "time"
        config = server_config
        registered_tool_names = []
        tools = [
            SimpleNamespace(name="get-current-time", description="", inputSchema={}),
            SimpleNamespace(name="get-secret", description="", inputSchema={}),
            SimpleNamespace(name="set-current-time", description="", inputSchema={}),
        ]

        async def call_tool(self, tool_name, payload):
            return {}

    connection = FakeConnection()
    manager._register_tools(connection)

    assert registry.get("mcp_time_get_current_time") is not None
    assert registry.get("mcp_time_get_secret") is None
    assert registry.get("mcp_time_set_current_time") is None
    assert connection.registered_tool_names == ["mcp_time_get_current_time"]


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


def test_mcp_status_includes_failed_or_not_connected_servers():
    config = AgentMCPConfig(
        servers={"time": AgentMCPServerConfig(command="cmd")}
    )
    manager = MCPClientManager(config, ToolRegistry())
    manager._server_errors["time"] = "boom"

    status = manager.status()

    assert status["servers"]["time"]["status"] == "not_connected"
    assert status["servers"]["time"]["last_error"] == "boom"

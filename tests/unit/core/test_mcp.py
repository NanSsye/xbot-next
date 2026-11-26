import asyncio
import sys
from functools import partial
from types import SimpleNamespace
from typing import ClassVar

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
        tools: ClassVar[list] = [
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
        registered_tool_names: ClassVar[list] = []
        tools: ClassVar[list] = [
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


@pytest.mark.asyncio
async def test_mcp_sdk_http_and_stdio_sessions_reload_across_tasks(monkeypatch):
    import httpx2
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("test")

    @server.tool()
    def echo(value: str) -> str:
        return value

    app = server.streamable_http_app(json_response=True, stateless_http=True)
    received_headers = []

    async def record_header(scope, receive, send):
        received_headers.append(dict(scope["headers"]).get(b"x-mcp-test"))
        await app(scope, receive, send)

    transport = httpx2.ASGITransport(app=record_header)
    monkeypatch.setattr(httpx2, "AsyncClient", partial(httpx2.AsyncClient, transport=transport))
    config = AgentMCPConfig(enabled=True, servers={
        "http": AgentMCPServerConfig(url="http://127.0.0.1:8000/mcp", headers={"X-MCP-Test": "present"}),
        "stdio": AgentMCPServerConfig(command=sys.executable, args=["-c", """
import asyncio
from mcp.server.mcpserver import MCPServer

server = MCPServer('test')

@server.tool()
def echo(value: str) -> str:
    return value

asyncio.run(server.run_stdio_async())
"""]),
    })
    registry = ToolRegistry()
    manager = MCPClientManager(config, registry)
    async with app.router.lifespan_context(app):
        try:
            await asyncio.create_task(manager.start())
            await asyncio.create_task(manager.reload())
            for name in ("http", "stdio"):
                tool = registry.get(f"mcp_{name}_echo")
                assert tool is not None, manager.status()
                result = await tool.handler({"value": name})
                assert result["content"][0]["text"] == name
        finally:
            await manager.stop()
    assert received_headers and all(header == b"present" for header in received_headers)

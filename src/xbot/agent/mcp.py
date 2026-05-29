from __future__ import annotations

import os
import re
from contextlib import AsyncExitStack
from typing import Any

import anyio

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.config import AgentMCPConfig, AgentMCPServerConfig
from xbot.core.exceptions import XBotError
from xbot.core.logging import logger


SAFE_ENV_KEYS = {"PATH", "HOME", "USER", "USERNAME", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR", "TEMP", "TMP"}


class MCPClientManager:
    def __init__(self, config: AgentMCPConfig, registry: ToolRegistry) -> None:
        self.config = config
        self.registry = registry
        self._servers: dict[str, MCPServerConnection] = {}

    async def start(self) -> None:
        if not self.config.enabled:
            return
        if not self.config.servers:
            logger.info("MCP 未配置 servers，跳过发现")
            return
        if not self._sdk_available():
            logger.warning("MCP SDK 未安装，跳过 MCP 工具发现。安装方式: pip install mcp")
            return
        for name, server_config in self.config.servers.items():
            if not server_config.enabled:
                continue
            if name in self._servers:
                continue
            try:
                connection = MCPServerConnection(name, server_config)
                await connection.connect()
                self._servers[name] = connection
                self._register_tools(connection)
            except Exception as exc:
                logger.warning("MCP server 连接失败: name={} error={}", name, self._redact(str(exc)))

    async def stop(self) -> None:
        for connection in list(self._servers.values()):
            await connection.close()
        self._servers.clear()

    def status(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "servers": {
                name: {"tool_count": len(connection.tools)}
                for name, connection in self._servers.items()
            },
        }

    def _register_tools(self, connection: "MCPServerConnection") -> None:
        for tool in connection.tools:
            tool_name = self._tool_name(connection.name, str(getattr(tool, "name", "")))
            original_name = str(getattr(tool, "name", ""))
            description = str(getattr(tool, "description", "") or f"MCP tool {original_name}")
            input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}

            async def handler(payload: dict, *, server=connection, mcp_tool=original_name):
                return await server.call_tool(mcp_tool, payload)

            self.registry.register(
                ToolDefinition(
                    name=tool_name,
                    description=f"[MCP:{connection.name}] {description}",
                    risk_level="execute",
                    handler=handler,
                    input_schema=input_schema,
                )
            )
            logger.info("MCP 工具已注册: server={} tool={} as={}", connection.name, original_name, tool_name)

    def _tool_name(self, server_name: str, tool_name: str) -> str:
        value = f"mcp_{server_name}_{tool_name}"
        return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")

    def _sdk_available(self) -> bool:
        try:
            import mcp  # noqa: F401
        except ImportError:
            return False
        return True

    def _redact(self, text: str) -> str:
        patterns = (
            r"gh[pousr]_[A-Za-z0-9_]+",
            r"sk-[A-Za-z0-9_-]+",
            r"Bearer\s+[A-Za-z0-9._-]+",
            r"(?i)(token|key|api_key|password|secret)=([^&\s]+)",
        )
        for pattern in patterns:
            text = re.sub(pattern, r"\1=***" if "=" in pattern else "***", text)
        return text


class MCPServerConnection:
    def __init__(self, name: str, config: AgentMCPServerConfig) -> None:
        self.name = name
        self.config = config
        self.stack = AsyncExitStack()
        self.session: Any | None = None
        self.tools: list[Any] = []

    async def connect(self) -> None:
        self._validate_config()
        with anyio.fail_after(max(1, self.config.connect_timeout)):
            if self.config.command:
                await self._connect_stdio()
            else:
                await self._connect_http()
            await self.session.initialize()
            result = await self.session.list_tools()
            self.tools = list(getattr(result, "tools", []) or [])
        logger.info("MCP server 已连接: name={} tools={}", self.name, len(self.tools))

    async def close(self) -> None:
        await self.stack.aclose()

    async def call_tool(self, tool_name: str, payload: dict) -> dict:
        if self.session is None:
            raise XBotError(f"MCP server is not connected: {self.name}")
        try:
            with anyio.fail_after(max(1, self.config.timeout)):
                result = await self.session.call_tool(tool_name, payload or {})
        except Exception as exc:
            raise XBotError(f"MCP tool call failed: {self.name}.{tool_name}: {exc}") from exc
        return self._serialize_result(result)

    async def _connect_stdio(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=str(self.config.command),
            args=[str(item) for item in self.config.args],
            env=self._filtered_env(),
        )
        read_stream, write_stream = await self.stack.enter_async_context(stdio_client(params))
        self.session = await self.stack.enter_async_context(ClientSession(read_stream, write_stream))

    async def _connect_http(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        if not self.config.url:
            raise XBotError(f"MCP server url is required: {self.name}")
        client_result = await self.stack.enter_async_context(
            streamablehttp_client(self.config.url, headers=self.config.headers or None)
        )
        read_stream, write_stream = client_result[0], client_result[1]
        self.session = await self.stack.enter_async_context(ClientSession(read_stream, write_stream))

    def _validate_config(self) -> None:
        has_command = bool(self.config.command)
        has_url = bool(self.config.url)
        if has_command == has_url:
            raise XBotError("MCP server must configure exactly one of command or url.")

    def _filtered_env(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key in SAFE_ENV_KEYS or key.startswith("XDG_")
        }
        env.update({str(key): str(value) for key, value in self.config.env.items()})
        return env

    def _serialize_result(self, result: Any) -> dict:
        content = []
        for item in getattr(result, "content", []) or []:
            if hasattr(item, "model_dump"):
                content.append(item.model_dump(mode="json"))
            elif hasattr(item, "dict"):
                content.append(item.dict())
            else:
                content.append(str(item))
        return {
            "content": content,
            "is_error": bool(getattr(result, "isError", False) or getattr(result, "is_error", False)),
        }

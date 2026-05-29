from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry


COMMON_COMMANDS = ["git", "gh", "node", "npm", "python", "pip", "playwright", "chromium", "chrome"]
COMMON_PORTS = [8080, 5432, 5433, 6379]
SENSITIVE_ENV_TERMS = ("password", "token", "secret", "key")


def register_environment_tools(registry: ToolRegistry, *, workspace) -> None:
    provider = EnvironmentProvider(workspace=workspace)
    for tool in provider.tools():
        registry.register(tool)


class EnvironmentProvider:
    def __init__(self, *, workspace) -> None:
        self.workspace = workspace

    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="environment.snapshot",
                description="Return a safe snapshot of the runtime environment and installed common tools.",
                risk_level="read",
                handler=self.snapshot,
                toolset="environment",
                source="environment",
                cacheable=True,
                timeout_seconds=15,
                input_schema={
                    "type": "object",
                    "properties": {
                        "commands": {"type": "array", "items": {"type": "string"}},
                        "ports": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            ),
            ToolDefinition(
                name="environment.which",
                description="Find executable paths for commands without requiring shell access.",
                risk_level="read",
                handler=self.which,
                toolset="environment",
                source="environment",
                cacheable=True,
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "required": ["commands"],
                    "properties": {"commands": {"type": "array", "items": {"type": "string"}}},
                },
            ),
            ToolDefinition(
                name="environment.ports",
                description="Check whether local TCP ports appear open.",
                risk_level="read",
                handler=self.ports,
                toolset="environment",
                source="environment",
                cacheable=True,
                timeout_seconds=10,
                input_schema={
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "default": "127.0.0.1"},
                        "ports": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            ),
        ]

    async def snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        commands = _string_list(payload.get("commands")) or COMMON_COMMANDS
        ports = _int_list(payload.get("ports")) or COMMON_PORTS
        return {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "platform": platform.platform(),
            },
            "python": {
                "version": sys.version.split()[0],
                "executable": sys.executable,
                "prefix": sys.prefix,
                "virtual_env": os.getenv("VIRTUAL_ENV") or "",
            },
            "workspace": {
                "root": str(self.workspace.root),
                "exists": self.workspace.root.exists(),
                "cwd": str(Path.cwd()),
            },
            "commands": _which_many(commands),
            "ports": _check_ports("127.0.0.1", ports),
            "env": _safe_env_snapshot(),
            "disk": _disk_snapshot(self.workspace.root),
        }

    async def which(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"commands": _which_many(_string_list(payload.get("commands")))}

    async def ports(self, payload: dict[str, Any]) -> dict[str, Any]:
        host = str(payload.get("host") or "127.0.0.1")
        ports = _int_list(payload.get("ports")) or COMMON_PORTS
        return {"host": host, "ports": _check_ports(host, ports)}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        try:
            items.append(int(item))
        except (TypeError, ValueError):
            continue
    return items


def _which_many(commands: list[str]) -> dict[str, dict[str, Any]]:
    return {
        command: {"available": bool(path := shutil.which(command)), "path": path or ""}
        for command in commands
    }


def _check_ports(host: str, ports: list[int]) -> dict[str, dict[str, Any]]:
    results = {}
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            open_ = sock.connect_ex((host, port)) == 0
        results[str(port)] = {"open": open_}
    return results


def _safe_env_snapshot() -> dict[str, dict[str, Any]]:
    selected = [
        "PATH",
        "VIRTUAL_ENV",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "XBOT_CONFIG_FILE",
        "XBOT_AGENT_MODE",
    ]
    items = {}
    for key in selected:
        value = os.getenv(key)
        if value is None:
            items[key] = {"present": False}
            continue
        lower = key.lower()
        if any(term in lower for term in SENSITIVE_ENV_TERMS):
            preview = "<redacted>"
        else:
            preview = value[:120]
        items[key] = {"present": True, "preview": preview, "length": len(value)}
    return items


def _disk_snapshot(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path if path.exists() else Path.cwd())
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
    }

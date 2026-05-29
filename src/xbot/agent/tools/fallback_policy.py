from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xbot.core.exceptions import PolicyDeniedError


@dataclass(slots=True)
class ToolError:
    tool: str
    payload: dict[str, Any]
    error: Exception
    denied: bool = False

    @property
    def message(self) -> str:
        return str(self.error)


class ToolFallbackPolicy:
    def __init__(self, *, policy=None) -> None:
        self.policy = policy

    def explain(self, error: ToolError) -> dict[str, Any]:
        error_type = self._classify(error)
        fallback = {
            "error_type": error_type,
            "message": error.message,
            "retryable": error_type in {"path_not_found", "dependency_missing", "auth_missing", "network_failed", "timeout"},
            "suggested_tool": None,
            "suggested_payload": None,
            "auto_retry": None,
            "guidance": self._guidance(error, error_type),
        }
        self._suggest(error, fallback)
        return fallback

    def _classify(self, error: ToolError) -> str:
        message = error.message.lower()
        if error.denied or isinstance(error.error, PolicyDeniedError):
            return "policy_denied"
        if isinstance(error.error, TimeoutError):
            return "timeout"
        if "path is a directory" in message or "is a directory" in message:
            return "directory_as_file"
        if "no such file" in message or "cannot find" in message or "not found" in message:
            if error.tool.startswith("github.") and ("auth" in message or "login" in message):
                return "auth_missing"
            return "path_not_found"
        if "permission denied" in message or "access is denied" in message:
            return "permission_denied"
        if "playwright" in message and ("install" in message or "require" in message):
            return "dependency_missing"
        if "gh:" in message and ("not logged" in message or "auth" in message):
            return "auth_missing"
        if "timed out" in message or "timeout" in message:
            return "timeout"
        if "network" in message or "connection" in message:
            return "network_failed"
        if "payload" in message or "required" in message:
            return "invalid_payload"
        return "tool_failed"

    def _suggest(self, error: ToolError, fallback: dict[str, Any]) -> None:
        if fallback["error_type"] == "directory_as_file" and error.tool == "filesystem.read_file":
            path = str(error.payload.get("path") or ".")
            fallback["suggested_tool"] = "filesystem.list_dir"
            fallback["suggested_payload"] = {"path": path}
        elif fallback["error_type"] == "path_not_found" and error.tool.startswith("filesystem."):
            path = Path(str(error.payload.get("path") or "."))
            fallback["suggested_tool"] = "filesystem.list_dir"
            fallback["suggested_payload"] = {"path": str(path.parent if str(path.parent) != "" else ".")}
        elif fallback["error_type"] == "dependency_missing":
            fallback["suggested_tool"] = "environment.snapshot"
            fallback["suggested_payload"] = {}
        elif fallback["error_type"] == "auth_missing" and error.tool.startswith("github."):
            fallback["suggested_tool"] = "environment.which"
            fallback["suggested_payload"] = {"commands": ["gh"]}
        elif fallback["error_type"] == "network_failed":
            fallback["suggested_tool"] = "environment.snapshot"
            fallback["suggested_payload"] = {}
        elif fallback["error_type"] == "timeout":
            fallback["suggested_tool"] = "task.start"
            fallback["suggested_payload"] = {
                "tool": error.tool,
                "payload": error.payload,
                "description": f"Retry timed out tool in background: {error.tool}",
                "replayable": True,
            }
            fallback["auto_retry"] = {
                "strategy": "background",
                "max_attempts": 1,
                "allowed_risk_levels": ["read"],
            }

    def _guidance(self, error: ToolError, error_type: str) -> str:
        if error_type == "directory_as_file":
            return "The requested path is a directory. Use filesystem.list_dir before reading a concrete file."
        if error_type == "path_not_found":
            return "The path was not found. List the parent directory to find the correct path before retrying."
        if error_type == "dependency_missing":
            return "A runtime dependency appears missing. Inspect the environment and explain the install step if needed."
        if error_type == "auth_missing":
            return "Authentication appears missing. Inspect the CLI availability and ask the operator to authenticate."
        if error_type == "policy_denied":
            return "The current agent policy denied this operation. Do not retry the same operation unless policy changes."
        if error_type == "timeout":
            return "The tool timed out. Consider a smaller request or running it as a background task."
        return "Use the error message to choose a safer next tool call or provide a concise explanation."

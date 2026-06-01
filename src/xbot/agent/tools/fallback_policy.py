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
            "retryable": error_type
            in {"path_not_found", "dependency_missing", "auth_missing", "network_failed", "timeout", "invalid_payload"},
            "suggested_tool": None,
            "suggested_payload": None,
            "auto_retry": None,
            "guidance": self._guidance(error, error_type),
        }
        self._suggest(error, fallback)
        fallback["repair_steps"] = self._repair_steps(error, error_type, fallback)
        return fallback

    def _classify(self, error: ToolError) -> str:
        message = error.message.lower()
        if error.denied or isinstance(error.error, PolicyDeniedError):
            return "policy_denied"
        if isinstance(error.error, TimeoutError):
            return "timeout"
        if isinstance(error.error, FileNotFoundError):
            return "path_not_found"
        if isinstance(error.error, IsADirectoryError):
            return "directory_as_file"
        if isinstance(error.error, PermissionError):
            return "permission_denied"
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
        if "api key" in message or "apikey" in message or "token" in message and "missing" in message:
            return "auth_missing"
        if "no module named" in message or "module not found" in message or "importerror" in message:
            return "dependency_missing"
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
        elif fallback["error_type"] == "invalid_payload":
            fallback["suggested_tool"] = error.tool
            fallback["suggested_payload"] = self._required_payload_hint(error.tool)
        elif error.tool == "task.status" and "background task not found" in error.message.lower():
            fallback["suggested_tool"] = "task.list"
            fallback["suggested_payload"] = {"limit": 10}

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
        if error_type == "invalid_payload":
            if error.tool == "filesystem.write_file":
                return "Retry filesystem.write_file with both path and content. Do not call it with only content or only a filename."
            if error.tool == "shell.exec":
                return "Retry shell.exec with command. Use cwd only as an optional working directory."
            return "Retry the same tool with all required fields from the tool schema."
        return "Use the error message to choose a safer next tool call or provide a concise explanation."

    def _repair_steps(self, error: ToolError, error_type: str, fallback: dict[str, Any]) -> list[str]:
        if error_type == "invalid_payload":
            return [
                "Read the tool schema from the available tool catalog.",
                "Retry with all required fields present and correct JSON types.",
            ]
        if error_type == "path_not_found":
            return [
                "List the parent directory first.",
                "Find the correct relative path.",
                "Retry the original operation with that path.",
            ]
        if error_type == "directory_as_file":
            return [
                "List the directory contents.",
                "Choose a concrete file path before reading.",
            ]
        if error_type == "dependency_missing":
            return [
                "Inspect the local environment before retrying.",
                "If this is a skill, read its skill.toml/SKILL.md to identify dependencies.",
                "Explain the missing install step if policy does not allow installation.",
            ]
        if error_type == "auth_missing":
            return [
                "Check whether the required key/token/config file exists.",
                "Do not invent credentials.",
                "Ask the operator for the missing credential if it is not available.",
            ]
        if error_type == "timeout":
            return [
                "Retry with a smaller scoped request when possible.",
                "For read-only long work, use task.start so progress can continue in background.",
            ]
        if error_type == "policy_denied":
            return [
                "Do not retry the same blocked operation.",
                "Use a safer read-only tool or ask the operator to change policy.",
            ]
        suggested_tool = fallback.get("suggested_tool")
        if suggested_tool:
            return [f"Call suggested tool {suggested_tool} with suggested_payload before retrying."]
        return ["Use the error and tool output to choose the next safer tool call."]

    def _required_payload_hint(self, tool: str) -> dict[str, Any] | None:
        hints = {
            "filesystem.write_file": {"path": "relative/path.txt", "content": "file content"},
            "filesystem.read_file": {"path": "relative/path.txt"},
            "filesystem.delete_path": {"path": "relative/path.txt", "recursive": False},
            "shell.exec": {"command": "command to run", "cwd": "."},
            "task.status": {"task_id": "known-background-task-id"},
            "skill.run": {"skill": "skill-name", "action": "action-name", "args": {}},
            "skill.manage": {"action": "create|patch|write_file|archive|restore|pin|unpin|usage"},
        }
        return hints.get(tool)

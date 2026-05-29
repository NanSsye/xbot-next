from __future__ import annotations

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry


def register_git_tools(registry: ToolRegistry, *, workspace) -> None:
    for tool in _git_tools(workspace):
        registry.register(tool)


def _git_tools(workspace) -> list[ToolDefinition]:
    async def git_status(payload: dict) -> dict:
        return await workspace.run_shell(
            "git status --short --branch",
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def git_log(payload: dict) -> dict:
        limit = max(1, min(int(payload.get("limit", 10)), 100))
        return await workspace.run_shell(
            f"git log --oneline --decorate -n {limit}",
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def git_diff(payload: dict) -> dict:
        staged = bool(payload.get("staged", False))
        command = "git diff --stat --cached" if staged else "git diff --stat"
        return await workspace.run_shell(
            command,
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_repo_info(payload: dict) -> dict:
        return await workspace.run_shell(
            "gh repo view --json name,owner,visibility,url,defaultBranchRef",
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    common_properties = {
        "cwd": {"type": "string"},
        "timeout_seconds": {"type": "integer", "default": 30},
        "max_output_chars": {"type": "integer", "default": 12000},
    }
    return [
        ToolDefinition(
            name="git.status",
            description="Return git branch and working tree status for a workspace repository.",
            risk_level="read",
            handler=git_status,
            toolset="git",
            source="git",
            cacheable=True,
            timeout_seconds=30,
            input_schema={"type": "object", "properties": common_properties},
        ),
        ToolDefinition(
            name="git.log",
            description="Return recent git commits for a workspace repository.",
            risk_level="read",
            handler=git_log,
            toolset="git",
            source="git",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {**common_properties, "limit": {"type": "integer", "default": 10}},
            },
        ),
        ToolDefinition(
            name="git.diff",
            description="Return git diff stats for a workspace repository.",
            risk_level="read",
            handler=git_diff,
            toolset="git",
            source="git",
            cacheable=False,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {**common_properties, "staged": {"type": "boolean", "default": False}},
            },
        ),
        ToolDefinition(
            name="github.repo_info",
            description="Return GitHub repository metadata using the gh CLI when available.",
            risk_level="read",
            handler=github_repo_info,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={"type": "object", "properties": common_properties},
        ),
    ]

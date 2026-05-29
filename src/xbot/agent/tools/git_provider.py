from __future__ import annotations

import subprocess

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
            _gh_command(["repo", "view", "--json", "name,owner,visibility,url,defaultBranchRef"], payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_issue_list(payload: dict) -> dict:
        args = [
            "issue",
            "list",
            "--state",
            str(payload.get("state", "open")),
            "--limit",
            str(max(1, min(int(payload.get("limit", 20)), 100))),
            "--json",
            "number,title,state,url,author,labels,createdAt,updatedAt",
        ]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_issue_view(payload: dict) -> dict:
        args = [
            "issue",
            "view",
            str(payload["number"]),
            "--json",
            "number,title,state,url,author,body,comments,labels,createdAt,updatedAt",
        ]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 20000)),
        )

    async def github_issue_create(payload: dict) -> dict:
        args = ["issue", "create", "--title", str(payload["title"]), "--body", str(payload.get("body", ""))]
        for label in payload.get("labels", []) or []:
            args.extend(["--label", str(label)])
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_pr_list(payload: dict) -> dict:
        args = [
            "pr",
            "list",
            "--state",
            str(payload.get("state", "open")),
            "--limit",
            str(max(1, min(int(payload.get("limit", 20)), 100))),
            "--json",
            "number,title,state,url,author,headRefName,baseRefName,createdAt,updatedAt",
        ]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_pr_view(payload: dict) -> dict:
        args = [
            "pr",
            "view",
            str(payload["number"]),
            "--json",
            "number,title,state,url,author,body,comments,files,headRefName,baseRefName,createdAt,updatedAt",
        ]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 24000)),
        )

    async def github_pr_comment(payload: dict) -> dict:
        args = ["pr", "comment", str(payload["number"]), "--body", str(payload["body"])]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_graphql(payload: dict) -> dict:
        args = ["api", "graphql", "-f", f"query={payload['query']}"]
        variables = payload.get("variables") or {}
        for key, value in variables.items():
            args.extend(["-f", f"{key}={value}"])
        return await workspace.run_shell(
            _gh_command(args, payload, include_repo=False),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 45)),
            max_output_chars=int(payload.get("max_output_chars", 24000)),
        )

    async def github_workflow_list(payload: dict) -> dict:
        args = ["workflow", "list", "--json", "id,name,state,path"]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def github_run_list(payload: dict) -> dict:
        args = [
            "run",
            "list",
            "--limit",
            str(max(1, min(int(payload.get("limit", 20)), 100))),
            "--json",
            "databaseId,workflowName,displayTitle,status,conclusion,createdAt,updatedAt,url,headBranch,event",
        ]
        if payload.get("workflow"):
            args.extend(["--workflow", str(payload["workflow"])])
        if payload.get("branch"):
            args.extend(["--branch", str(payload["branch"])])
        if payload.get("status"):
            args.extend(["--status", str(payload["status"])])
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 20000)),
        )

    async def github_run_view(payload: dict) -> dict:
        args = [
            "run",
            "view",
            str(payload["run_id"]),
            "--json",
            "databaseId,workflowName,displayTitle,status,conclusion,createdAt,updatedAt,url,headBranch,event,jobs",
        ]
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 24000)),
        )

    async def github_run_logs(payload: dict) -> dict:
        args = ["run", "view", str(payload["run_id"]), "--log"]
        if payload.get("job"):
            args.extend(["--job", str(payload["job"])])
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 60)),
            max_output_chars=int(payload.get("max_output_chars", 50000)),
        )

    async def github_run_rerun(payload: dict) -> dict:
        args = ["run", "rerun", str(payload["run_id"])]
        if payload.get("failed"):
            args.append("--failed")
        return await workspace.run_shell(
            _gh_command(args, payload),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 60)),
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
        ToolDefinition(
            name="github.issue_list",
            description="List GitHub issues using the gh CLI.",
            risk_level="read",
            handler=github_issue_list,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "state": {"type": "string", "default": "open"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        ToolDefinition(
            name="github.issue_view",
            description="View a GitHub issue using the gh CLI.",
            risk_level="read",
            handler=github_issue_view,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {**common_properties, "repo": {"type": "string"}, "number": {"type": "integer"}},
            },
        ),
        ToolDefinition(
            name="github.issue_create",
            description="Create a GitHub issue using the gh CLI.",
            risk_level="write",
            handler=github_issue_create,
            toolset="git",
            source="github",
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        ToolDefinition(
            name="github.pr_list",
            description="List GitHub pull requests using the gh CLI.",
            risk_level="read",
            handler=github_pr_list,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "state": {"type": "string", "default": "open"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        ToolDefinition(
            name="github.pr_view",
            description="View a GitHub pull request using the gh CLI.",
            risk_level="read",
            handler=github_pr_view,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {**common_properties, "repo": {"type": "string"}, "number": {"type": "integer"}},
            },
        ),
        ToolDefinition(
            name="github.pr_comment",
            description="Comment on a GitHub pull request using the gh CLI.",
            risk_level="write",
            handler=github_pr_comment,
            toolset="git",
            source="github",
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["number", "body"],
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "number": {"type": "integer"},
                    "body": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="github.graphql",
            description="Run a GitHub GraphQL query through the gh CLI.",
            risk_level="read",
            handler=github_graphql,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=45,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    **common_properties,
                    "query": {"type": "string"},
                    "variables": {"type": "object", "default": {}},
                },
            },
        ),
        ToolDefinition(
            name="github.workflow_list",
            description="List GitHub Actions workflows using the gh CLI.",
            risk_level="read",
            handler=github_workflow_list,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {**common_properties, "repo": {"type": "string"}},
            },
        ),
        ToolDefinition(
            name="github.run_list",
            description="List GitHub Actions workflow runs using the gh CLI.",
            risk_level="read",
            handler=github_run_list,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "workflow": {"type": "string"},
                    "branch": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        ToolDefinition(
            name="github.run_view",
            description="View a GitHub Actions workflow run using the gh CLI.",
            risk_level="read",
            handler=github_run_view,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {**common_properties, "repo": {"type": "string"}, "run_id": {"type": "integer"}},
            },
        ),
        ToolDefinition(
            name="github.run_logs",
            description="Read logs for a GitHub Actions workflow run using the gh CLI.",
            risk_level="read",
            handler=github_run_logs,
            toolset="git",
            source="github",
            cacheable=True,
            timeout_seconds=60,
            metadata={"background_candidate": True, "background_reason": "GitHub Actions logs can be large"},
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "run_id": {"type": "integer"},
                    "job": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="github.run_rerun",
            description="Rerun a GitHub Actions workflow run using the gh CLI.",
            risk_level="write",
            handler=github_run_rerun,
            toolset="git",
            source="github",
            timeout_seconds=60,
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    **common_properties,
                    "repo": {"type": "string"},
                    "run_id": {"type": "integer"},
                    "failed": {"type": "boolean", "default": False},
                },
            },
        ),
    ]


def _gh_command(args: list[str], payload: dict, *, include_repo: bool = True) -> str:
    command = ["gh", *args]
    if include_repo and payload.get("repo"):
        command.extend(["--repo", str(payload["repo"])])
    return subprocess.list2cmdline(command)

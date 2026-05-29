from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.exceptions import XBotError

SkillRunner = Callable[[dict], Awaitable[dict]]


def register_builtin_tools(
    registry: ToolRegistry,
    *,
    workspace,
    skills,
    run_skill: SkillRunner,
) -> None:
    async def read_file(payload: dict):
        return await workspace.read_text(str(payload["path"]))

    async def write_file(payload: dict):
        await workspace.write_text(str(payload["path"]), str(payload.get("content", "")))
        return {"written": payload["path"]}

    async def list_dir(payload: dict):
        return await workspace.list_dir(str(payload.get("path", ".")))

    async def delete_path(payload: dict):
        return await workspace.delete_path(
            str(payload["path"]),
            recursive=bool(payload.get("recursive", False)),
        )

    async def shell_exec(payload: dict):
        return await workspace.run_shell(
            str(payload["command"]),
            cwd=payload.get("cwd"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_chars=int(payload.get("max_output_chars", 12000)),
        )

    async def skill_list(payload: dict):
        if not skills:
            return []
        return skills.list_skills()

    async def skill_describe(payload: dict):
        name = str(payload["skill"])
        if not skills:
            raise XBotError("Skill manager is not available.")
        instructions = skills.get_instructions(name)
        if instructions is None:
            raise XBotError(f"Skill not found or disabled: {name}")
        path = skills.get_path(name)
        return {
            "name": name,
            "path": str(path) if path else "",
            "instructions": instructions,
        }

    async def skill_run(payload: dict):
        return await run_skill(payload)

    for tool in _builtin_tool_definitions(
        read_file=read_file,
        write_file=write_file,
        list_dir=list_dir,
        delete_path=delete_path,
        shell_exec=shell_exec,
        skill_list=skill_list,
        skill_describe=skill_describe,
        skill_run=skill_run,
    ):
        registry.register(tool)


def _builtin_tool_definitions(**handlers: Callable[[dict[str, Any]], Awaitable[Any]]) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="filesystem.read_file",
            description="Read a UTF-8 text file inside the allowed workspace.",
            risk_level="read",
            handler=handlers["read_file"],
            toolset="filesystem",
            source="builtin",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
        ),
        ToolDefinition(
            name="filesystem.write_file",
            description="Write a UTF-8 text file inside the allowed workspace.",
            risk_level="write",
            handler=handlers["write_file"],
            toolset="filesystem_write",
            source="builtin",
            timeout_seconds=30,
            invalidates_cache=True,
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="filesystem.list_dir",
            description="List files and directories inside the allowed workspace.",
            risk_level="read",
            handler=handlers["list_dir"],
            toolset="filesystem",
            source="builtin",
            cacheable=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
        ),
        ToolDefinition(
            name="filesystem.delete_path",
            description="Delete a file or directory inside the allowed workspace.",
            risk_level="dangerous",
            handler=handlers["delete_path"],
            toolset="filesystem_dangerous",
            source="builtin",
            timeout_seconds=30,
            invalidates_cache=True,
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean", "default": False},
                },
            },
        ),
        ToolDefinition(
            name="shell.exec",
            description="Execute a shell command from an allowed workspace directory.",
            risk_level="execute",
            handler=handlers["shell_exec"],
            toolset="shell",
            source="builtin",
            timeout_seconds=120,
            metadata={"background_candidate": True, "background_reason": "shell commands may take time"},
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "default": 30},
                    "max_output_chars": {"type": "integer", "default": 12000},
                },
            },
        ),
        ToolDefinition(
            name="skill.list",
            description="List enabled skills and their required tools.",
            risk_level="read",
            handler=handlers["skill_list"],
            toolset="core",
            source="builtin",
            cacheable=True,
            timeout_seconds=15,
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="skill.describe",
            description="Return instructions and path for an enabled skill.",
            risk_level="read",
            handler=handlers["skill_describe"],
            toolset="core",
            source="builtin",
            cacheable=True,
            timeout_seconds=15,
            input_schema={
                "type": "object",
                "required": ["skill"],
                "properties": {"skill": {"type": "string"}},
            },
        ),
        ToolDefinition(
            name="skill.run",
            description=(
                "Run a registered skill action. For wechat-869-media-sender, actions are "
                "send-image, send-video, send-voice, send-music, send-link, send-file, send-text."
            ),
            risk_level="execute",
            handler=handlers["skill_run"],
            toolset="skill",
            source="skill",
            timeout_seconds=300,
            metadata={"background_candidate": True, "background_reason": "skill actions may take time"},
            input_schema={
                "type": "object",
                "required": ["skill", "action", "args"],
                "properties": {
                    "skill": {"type": "string"},
                    "action": {"type": "string"},
                    "args": {"type": "object"},
                },
            },
        ),
    ]

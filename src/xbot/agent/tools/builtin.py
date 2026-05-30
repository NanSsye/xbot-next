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
    memory,
    wiki,
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
        if hasattr(skills, "record_use"):
            await skills.record_use(name, "view")
        return {
            "name": name,
            "path": str(path) if path else "",
            "instructions": instructions,
        }

    async def skill_run(payload: dict):
        result = await run_skill(payload)
        if skills and hasattr(skills, "record_use"):
            await skills.record_use(str(payload.get("skill") or ""), "use")
        return result

    async def skill_manage(payload: dict):
        if not skills or not hasattr(skills, "manage"):
            raise XBotError("Skill manager does not support skill.manage.")
        return await skills.manage(payload)

    async def memory_read(payload: dict):
        return memory.read_curated(str(payload.get("target", "memory")))

    async def memory_add(payload: dict):
        return memory.add_curated(
            str(payload.get("target", "memory")),
            str(payload.get("content", "")),
        )

    async def memory_replace(payload: dict):
        return memory.replace_curated(
            str(payload.get("target", "memory")),
            str(payload.get("old_text", "")),
            str(payload.get("content", "")),
        )

    async def memory_remove(payload: dict):
        return memory.remove_curated(
            str(payload.get("target", "memory")),
            str(payload.get("old_text", "")),
        )

    async def wiki_manage(payload: dict):
        if not wiki:
            raise XBotError("Wiki store is not available.")
        return wiki.manage(payload)

    for tool in _builtin_tool_definitions(
        read_file=read_file,
        write_file=write_file,
        list_dir=list_dir,
        delete_path=delete_path,
        shell_exec=shell_exec,
        skill_list=skill_list,
        skill_describe=skill_describe,
        skill_run=skill_run,
        skill_manage=skill_manage,
        memory_read=memory_read,
        memory_add=memory_add,
        memory_replace=memory_replace,
        memory_remove=memory_remove,
        wiki_manage=wiki_manage,
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
        ToolDefinition(
            name="skill.manage",
            description=(
                "Manage agent-owned procedural memory skills under skills/.agent only. "
                "Actions: create, patch, write_file, archive, restore, pin, unpin, usage."
            ),
            risk_level="write",
            handler=handlers["skill_manage"],
            toolset="skill",
            source="skill",
            timeout_seconds=30,
            invalidates_cache=True,
            input_schema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "patch", "write_file", "archive", "restore", "pin", "unpin", "usage"],
                    },
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "content": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "file_path": {"type": "string"},
                    "file_content": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="memory.read",
            description="Read curated long-term memory entries. Targets: memory for agent notes, user for user profile.",
            risk_level="read",
            handler=handlers["memory_read"],
            toolset="memory",
            source="builtin",
            cacheable=False,
            timeout_seconds=10,
            input_schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["memory", "user"], "default": "memory"},
                },
            },
        ),
        ToolDefinition(
            name="memory.add",
            description=(
                "Save a compact durable memory entry for future sessions. Use target=user for "
                "user preferences/profile; target=memory for environment facts and project conventions."
            ),
            risk_level="write",
            handler=handlers["memory_add"],
            toolset="memory",
            source="builtin",
            invalidates_cache=True,
            timeout_seconds=10,
            input_schema={
                "type": "object",
                "required": ["target", "content"],
                "properties": {
                    "target": {"type": "string", "enum": ["memory", "user"]},
                    "content": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="memory.replace",
            description="Replace one curated memory entry identified by a unique old_text substring.",
            risk_level="write",
            handler=handlers["memory_replace"],
            toolset="memory",
            source="builtin",
            invalidates_cache=True,
            timeout_seconds=10,
            input_schema={
                "type": "object",
                "required": ["target", "old_text", "content"],
                "properties": {
                    "target": {"type": "string", "enum": ["memory", "user"]},
                    "old_text": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="memory.remove",
            description="Remove one curated memory entry identified by a unique old_text substring.",
            risk_level="write",
            handler=handlers["memory_remove"],
            toolset="memory",
            source="builtin",
            invalidates_cache=True,
            timeout_seconds=10,
            input_schema={
                "type": "object",
                "required": ["target", "old_text"],
                "properties": {
                    "target": {"type": "string", "enum": ["memory", "user"]},
                    "old_text": {"type": "string"},
                },
            },
        ),
        ToolDefinition(
            name="wiki.manage",
            description=(
                "Manage the file-based Markdown knowledge base. Actions: bootstrap, ingest, query, "
                "read_page, write_page, append_page, suggest_merge, maintain_links, detect_conflicts, "
                "digest, rebuild_index, update_index, lint, log. Markdown files are the source of truth; "
                "vector/RAG indexes are optional derived artifacts."
            ),
            risk_level="write",
            handler=handlers["wiki_manage"],
            toolset="wiki",
            source="builtin",
            invalidates_cache=True,
            timeout_seconds=30,
            input_schema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "bootstrap",
                            "ingest",
                            "query",
                            "read_page",
                            "write_page",
                            "append_page",
                            "suggest_merge",
                            "maintain_links",
                            "detect_conflicts",
                            "digest",
                            "rebuild_index",
                            "update_index",
                            "lint",
                            "log",
                        ],
                    },
                    "wiki": {"type": "string", "default": "xbot"},
                    "topic": {"type": "string"},
                    "source": {"type": "string"},
                    "text": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                    "pages": {"type": "array", "items": {"type": "string"}},
                    "page": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "message": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": True},
                },
            },
        ),
    ]

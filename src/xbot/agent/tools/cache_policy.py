from __future__ import annotations

from typing import Any

from xbot.agent.cache import stable_cache_key
from xbot.agent.tool_registry import ToolDefinition


class ToolCachePolicy:
    def __init__(self, config, workspace, policy, skills) -> None:
        self.config = config
        self.workspace = workspace
        self.policy = policy
        self.skills = skills

    def key_for(self, tool: ToolDefinition, payload: dict[str, Any]) -> str | None:
        if not (
            self.config.cache.enabled
            and self.config.cache.tool_results
            and self.config.cache.tool_result_ttl_seconds > 0
            and tool.cacheable
        ):
            return None
        if tool.name == "filesystem.read_file":
            return self._filesystem_key(tool.name, str(payload["path"]))
        if tool.name == "filesystem.list_dir":
            return self._filesystem_key(tool.name, str(payload.get("path", ".")))
        if tool.name == "skill.list":
            return stable_cache_key(
                {"tool": tool.name, "skills_revision": self._skills_revision()}
            )
        if tool.name == "skill.describe":
            return stable_cache_key(
                {
                    "tool": tool.name,
                    "skill": payload.get("skill"),
                    "skills_revision": self._skills_revision(),
                }
            )
        return stable_cache_key({"tool": tool.name, "payload": payload})

    def _filesystem_key(self, tool_name: str, path: str) -> str:
        target = self.workspace._resolve(path)
        self.policy.assert_file_read_allowed(target)
        stat = target.stat()
        return stable_cache_key(
            {
                "tool": tool_name,
                "path": str(target),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
        )

    def _skills_revision(self) -> int:
        return int(getattr(self.skills, "revision", 0) or 0)

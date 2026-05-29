from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from xbot.core.config import AgentConfig
from xbot.core.exceptions import PolicyDeniedError
from xbot.core.security import is_agent_admin_mode_allowed


class PolicyEngine:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        if config.mode == "admin" and not (config.admin_mode_allowed or is_agent_admin_mode_allowed()):
            raise PolicyDeniedError("Agent admin mode is disabled by environment policy.")

    def snapshot(self) -> dict:
        return self.config.model_dump(mode="json")

    def can_write_files(self) -> bool:
        return self.config.mode == "admin" or self.config.allow_file_write

    def can_execute_shell(self) -> bool:
        return self.config.mode == "admin" or self.config.allow_shell

    def assert_file_read_allowed(self, path: Path) -> None:
        self._assert_path_allowed(path)

    def assert_file_write_allowed(self, path: Path) -> None:
        if not self.can_write_files():
            raise PolicyDeniedError("File write is disabled by agent policy.")
        self._assert_path_allowed(path)

    def assert_file_delete_allowed(self, path: Path) -> None:
        if self.config.mode != "admin" and self.config.approval.delete_files:
            raise PolicyDeniedError("File delete requires approval by agent policy.")
        self._assert_path_allowed(path)

    def assert_shell_allowed(self, cwd: Path | None = None) -> None:
        if not self.can_execute_shell():
            raise PolicyDeniedError("Shell execution is disabled by agent policy.")
        if cwd is not None:
            self._assert_path_allowed(cwd)

    def _assert_path_allowed(self, path: Path) -> None:
        if self.config.mode == "admin" and self.config.workspace.allow_all_filesystem:
            return
        resolved = path.resolve()
        deny_patterns = [str(Path(item).resolve()) for item in self.config.workspace.deny]
        if any(fnmatch(str(resolved), pattern) for pattern in deny_patterns):
            raise PolicyDeniedError(f"Path is denied by agent policy: {resolved}")
        roots = [Path(root).resolve() for root in self.config.workspace.roots]
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise PolicyDeniedError(f"Path is outside allowed workspace roots: {resolved}")

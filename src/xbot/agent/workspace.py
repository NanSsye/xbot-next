from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import anyio

from xbot.agent.policy import PolicyEngine


class Workspace:
    def __init__(self, root: str, policy: PolicyEngine) -> None:
        self.root = Path(root).resolve()
        self.policy = policy

    async def read_text(self, path: str) -> str:
        target = self._resolve(path)
        self.policy.assert_file_read_allowed(target)
        return await anyio.to_thread.run_sync(lambda: target.read_text(encoding="utf-8"))

    async def write_text(self, path: str, content: str) -> None:
        target = self._resolve(path)
        self.policy.assert_file_write_allowed(target)
        await anyio.to_thread.run_sync(self._write_text_sync, target, content)

    async def list_dir(self, path: str = ".") -> list[dict]:
        target = self._resolve(path)
        self.policy.assert_file_read_allowed(target)
        return await anyio.to_thread.run_sync(self._list_dir_sync, target)

    async def delete_path(self, path: str, recursive: bool = False) -> dict:
        target = self._resolve(path)
        self.policy.assert_file_delete_allowed(target)
        return await anyio.to_thread.run_sync(self._delete_path_sync, target, recursive)

    async def run_shell(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int = 30,
        max_output_chars: int = 12000,
    ) -> dict:
        workdir = self._resolve(cwd or ".")
        self.policy.assert_shell_allowed(workdir)
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            timed_out = True
        else:
            timed_out = False
        return {
            "command": command,
            "cwd": str(workdir),
            "returncode": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout.decode(errors="replace")[-max_output_chars:],
            "stderr": stderr.decode(errors="replace")[-max_output_chars:],
        }

    def _resolve(self, path: str) -> Path:
        target = Path(path)
        if not target.is_absolute():
            target = self.root / target
        return target.resolve()

    def _write_text_sync(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _list_dir_sync(self, target: Path) -> list[dict]:
        return [
            {
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else None,
            }
            for item in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name))
        ]

    def _delete_path_sync(self, target: Path, recursive: bool) -> dict:
        if target.is_dir():
            if not recursive:
                target.rmdir()
            else:
                shutil.rmtree(target)
        else:
            target.unlink()
        return {"deleted": str(target), "recursive": recursive}

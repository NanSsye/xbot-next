from __future__ import annotations

from pathlib import Path

from xbot.core.config import SkillConfig
from xbot.core.logging import logger
from xbot.skills.loader import SkillLoader
from xbot.skills.manifest import SkillManifest


class SkillManager:
    """Load and enable framework skills.

    Agent-owned skill creation, curation, and self-improvement now belong to
    embedded Hermes and are persisted under data/hermes.
    """

    def __init__(self, config: SkillConfig, repository_provider=None) -> None:
        self.config = config
        self.repository_provider = repository_provider
        self.loader = SkillLoader()
        self._skills: dict[str, tuple[SkillManifest, str]] = {}
        self._paths: dict[str, Path] = {}
        self._disabled: set[str] = set()
        self._revision = 0

    async def load_all(self) -> None:
        root = Path(self.config.directory)
        if not root.exists():
            return
        for skill_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            try:
                manifest = self.loader.load_manifest(skill_dir)
                self._paths[manifest.name] = skill_dir
                persisted_enabled = await self._get_persisted_enabled(manifest.name)
                enabled = persisted_enabled if persisted_enabled is not None else manifest.enabled
                await self._persist_manifest(manifest, skill_dir, enabled)
                if not enabled:
                    self._disabled.add(manifest.name)
                    continue
                if manifest.name in self._disabled:
                    continue
                instructions = self.loader.load_instructions(skill_dir)
                self._skills[manifest.name] = (manifest, instructions)
            except Exception as exc:
                logger.warning(f"Failed to load skill {skill_dir}: {exc}")
        self._revision += 1

    def list_skills(self) -> list[dict]:
        items: list[dict] = []
        names = sorted(set(self._paths) | set(self._skills))
        for name in names:
            loaded = self._skills.get(name)
            try:
                manifest = loaded[0] if loaded else self.loader.load_manifest(self._paths[name])
            except Exception:
                continue
            items.append(
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "tools": manifest.tools.required,
                    "enabled": manifest.name not in self._disabled and manifest.name in self._skills,
                    "path": str(self._paths.get(manifest.name) or ""),
                }
            )
        return items

    @property
    def revision(self) -> int:
        return self._revision

    async def enable(self, name: str) -> bool:
        if name in self._skills:
            self._disabled.discard(name)
            await self._persist_enabled(name, True)
            self._revision += 1
            return True
        skill_dir = self._paths.get(name)
        if skill_dir is None:
            return False
        manifest = self.loader.load_manifest(skill_dir)
        instructions = self.loader.load_instructions(skill_dir)
        self._disabled.discard(name)
        self._skills[name] = (manifest, instructions)
        await self._persist_enabled(name, True)
        self._revision += 1
        return True

    async def disable(self, name: str) -> bool:
        if name not in self._skills and name not in self._paths:
            return False
        self._disabled.add(name)
        self._skills.pop(name, None)
        await self._persist_enabled(name, False)
        self._revision += 1
        return True

    def get_instructions(self, name: str) -> str | None:
        if name in self._disabled:
            return None
        item = self._skills.get(name)
        return item[1] if item else None

    def get_path(self, name: str) -> Path | None:
        if name in self._disabled:
            return None
        return self._paths.get(name)

    async def _persist_manifest(self, manifest: SkillManifest, skill_dir: Path, enabled: bool) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            await repo.upsert_manifest(manifest, str(skill_dir), enabled)

    async def _persist_enabled(self, name: str, enabled: bool) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            await repo.set_enabled(name, enabled)

    async def _get_persisted_enabled(self, name: str) -> bool | None:
        if not self.repository_provider:
            return None
        async with self.repository_provider() as repo:
            return await repo.get_enabled(name)

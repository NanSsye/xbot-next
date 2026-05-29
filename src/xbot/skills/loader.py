from __future__ import annotations

import tomllib
from pathlib import Path

from xbot.core.exceptions import SkillLoadError
from xbot.skills.manifest import SkillManifest


class SkillLoader:
    def load_manifest(self, skill_dir: Path) -> SkillManifest:
        manifest_path = skill_dir / "skill.toml"
        if not manifest_path.exists():
            raise SkillLoadError(f"Missing skill manifest: {manifest_path}")
        with manifest_path.open("rb") as fh:
            return SkillManifest.model_validate(tomllib.load(fh))

    def load_instructions(self, skill_dir: Path) -> str:
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.exists():
            raise SkillLoadError(f"Missing skill instructions: {skill_path}")
        return skill_path.read_text(encoding="utf-8")


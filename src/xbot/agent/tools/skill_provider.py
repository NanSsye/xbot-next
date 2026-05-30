from __future__ import annotations

import shlex
import sys
from pathlib import Path

from xbot.core.exceptions import XBotError


class SkillToolProvider:
    def __init__(self, *, workspace, skills) -> None:
        self.workspace = workspace
        self.skills = skills

    async def run_skill(self, payload: dict) -> dict:
        if not self.skills:
            raise XBotError("Skill manager is not available.")
        skill_name = str(payload["skill"])
        action = str(payload["action"])
        args = self._skill_args(payload)
        if not isinstance(args, dict):
            raise XBotError("skill.run args must be an object.")
        skill_path = self.skills.get_path(skill_name)
        if skill_path is None:
            raise XBotError(f"Skill not found or disabled: {skill_name}")
        if skill_name == "wechat-869-media-sender":
            return await self._run_wechat_869_media_skill(skill_path, action, args)
        raise XBotError(f"Skill does not expose runnable actions yet: {skill_name}")

    async def _run_wechat_869_media_skill(self, skill_path: Path, action: str, args: dict) -> dict:
        allowed_actions = {
            "send-image": ["to", "path"],
            "send-video": ["to", "path"],
            "send-voice": ["to", "path"],
            "send-music": ["to", "path"],
            "send-link": ["to", "url"],
            "send-file": ["to", "path"],
            "send-text": ["to", "text"],
        }
        if action not in allowed_actions:
            raise XBotError(f"Unsupported wechat-869-media-sender action: {action}")
        missing = [name for name in allowed_actions[action] if not args.get(name)]
        if missing:
            raise XBotError(f"Missing skill.run args: {', '.join(missing)}")
        script = skill_path / "send_869_media.py"
        command_parts = [shlex.quote(sys.executable), shlex.quote(str(script)), action]
        option_map = {
            "to": "--to",
            "path": "--path",
            "thumb": "--thumb",
            "thumb_mode": "--thumb-mode",
            "format": "--format",
            "seconds": "--seconds",
            "url": "--url",
            "title": "--title",
            "desc": "--desc",
            "thumb_url": "--thumb-url",
            "name": "--name",
            "text": "--text",
        }
        for key, option in option_map.items():
            value = args.get(key)
            if value in (None, ""):
                continue
            command_parts.extend([option, shlex.quote(str(value))])
        for at in args.get("at", []) or []:
            command_parts.extend(["--at", shlex.quote(str(at))])
        return await self.workspace.run_shell(
            " ".join(command_parts),
            cwd=".",
            timeout_seconds=int(args.get("timeout_seconds", 300)),
            max_output_chars=int(args.get("max_output_chars", 12000)),
        )

    def _skill_args(self, payload: dict) -> dict:
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            raise XBotError("skill.run args must be an object.")
        merged = dict(args)
        for key, value in payload.items():
            if key in {"skill", "action", "args", "foreground"}:
                continue
            merged.setdefault(key, value)
        return merged

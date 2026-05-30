from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from xbot.core.config import SkillConfig
from xbot.core.logging import logger
from xbot.skills.loader import SkillLoader
from xbot.skills.manifest import SkillManifest


class SkillManager:
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
        skill_dirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        agent_root = self._agent_root()
        if agent_root.exists():
            skill_dirs.extend(p for p in agent_root.iterdir() if p.is_dir() and not p.name.startswith("."))
        for skill_dir in sorted(skill_dirs):
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
        return [
            {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "tools": manifest.tools.required,
                "enabled": manifest.name not in self._disabled,
            }
            for manifest, _ in self._skills.values()
        ]

    def list_agent_owned_skills(self) -> list[dict]:
        usage = self._load_usage()
        items = []
        for name, record in sorted(usage.items()):
            if not isinstance(record, dict) or record.get("created_by") != "agent":
                continue
            path = self._archive_dir() / name if record.get("state") == "archived" else self._agent_skill_dir(name)
            items.append(
                {
                    "name": name,
                    "state": record.get("state", "active"),
                    "pinned": bool(record.get("pinned")),
                    "path": str(path),
                    "use_count": int(record.get("use_count") or 0),
                    "view_count": int(record.get("view_count") or 0),
                    "patch_count": int(record.get("patch_count") or 0),
                    "created_at": record.get("created_at"),
                    "last_use_at": record.get("last_use_at"),
                    "last_view_at": record.get("last_view_at"),
                    "last_patch_at": record.get("last_patch_at"),
                    "archived_at": record.get("archived_at"),
                }
            )
        return items

    def agent_usage_snapshot(self) -> dict:
        return {
            name: record
            for name, record in self._load_usage().items()
            if isinstance(record, dict) and record.get("created_by") == "agent"
        }

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

    async def manage(self, payload: dict) -> dict:
        action = str(payload.get("action") or "")
        if action == "create":
            return await self._manage_create(payload)
        if action == "patch":
            return await self._manage_patch(payload)
        if action == "write_file":
            return await self._manage_write_file(payload)
        if action == "archive":
            return await self._manage_archive(payload)
        if action == "restore":
            return await self._manage_restore(payload)
        if action == "pin":
            return self._manage_pin(str(payload.get("name") or ""), pinned=True)
        if action == "unpin":
            return self._manage_pin(str(payload.get("name") or ""), pinned=False)
        if action == "usage":
            return {"success": True, "usage": self._load_usage()}
        raise ValueError("Unsupported skill.manage action.")

    async def record_use(self, name: str, event: str = "use") -> None:
        if not name or not self._is_agent_owned(name):
            return
        usage = self._load_usage()
        record = usage.setdefault(name, self._usage_record(name))
        key = f"{event}_count"
        record[key] = int(record.get(key) or 0) + 1
        record[f"last_{event}_at"] = self._now()
        self._save_usage(usage)

    async def run_curator(self) -> dict:
        if not self.config.curator_enabled:
            return {"success": True, "enabled": False, "stale": 0, "archived": 0}
        usage = self._load_usage()
        stale = 0
        archived = 0
        for name, record in list(usage.items()):
            if not isinstance(record, dict) or record.get("created_by") != "agent":
                continue
            if record.get("pinned") or record.get("state") == "archived":
                continue
            age_days = self._activity_age_days(record)
            if age_days >= int(self.config.curator_archive_after_days):
                await self._manage_archive({"name": name})
                usage = self._load_usage()
                archived += 1
                continue
            if age_days >= int(self.config.curator_stale_after_days):
                record["state"] = "stale"
                record["stale_at"] = record.get("stale_at") or self._now()
                stale += 1
            else:
                record["state"] = "active"
        self._save_usage(usage)
        return {"success": True, "enabled": True, "stale": stale, "archived": archived, "usage": usage}

    def build_curator_report(self, *, llm_proposals: list[dict] | None = None) -> dict:
        snapshot = self.curator_snapshot()
        proposals = self._rule_curator_proposals(snapshot)
        proposals.extend(self._duplicate_skill_proposals(snapshot))
        proposals.extend(self._normalize_llm_proposals(llm_proposals or [], snapshot))
        report = {
            "success": True,
            "id": str(uuid4()),
            "created_at": self._now(),
            "dry_run": True,
            "summary": self._curator_summary(snapshot, proposals),
            "counts": self._skill_state_counts(snapshot),
            "skills": snapshot,
            "proposals": self._dedupe_proposals(proposals),
        }
        self.save_curator_report(report)
        return report

    def curator_snapshot(self) -> list[dict]:
        items = []
        for item in self.list_agent_owned_skills():
            name = str(item["name"])
            instructions = self.get_instructions(name) or self._archived_instructions(name)
            items.append(
                {
                    **item,
                    "description": self._skill_description(name),
                    "age_days": self._activity_age_days(self._load_usage().get(name, {})),
                    "instructions_preview": instructions[:1600],
                }
            )
        return items

    def save_curator_report(self, report: dict) -> None:
        report_dir = self._curator_report_dir()
        report_dir.mkdir(parents=True, exist_ok=True)
        report_id = str(report.get("id") or "latest")
        payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        (report_dir / f"{report_id}.json").write_text(payload, encoding="utf-8")
        (report_dir / "latest.json").write_text(payload, encoding="utf-8")

    def load_curator_report(self, report_id: str = "latest") -> dict:
        path = self._curator_report_dir() / f"{report_id or 'latest'}.json"
        if not path.exists():
            raise ValueError(f"Curator report not found: {report_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid curator report: {report_id}")
        return data

    async def apply_curator_report(
        self,
        *,
        report_id: str = "latest",
        proposal_ids: list[str] | None = None,
    ) -> dict:
        report = self.load_curator_report(report_id)
        selected = set(proposal_ids or [])
        proposals = report.get("proposals") or []
        results = []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            proposal_id = str(proposal.get("id") or "")
            if selected and proposal_id not in selected:
                continue
            result = await self._apply_curator_proposal(proposal)
            proposal["status"] = result.get("status", "skipped")
            proposal["applied_at"] = self._now() if result.get("status") == "applied" else proposal.get("applied_at")
            results.append({"id": proposal_id, **result})
        report["dry_run"] = False
        report["applied_at"] = self._now()
        self.save_curator_report(report)
        return {"success": True, "report_id": report.get("id"), "results": results}

    async def _manage_create(self, payload: dict) -> dict:
        name = self._validate_agent_skill_name(str(payload.get("name") or ""))
        description = str(payload.get("description") or "")
        content = str(payload.get("content") or "")
        if not description or not content:
            raise ValueError("name, description and content are required.")
        skill_dir = self._agent_skill_dir(name)
        if skill_dir.exists():
            raise ValueError(f"Agent skill already exists: {name}")
        skill_dir.mkdir(parents=True, exist_ok=False)
        (skill_dir / "skill.toml").write_text(
            (
                f'name = "{name}"\n'
                'version = "0.1.0"\n'
                f'description = "{description.replace(chr(34), chr(39))}"\n'
                "enabled = true\n\n"
                "[tools]\n"
                'required = []\n'
            ),
            encoding="utf-8",
        )
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        await self._load_one(skill_dir)
        self._mark_agent_created(name)
        self._revision += 1
        return {"success": True, "action": "create", "name": name, "path": str(skill_dir)}

    async def _manage_patch(self, payload: dict) -> dict:
        name = self._validate_agent_skill_name(str(payload.get("name") or ""))
        old_text = str(payload.get("old_text") or "")
        new_text = str(payload.get("new_text") or payload.get("content") or "")
        file_path = str(payload.get("file_path") or "SKILL.md")
        if not old_text or not new_text:
            raise ValueError("old_text and new_text/content are required.")
        target = self._agent_skill_file(name, file_path)
        text = target.read_text(encoding="utf-8")
        if old_text not in text:
            raise ValueError("old_text was not found.")
        target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        if file_path == "SKILL.md":
            await self._load_one(self._agent_skill_dir(name))
        await self.record_use(name, "patch")
        self._revision += 1
        return {"success": True, "action": "patch", "name": name, "file_path": file_path}

    async def _manage_write_file(self, payload: dict) -> dict:
        name = self._validate_agent_skill_name(str(payload.get("name") or ""))
        file_path = str(payload.get("file_path") or "")
        content = str(payload.get("content") or payload.get("file_content") or "")
        target = self._agent_skill_file(name, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        await self.record_use(name, "patch")
        self._revision += 1
        return {"success": True, "action": "write_file", "name": name, "file_path": file_path}

    async def _manage_archive(self, payload: dict) -> dict:
        name = self._validate_agent_skill_name(str(payload.get("name") or ""))
        usage = self._load_usage()
        if usage.get(name, {}).get("pinned"):
            raise ValueError(f"Skill is pinned: {name}")
        src = self._agent_skill_dir(name)
        if not src.exists():
            raise ValueError(f"Agent skill not found: {name}")
        dst = self._archive_dir() / name
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        self._skills.pop(name, None)
        self._paths.pop(name, None)
        usage.setdefault(name, self._usage_record(name))["state"] = "archived"
        usage[name]["archived_at"] = self._now()
        self._save_usage(usage)
        self._revision += 1
        return {"success": True, "action": "archive", "name": name, "path": str(dst)}

    async def _manage_restore(self, payload: dict) -> dict:
        name = self._validate_agent_skill_name(str(payload.get("name") or ""))
        src = self._archive_dir() / name
        dst = self._agent_skill_dir(name)
        if not src.exists():
            raise ValueError(f"Archived skill not found: {name}")
        if dst.exists():
            raise ValueError(f"Active skill already exists: {name}")
        shutil.move(str(src), str(dst))
        await self._load_one(dst)
        usage = self._load_usage()
        usage.setdefault(name, self._usage_record(name))["state"] = "active"
        usage[name]["restored_at"] = self._now()
        self._save_usage(usage)
        self._revision += 1
        return {"success": True, "action": "restore", "name": name, "path": str(dst)}

    def _manage_pin(self, name: str, *, pinned: bool) -> dict:
        name = self._validate_agent_skill_name(name)
        usage = self._load_usage()
        usage.setdefault(name, self._usage_record(name))["pinned"] = pinned
        self._save_usage(usage)
        return {"success": True, "action": "pin" if pinned else "unpin", "name": name, "pinned": pinned}

    async def _load_one(self, skill_dir: Path) -> None:
        manifest = self.loader.load_manifest(skill_dir)
        self._paths[manifest.name] = skill_dir
        self._disabled.discard(manifest.name)
        self._skills[manifest.name] = (manifest, self.loader.load_instructions(skill_dir))
        await self._persist_manifest(manifest, skill_dir, True)

    def _agent_root(self) -> Path:
        return Path(self.config.directory) / ".agent"

    def _archive_dir(self) -> Path:
        return self._agent_root() / ".archive"

    def _curator_report_dir(self) -> Path:
        return self._agent_root() / ".curator"

    def _usage_path(self) -> Path:
        return self._agent_root() / ".usage.json"

    def _agent_skill_dir(self, name: str) -> Path:
        return self._agent_root() / name

    def _is_agent_owned(self, name: str) -> bool:
        usage = self._load_usage()
        if usage.get(name, {}).get("created_by") == "agent":
            return True
        path = self._paths.get(name)
        if path is None:
            return False
        try:
            path.resolve().relative_to(self._agent_root().resolve())
            return True
        except (OSError, ValueError):
            return False

    def _agent_skill_file(self, name: str, file_path: str) -> Path:
        base = self._agent_skill_dir(name).resolve()
        target = (base / file_path).resolve()
        allowed_parts = {"SKILL.md", "references", "templates", "scripts", "assets"}
        first = Path(file_path).parts[0] if Path(file_path).parts else ""
        if first not in allowed_parts or target == base or base not in target.parents:
            raise ValueError("file_path must be SKILL.md or under references/templates/scripts/assets.")
        return target

    def _validate_agent_skill_name(self, name: str) -> str:
        import re

        name = name.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
            raise ValueError("Invalid skill name.")
        return name

    def _load_usage(self) -> dict:
        path = self._usage_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_usage(self, usage: dict) -> None:
        path = self._usage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(usage, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _mark_agent_created(self, name: str) -> None:
        usage = self._load_usage()
        usage[name] = self._usage_record(name)
        self._save_usage(usage)

    def _usage_record(self, name: str) -> dict:
        now = self._now()
        return {
            "name": name,
            "created_by": "agent",
            "state": "active",
            "pinned": False,
            "created_at": now,
            "use_count": 0,
            "view_count": 0,
            "patch_count": 0,
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _activity_age_days(self, record: dict) -> float:
        raw = (
            record.get("last_use_at")
            or record.get("last_view_at")
            or record.get("last_patch_at")
            or record.get("created_at")
        )
        try:
            timestamp = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return 0
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - timestamp).total_seconds() / 86400

    def _rule_curator_proposals(self, snapshot: list[dict]) -> list[dict]:
        proposals = []
        for item in snapshot:
            name = str(item.get("name") or "")
            if not name or item.get("pinned") or item.get("state") == "archived":
                continue
            age_days = float(item.get("age_days") or 0)
            if age_days >= int(self.config.curator_archive_after_days):
                proposals.append(
                    self._proposal(
                        action="archive",
                        target=name,
                        reason=f"规则建议归档：{age_days:.1f} 天未使用，超过 archive 阈值。",
                        confidence=0.8,
                        source="rule",
                    )
                )
            elif age_days >= int(self.config.curator_stale_after_days):
                proposals.append(
                    self._proposal(
                        action="mark_stale",
                        target=name,
                        reason=f"规则建议标记 stale：{age_days:.1f} 天未使用，超过 stale 阈值。",
                        confidence=0.7,
                        source="rule",
                    )
                )
        return proposals

    def _duplicate_skill_proposals(self, snapshot: list[dict]) -> list[dict]:
        proposals = []
        active = [item for item in snapshot if item.get("state") != "archived"]
        for index, left in enumerate(active):
            for right in active[index + 1 :]:
                score = self._skill_similarity(left, right)
                if score < 0.55:
                    continue
                target = self._merge_target(left, right)
                source = right if target == left.get("name") else left
                proposals.append(
                    self._proposal(
                        action="merge",
                        target=str(target),
                        source_skill=str(source.get("name") or ""),
                        reason=(
                            "疑似重复 skill："
                            f"{left.get('name')} 与 {right.get('name')} 相似度 {score:.2f}。"
                        ),
                        confidence=min(0.95, score),
                        source="heuristic",
                    )
                )
        return proposals

    def _normalize_llm_proposals(self, proposals: list[dict], snapshot: list[dict]) -> list[dict]:
        known = {str(item.get("name")) for item in snapshot}
        normalized = []
        for item in proposals:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            target = str(item.get("target") or item.get("name") or "").strip()
            if action not in {"archive", "mark_stale", "merge", "pin", "unpin"}:
                continue
            if target not in known:
                continue
            source_skill = str(item.get("source_skill") or "").strip()
            if source_skill and source_skill not in known:
                source_skill = ""
            normalized.append(
                self._proposal(
                    action=action,
                    target=target,
                    source_skill=source_skill,
                    reason=str(item.get("reason") or "LLM curator suggestion").strip(),
                    confidence=float(item.get("confidence") or 0.5),
                    source="llm",
                    merged_content=str(item.get("merged_content") or ""),
                )
            )
        return normalized

    def _dedupe_proposals(self, proposals: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for item in proposals:
            key = (item.get("action"), item.get("target"), item.get("source_skill"))
            if key in seen:
                continue
            seen.add(key)
            item["id"] = item.get("id") or f"p{len(result) + 1}"
            result.append(item)
        return result

    async def _apply_curator_proposal(self, proposal: dict) -> dict:
        action = str(proposal.get("action") or "")
        target = str(proposal.get("target") or "")
        if action == "archive":
            return {"status": "applied", "result": await self._manage_archive({"name": target})}
        if action == "mark_stale":
            usage = self._load_usage()
            usage.setdefault(target, self._usage_record(target))["state"] = "stale"
            usage[target]["stale_at"] = self._now()
            self._save_usage(usage)
            return {"status": "applied", "result": {"action": "mark_stale", "name": target}}
        if action in {"pin", "unpin"}:
            return {
                "status": "applied",
                "result": self._manage_pin(target, pinned=(action == "pin")),
            }
        if action == "merge":
            source_skill = str(proposal.get("source_skill") or "")
            merged_content = str(proposal.get("merged_content") or "")
            if not source_skill:
                return {"status": "skipped", "reason": "merge proposal has no source_skill"}
            if merged_content:
                await self._manage_write_file(
                    {"name": target, "file_path": "SKILL.md", "content": merged_content}
                )
            archive_result = await self._manage_archive({"name": source_skill})
            return {
                "status": "applied",
                "result": {
                    "action": "merge",
                    "target": target,
                    "source_skill": source_skill,
                    "source_archived": archive_result,
                    "content_updated": bool(merged_content),
                },
            }
        return {"status": "skipped", "reason": f"unsupported action: {action}"}

    def _proposal(
        self,
        *,
        action: str,
        target: str,
        reason: str,
        confidence: float,
        source: str,
        source_skill: str = "",
        merged_content: str = "",
    ) -> dict:
        return {
            "id": "",
            "action": action,
            "target": target,
            "source_skill": source_skill,
            "reason": reason,
            "confidence": round(max(0.0, min(float(confidence), 1.0)), 2),
            "source": source,
            "status": "pending",
            "merged_content": merged_content,
        }

    def _skill_description(self, name: str) -> str:
        item = self._skills.get(name)
        if not item:
            return ""
        return item[0].description

    def _archived_instructions(self, name: str) -> str:
        path = self._archive_dir() / name / "SKILL.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _skill_state_counts(self, snapshot: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for item in snapshot:
            state = str(item.get("state") or "active")
            counts[state] = counts.get(state, 0) + 1
        return counts

    def _curator_summary(self, snapshot: list[dict], proposals: list[dict]) -> dict:
        by_action: dict[str, int] = {}
        for item in proposals:
            action = str(item.get("action") or "")
            by_action[action] = by_action.get(action, 0) + 1
        return {
            "skill_count": len(snapshot),
            "proposal_count": len(proposals),
            "by_action": by_action,
        }

    def _skill_similarity(self, left: dict, right: dict) -> float:
        left_tokens = self._skill_tokens(left)
        right_tokens = self._skill_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return overlap / union if union else 0.0

    def _skill_tokens(self, item: dict) -> set[str]:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("name", "description", "instructions_preview")
        ).lower()
        return {
            token
            for token in re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", text)
            if token not in {"skill", "workflow", "agent", "the", "and", "for", "with"}
        }

    def _merge_target(self, left: dict, right: dict) -> str:
        left_score = int(left.get("use_count") or 0) + int(left.get("view_count") or 0) + int(left.get("patch_count") or 0)
        right_score = int(right.get("use_count") or 0) + int(right.get("view_count") or 0) + int(right.get("patch_count") or 0)
        if left.get("pinned") and not right.get("pinned"):
            return str(left.get("name") or "")
        if right.get("pinned") and not left.get("pinned"):
            return str(right.get("name") or "")
        return str(left.get("name") if left_score >= right_score else right.get("name"))

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

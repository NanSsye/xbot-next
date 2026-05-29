from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xbot.skills.manifest import SkillManifest
from xbot.storage.models import SkillRecord


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_manifest(self, manifest: SkillManifest, path: str, enabled: bool) -> None:
        record = await self.get_record(manifest.name)
        now = datetime.utcnow()
        if record:
            record.version = manifest.version
            record.enabled = enabled
            record.path = path
            record.updated_at = now
        else:
            self.session.add(
                SkillRecord(
                    name=manifest.name,
                    version=manifest.version,
                    enabled=enabled,
                    path=path,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def set_enabled(self, name: str, enabled: bool) -> bool:
        record = await self.get_record(name)
        if record is None:
            return False
        record.enabled = enabled
        record.updated_at = datetime.utcnow()
        return True

    async def get_enabled(self, name: str) -> bool | None:
        record = await self.get_record(name)
        return record.enabled if record else None

    async def list_records(self) -> list[SkillRecord]:
        result = await self.session.execute(select(SkillRecord).order_by(SkillRecord.name))
        return list(result.scalars().all())

    async def get_record(self, name: str) -> SkillRecord | None:
        result = await self.session.execute(select(SkillRecord).where(SkillRecord.name == name))
        return result.scalar_one_or_none()

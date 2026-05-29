from __future__ import annotations

from pydantic import BaseModel, Field


class SkillTools(BaseModel):
    required: list[str] = Field(default_factory=list)


class SkillManifest(BaseModel):
    name: str
    version: str = "0.0.0"
    description: str | None = None
    enabled: bool = True
    tools: SkillTools = Field(default_factory=SkillTools)


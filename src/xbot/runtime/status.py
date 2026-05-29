from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RuntimeStatus(BaseModel):
    state: Literal["created", "starting", "running", "stopping", "stopped"] = "created"
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    plugin_count: int = 0
    skill_count: int = 0
    adapter_count: int = 0
    agent_enabled: bool = False
    details: dict[str, str] = Field(default_factory=dict)


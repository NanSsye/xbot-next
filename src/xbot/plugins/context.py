from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from xbot.messaging.models import Reply


@dataclass(slots=True)
class PluginContext:
    name: str
    data_dir: Path
    config: dict[str, Any]
    plugins: Any | None = None
    agent: Any | None = None
    send_reply: Callable[[Reply], Awaitable[None]] | None = None
    conversations: Any | None = None
    settings: Any | None = None

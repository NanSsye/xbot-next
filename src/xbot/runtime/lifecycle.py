from __future__ import annotations

from xbot.runtime.engine import XBotEngine


class LifecycleManager:
    def __init__(self, engine: XBotEngine) -> None:
        self.engine = engine

    async def start(self) -> None:
        await self.engine.start()

    async def stop(self) -> None:
        await self.engine.stop()


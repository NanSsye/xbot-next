from __future__ import annotations

from xbot.messaging.models import Message
from xbot.plugins.context import PluginContext


class PluginBase:
    name: str = "plugin"
    version: str = "0.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        return None

    async def on_unload(self) -> None:
        return None

    async def on_message(self, message: Message, ctx: PluginContext) -> None:
        return None


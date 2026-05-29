from __future__ import annotations

from xbot.messaging.models import Reply


class ReplyRouter:
    async def route(self, reply: Reply) -> Reply:
        return reply


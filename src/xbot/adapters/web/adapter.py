from __future__ import annotations

from xbot.adapters.base import BaseAdapter
from xbot.messaging.models import Message, Reply


class WebAdapter(BaseAdapter):
    name = "web"
    platform = "web"

    def __init__(self) -> None:
        self.started = False
        self.sent_replies: list[Reply] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send(self, reply: Reply) -> None:
        self.sent_replies.append(reply)

    async def normalize(self, raw: dict) -> Message:
        return Message(
            platform="web",
            adapter=self.name,
            conversation_id=str(raw.get("conversation_id", "default")),
            sender_id=str(raw.get("sender_id", "user")),
            sender_name=raw.get("sender_name"),
            content=raw.get("content"),
            raw=raw,
        )


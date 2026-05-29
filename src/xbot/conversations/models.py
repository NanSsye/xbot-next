from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from xbot.messaging.models import Message

ConversationScope = Literal["private", "group", "channel", "agent_task", "system"]


class Conversation(BaseModel):
    id: str
    platform: str
    adapter: str
    scope: ConversationScope = "private"
    raw_id: str
    title: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationContext(BaseModel):
    conversation: Conversation
    messages: list[Message]
    summaries: list["ConversationSummary"] = Field(default_factory=list)
    state: dict[str, dict] = Field(default_factory=dict)


class ConversationSummary(BaseModel):
    id: int | None = None
    conversation_id: str
    summary: str
    from_message_id: str | None = None
    to_message_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


def build_conversation_id(
    platform: str, adapter: str, scope: ConversationScope, raw_id: str
) -> str:
    return f"{platform}:{adapter}:{scope}:{raw_id}"

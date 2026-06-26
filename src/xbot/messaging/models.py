from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MessageType = Literal["text", "image", "file", "event"]
ReplyType = Literal["text", "image", "file", "event"]


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    platform: str
    adapter: str
    type: MessageType = "text"
    conversation_id: str
    sender_id: str
    sender_name: str | None = None
    content: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Reply(BaseModel):
    platform: str
    adapter: str
    conversation_id: str
    type: ReplyType = "text"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    quote_message_id: str | None = None


class MessageEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    dedupe_key: str
    message: Message
    delivery_attempts: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    available_at: datetime | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_message(cls, message: Message, dedupe_key: str | None = None) -> "MessageEnvelope":
        return cls(
            dedupe_key=dedupe_key or default_dedupe_key(message),
            message=message,
        )


def default_dedupe_key(message: Message) -> str:
    raw_id = message.raw.get("id") or message.raw.get("message_id") or message.raw.get("msg_id")
    if raw_id:
        return f"{message.platform}:{message.adapter}:{raw_id}"
    content_hash = str(abs(hash(message.content or "")))
    return (
        f"{message.platform}:{message.adapter}:{message.conversation_id}:"
        f"{message.sender_id}:{message.timestamp.isoformat()}:{content_hash}"
    )

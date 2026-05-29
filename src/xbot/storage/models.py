from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PluginRecord(Base):
    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    version: Mapped[str] = mapped_column(String(64), default="0.0.0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SkillRecord(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    version: Mapped[str] = mapped_column(String(64), default="0.0.0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentEventRecord(Base):
    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentTaskRecord(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    input: Mapped[str] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentMemoryRecord(Base):
    __tablename__ = "agent_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(128), default="global", index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128), default="agent", index=True)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    summary: Mapped[str] = mapped_column(Text)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    importance: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentMemoryLinkRecord(Base):
    __tablename__ = "agent_memory_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    relation: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentArtifactRecord(Base):
    __tablename__ = "agent_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(String(256), index=True)
    sender_id: Mapped[str] = mapped_column(String(256), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReplyRecord(Base):
    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(String(256), index=True)
    type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    quote_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MessageEnvelopeRecord(Base):
    __tablename__ = "message_envelopes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    headers_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeadLetterRecord(Base):
    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    queue_name: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(512), primary_key=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)
    raw_id: Mapped[str] = mapped_column(String(256), index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationMemberRecord(Base):
    __tablename__ = "conversation_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    user_id: Mapped[str] = mapped_column(String(256), index=True)
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    sender_id: Mapped[str] = mapped_column(String(256), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationStateRecord(Base):
    __tablename__ = "conversation_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    namespace: Mapped[str] = mapped_column(String(256), index=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationSummaryRecord(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    summary: Mapped[str] = mapped_column(Text)
    from_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

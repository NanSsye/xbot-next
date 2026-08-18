from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


EXTERNAL_MESSAGE_ID_LENGTH = 512


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


class AgentBackgroundTaskRecord(Base):
    __tablename__ = "agent_background_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentScheduledJobRecord(Base):
    __tablename__ = "agent_scheduled_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    schedule_type: Mapped[str] = mapped_column(String(32), index=True)
    schedule_expr: Mapped[str] = mapped_column(Text)
    schedule_display: Mapped[str] = mapped_column(String(256), default="")
    timezone: Mapped[str] = mapped_column(String(128), default="Asia/Shanghai")
    input: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(256), index=True)
    reply_policy: Mapped[str] = mapped_column(String(64), default="parent_agent")
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    last_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdapterStateRecord(Base):
    __tablename__ = "adapter_states"

    adapter: Mapped[str] = mapped_column(String(128), primary_key=True)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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

    id: Mapped[str] = mapped_column(String(EXTERNAL_MESSAGE_ID_LENGTH), primary_key=True)
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
    quote_message_id: Mapped[str | None] = mapped_column(
        String(EXTERNAL_MESSAGE_ID_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuntimeScheduledJobRecord(Base):
    __tablename__ = "runtime_scheduled_jobs"
    __table_args__ = (
        Index("ix_runtime_scheduled_jobs_due", "next_run_at", "lease_expires_at"),
    )

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReplyOutboxRecord(Base):
    __tablename__ = "reply_outbox"
    __table_args__ = (
        Index(
            "ix_reply_outbox_dispatch",
            "status",
            "available_at",
            "lease_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    reply_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    available_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    platform_message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MessageEnvelopeRecord(Base):
    __tablename__ = "message_envelopes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    message_id: Mapped[str] = mapped_column(String(EXTERNAL_MESSAGE_ID_LENGTH), index=True)
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
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_persona_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_persona_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_persona_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agent_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationMemberRecord(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (Index("ix_conversation_members_conversation_user", "conversation_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    user_id: Mapped[str] = mapped_column(String(256), index=True)
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_conversation_messages_conversation_sender_created", "conversation_id", "sender_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    message_id: Mapped[str] = mapped_column(String(EXTERNAL_MESSAGE_ID_LENGTH), index=True)
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
    from_message_id: Mapped[str | None] = mapped_column(
        String(EXTERNAL_MESSAGE_ID_LENGTH), nullable=True
    )
    to_message_id: Mapped[str | None] = mapped_column(
        String(EXTERNAL_MESSAGE_ID_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContactRecord(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("platform", "adapter", "user_id", name="uq_contacts_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(256), index=True)
    nickname: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MessageAttachmentRecord(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (Index("ix_message_attachments_conversation_sender_kind", "conversation_id", "sender_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(EXTERNAL_MESSAGE_ID_LENGTH), index=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    sender_id: Mapped[str] = mapped_column(String(256), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    download_status: Mapped[str] = mapped_column(String(64), default="metadata_only")
    quoted: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserProfileRecord(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("platform", "adapter", "user_id", "conversation_id", name="uq_user_profiles_scope"),
        Index("ix_user_profiles_scope_lookup", "platform", "adapter", "conversation_id", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(64))
    adapter: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(256), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityConfigRecord(Base):
    __tablename__ = "community_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupKnowledgeBaseRecord(Base):
    __tablename__ = "group_knowledge_bases"

    conversation_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=43200)
    cursor_record_id: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    person_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupKnowledgeRunRecord(Base):
    __tablename__ = "group_knowledge_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_group_knowledge_run_idempotency"),
        Index("ix_group_knowledge_runs_conversation_started", "conversation_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), index=True)
    from_cursor: Mapped[int] = mapped_column(Integer, default=0)
    to_cursor: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    page_change_count: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class GroupKnowledgeSourceRecord(Base):
    __tablename__ = "group_knowledge_sources"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "source_type", "source_key",
            name="uq_group_knowledge_source_scope",
        ),
        Index("ix_group_knowledge_sources_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_key: Mapped[str] = mapped_column(String(512))
    message_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(EXTERNAL_MESSAGE_ID_LENGTH), nullable=True)
    attachment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extract_status: Mapped[str] = mapped_column(String(32), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupKnowledgePageRecord(Base):
    __tablename__ = "group_knowledge_pages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "relative_path", name="uq_group_knowledge_page_path"),
        Index("ix_group_knowledge_pages_conversation_updated", "conversation_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    relative_path: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    source_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    content_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityAccountRecord(Base):
    __tablename__ = "community_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invite_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityIdentityRecord(Base):
    __tablename__ = "community_identities"
    __table_args__ = (
        UniqueConstraint("platform", "adapter", "user_id", name="uq_community_identity_user"),
        UniqueConstraint(
            "account_id", "platform", "adapter", name="uq_community_identity_account_channel"
        ),
        Index("ix_community_identities_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(64))
    adapter: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(256))
    nickname: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityPointLedgerRecord(Base):
    __tablename__ = "community_point_ledger"
    __table_args__ = (
        Index("ix_community_ledger_account_created", "account_id", "created_at"),
        Index("ix_community_ledger_effective_date", "effective_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer)
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64), index=True)
    reference_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityTokenExchangeRecord(Base):
    __tablename__ = "community_token_exchanges"
    __table_args__ = (
        Index("ix_community_token_exchange_account_created", "account_id", "created_at"),
        Index("ix_community_token_exchange_account_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer)
    points_cost: Mapped[int] = mapped_column(Integer)
    token_amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunityCharacterImageExchangeRecord(Base):
    __tablename__ = "community_character_image_exchanges"
    __table_args__ = (
        Index("ix_community_character_image_exchange_account_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer)
    points_cost: Mapped[int] = mapped_column(Integer)
    image_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunityRedPacketRecord(Base):
    __tablename__ = "community_red_packets"
    __table_args__ = (
        Index("ix_community_red_packet_conversation_status", "conversation_id", "status"),
        Index("ix_community_red_packet_creator_created", "creator_account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    packet_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    creator_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creator_user_id: Mapped[str] = mapped_column(String(256))
    creator_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    conversation_id: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    total_points: Mapped[int] = mapped_column(Integer)
    packet_count: Mapped[int] = mapped_column(Integer)
    remaining_points: Mapped[int] = mapped_column(Integer)
    remaining_count: Mapped[int] = mapped_column(Integer)
    allocations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunityRedPacketClaimRecord(Base):
    __tablename__ = "community_red_packet_claims"
    __table_args__ = (
        UniqueConstraint("packet_id", "account_id", name="uq_community_red_packet_claim"),
        Index("ix_community_red_packet_claim_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    packet_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityCheckinRecord(Base):
    __tablename__ = "community_checkins"
    __table_args__ = (
        UniqueConstraint("account_id", "checkin_date", name="uq_community_checkin_day"),
        Index("ix_community_checkins_account_date", "account_id", "checkin_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer)
    checkin_date: Mapped[date] = mapped_column(Date)
    streak: Mapped[int] = mapped_column(Integer)
    reward: Mapped[int] = mapped_column(Integer)
    conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityGamePlayRecord(Base):
    __tablename__ = "community_game_plays"
    __table_args__ = (
        Index("ix_community_game_account_day", "account_id", "game", "play_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer)
    game: Mapped[str] = mapped_column(String(32))
    play_date: Mapped[date] = mapped_column(Date)
    reference_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    points_delta: Mapped[int] = mapped_column(Integer, default=0)
    conversation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityTreasureClaimRecord(Base):
    __tablename__ = "community_treasure_claims"
    __table_args__ = (
        UniqueConstraint("account_id", "claim_date", name="uq_community_treasure_account_day"),
        Index("ix_community_treasure_claim_date", "claim_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer)
    claim_date: Mapped[date] = mapped_column(Date)
    conversation_id: Mapped[str] = mapped_column(String(512))
    box_number: Mapped[int] = mapped_column(Integer)
    reward: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityBossRecord(Base):
    __tablename__ = "community_bosses"
    __table_args__ = (
        UniqueConstraint("conversation_id", "boss_date", name="uq_community_boss_conversation_day"),
        Index("ix_community_boss_date_status", "boss_date", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512))
    boss_date: Mapped[date] = mapped_column(Date)
    max_hp: Mapped[int] = mapped_column(Integer)
    remaining_hp: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="active")
    participant_count: Mapped[int] = mapped_column(Integer, default=0)
    payout_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    defeated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunityBossAttackRecord(Base):
    __tablename__ = "community_boss_attacks"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_community_boss_attack_event"),
        UniqueConstraint(
            "boss_id", "account_id", "attack_index", name="uq_community_boss_attack_index"
        ),
        Index("ix_community_boss_attack_boss_account", "boss_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    boss_id: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(String(EXTERNAL_MESSAGE_ID_LENGTH))
    attack_index: Mapped[int] = mapped_column(Integer)
    damage: Mapped[int] = mapped_column(Integer)
    reward: Mapped[int] = mapped_column(Integer)
    pool_reward: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityHorseRaceRecord(Base):
    __tablename__ = "community_horse_races"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "race_date", "race_hour", name="uq_community_horse_race_round"
        ),
        Index("ix_community_horse_race_status", "status", "race_date", "race_hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512))
    platform: Mapped[str] = mapped_column(String(64))
    adapter: Mapped[str] = mapped_column(String(64))
    race_date: Mapped[date] = mapped_column(Date)
    race_hour: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="active")
    winning_horse: Mapped[int | None] = mapped_column(Integer, nullable=True)
    participant_count: Mapped[int] = mapped_column(Integer, default=0)
    winner_count: Mapped[int] = mapped_column(Integer, default=0)
    payout_total: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunityHorseRaceBetRecord(Base):
    __tablename__ = "community_horse_race_bets"
    __table_args__ = (
        UniqueConstraint("race_id", "account_id", name="uq_community_horse_race_bet_account"),
        Index("ix_community_horse_race_bet_horse", "race_id", "horse_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    race_id: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(Integer)
    horse_number: Mapped[int] = mapped_column(Integer)
    nickname: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reward: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityHighLowWagerRecord(Base):
    __tablename__ = "community_high_low_wagers"
    __table_args__ = (
        Index("ix_community_high_low_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wager_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer)
    conversation_id: Mapped[str] = mapped_column(String(512))
    amount: Mapped[int] = mapped_column(Integer)
    choice: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    roll: Mapped[int | None] = mapped_column(Integer, nullable=True)
    won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payout: Mapped[int] = mapped_column(Integer, default=0)
    net_points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunityActivitySettlementRecord(Base):
    __tablename__ = "community_activity_settlements"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "activity_date", name="uq_community_activity_settlement"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512), index=True)
    activity_date: Mapped[date] = mapped_column(Date, index=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    settled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CommunityActivityAwardRecord(Base):
    __tablename__ = "community_activity_awards"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "activity_date", "rank", name="uq_community_activity_award_rank"
        ),
        UniqueConstraint(
            "conversation_id",
            "activity_date",
            "account_id",
            name="uq_community_activity_award_account",
        ),
        Index("ix_community_activity_awards_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(512))
    activity_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int] = mapped_column(Integer)
    message_count: Mapped[int] = mapped_column(Integer)
    reward: Mapped[int] = mapped_column(Integer)
    nickname: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

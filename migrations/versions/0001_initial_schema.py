"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_plugins_name", "plugins", ["name"], unique=True)

    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_skills_name", "skills", ["name"], unique=True)

    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_events_task_id", "agent_events", ["task_id"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"])
    op.create_index("ix_agent_tasks_source", "agent_tasks", ["source"])

    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_memories_scope", "agent_memories", ["scope"])
    op.create_index("ix_agent_memories_kind", "agent_memories", ["kind"])
    op.create_index("ix_agent_memories_source", "agent_memories", ["source"])

    op.create_table(
        "agent_memory_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column("relation", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_memory_links_memory_id", "agent_memory_links", ["memory_id"])
    op.create_index("ix_agent_memory_links_task_id", "agent_memory_links", ["task_id"])
    op.create_index("ix_agent_memory_links_artifact_id", "agent_memory_links", ["artifact_id"])

    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_artifacts_task_id", "agent_artifacts", ["task_id"])
    op.create_index("ix_agent_artifacts_kind", "agent_artifacts", ["kind"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=256), nullable=False),
        sa.Column("sender_id", sa.String(length=256), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_messages_platform", "messages", ["platform"])
    op.create_index("ix_messages_adapter", "messages", ["adapter"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])

    op.create_table(
        "replies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=256), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("quote_message_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_replies_platform", "replies", ["platform"])
    op.create_index("ix_replies_adapter", "replies", ["adapter"])
    op.create_index("ix_replies_conversation_id", "replies", ["conversation_id"])

    op.create_table(
        "message_envelopes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=512), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("headers_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_message_envelopes_trace_id", "message_envelopes", ["trace_id"])
    op.create_index("ix_message_envelopes_dedupe_key", "message_envelopes", ["dedupe_key"], unique=True)
    op.create_index("ix_message_envelopes_message_id", "message_envelopes", ["message_id"])

    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("queue_name", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dead_letters_trace_id", "dead_letters", ["trace_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=512), primary_key=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("raw_id", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversations_platform", "conversations", ["platform"])
    op.create_index("ix_conversations_adapter", "conversations", ["adapter"])
    op.create_index("ix_conversations_scope", "conversations", ["scope"])
    op.create_index("ix_conversations_raw_id", "conversations", ["raw_id"])

    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversation_members_conversation_id", "conversation_members", ["conversation_id"])
    op.create_index("ix_conversation_members_user_id", "conversation_members", ["user_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("sender_id", sa.String(length=256), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])
    op.create_index("ix_conversation_messages_message_id", "conversation_messages", ["message_id"])
    op.create_index("ix_conversation_messages_platform", "conversation_messages", ["platform"])
    op.create_index("ix_conversation_messages_adapter", "conversation_messages", ["adapter"])
    op.create_index("ix_conversation_messages_sender_id", "conversation_messages", ["sender_id"])

    op.create_table(
        "conversation_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("namespace", sa.String(length=256), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversation_states_conversation_id", "conversation_states", ["conversation_id"])
    op.create_index("ix_conversation_states_namespace", "conversation_states", ["namespace"])

    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("from_message_id", sa.String(length=64), nullable=True),
        sa.Column("to_message_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversation_summaries_conversation_id", "conversation_summaries", ["conversation_id"])


def downgrade() -> None:
    for table in [
        "conversation_summaries",
        "conversation_states",
        "conversation_messages",
        "conversation_members",
        "conversations",
        "dead_letters",
        "message_envelopes",
        "replies",
        "messages",
        "agent_artifacts",
        "agent_memory_links",
        "agent_memories",
        "agent_tasks",
        "agent_events",
        "skills",
        "plugins",
    ]:
        op.drop_table(table)

"""add per-group knowledge vault metadata

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_knowledge_bases",
        sa.Column("conversation_id", sa.String(512), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="43200"),
        sa.Column("cursor_record_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("person_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_group_knowledge_bases_enabled", "group_knowledge_bases", ["enabled"])
    op.create_index("ix_group_knowledge_bases_status", "group_knowledge_bases", ["status"])
    op.create_index("ix_group_knowledge_bases_next_run_at", "group_knowledge_bases", ["next_run_at"])

    op.create_table(
        "group_knowledge_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("conversation_id", sa.String(512), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("from_cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("to_cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_change_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_group_knowledge_run_idempotency"),
    )
    op.create_index("ix_group_knowledge_runs_conversation_id", "group_knowledge_runs", ["conversation_id"])
    op.create_index("ix_group_knowledge_runs_status", "group_knowledge_runs", ["status"])
    op.create_index("ix_group_knowledge_runs_conversation_started", "group_knowledge_runs", ["conversation_id", "started_at"])

    op.create_table(
        "group_knowledge_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(512), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(512), nullable=False),
        sa.Column("message_record_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.String(512), nullable=True),
        sa.Column("attachment_id", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(128), nullable=True),
        sa.Column("relative_path", sa.String(1024), nullable=True),
        sa.Column("extract_status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "source_type", "source_key", name="uq_group_knowledge_source_scope"),
    )
    op.create_index("ix_group_knowledge_sources_conversation_id", "group_knowledge_sources", ["conversation_id"])
    op.create_index("ix_group_knowledge_sources_source_type", "group_knowledge_sources", ["source_type"])
    op.create_index("ix_group_knowledge_sources_message_record_id", "group_knowledge_sources", ["message_record_id"])
    op.create_index("ix_group_knowledge_sources_attachment_id", "group_knowledge_sources", ["attachment_id"])
    op.create_index("ix_group_knowledge_sources_conversation_created", "group_knowledge_sources", ["conversation_id", "created_at"])

    op.create_table(
        "group_knowledge_pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(512), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "relative_path", name="uq_group_knowledge_page_path"),
    )
    op.create_index("ix_group_knowledge_pages_conversation_id", "group_knowledge_pages", ["conversation_id"])
    op.create_index("ix_group_knowledge_pages_title", "group_knowledge_pages", ["title"])
    op.create_index("ix_group_knowledge_pages_conversation_updated", "group_knowledge_pages", ["conversation_id", "updated_at"])


def downgrade() -> None:
    op.drop_table("group_knowledge_pages")
    op.drop_table("group_knowledge_sources")
    op.drop_table("group_knowledge_runs")
    op.drop_table("group_knowledge_bases")

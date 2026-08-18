"""add runtime scheduler and reply outbox

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_scheduled_jobs",
        sa.Column("name", sa.String(length=128), primary_key=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_runtime_scheduled_jobs_source",
        "runtime_scheduled_jobs",
        ["source"],
    )
    op.create_index(
        "ix_runtime_scheduled_jobs_next_run_at",
        "runtime_scheduled_jobs",
        ["next_run_at"],
    )
    op.create_index(
        "ix_runtime_scheduled_jobs_lease_expires_at",
        "runtime_scheduled_jobs",
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_runtime_scheduled_jobs_due",
        "runtime_scheduled_jobs",
        ["next_run_at", "lease_expires_at"],
    )

    op.create_table(
        "reply_outbox",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("reply_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("platform_message_id", sa.String(length=512), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "source",
        "platform",
        "adapter",
        "conversation_id",
        "status",
        "available_at",
        "lease_expires_at",
    ):
        op.create_index(f"ix_reply_outbox_{column}", "reply_outbox", [column])
    op.create_index(
        "ix_reply_outbox_idempotency_key",
        "reply_outbox",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_reply_outbox_dispatch",
        "reply_outbox",
        ["status", "available_at", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("reply_outbox")
    op.drop_table("runtime_scheduled_jobs")

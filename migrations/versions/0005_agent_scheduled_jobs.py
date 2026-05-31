"""add agent scheduled jobs

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_scheduled_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("schedule_expr", sa.Text(), nullable=False),
        sa.Column("schedule_display", sa.String(length=256), nullable=False),
        sa.Column("timezone", sa.String(length=128), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=False),
        sa.Column("reply_policy", sa.String(length=64), nullable=False),
        sa.Column("max_runs", sa.Integer(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=64), nullable=True),
        sa.Column("last_task_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_scheduled_jobs_name", "agent_scheduled_jobs", ["name"])
    op.create_index("ix_agent_scheduled_jobs_enabled", "agent_scheduled_jobs", ["enabled"])
    op.create_index("ix_agent_scheduled_jobs_schedule_type", "agent_scheduled_jobs", ["schedule_type"])
    op.create_index("ix_agent_scheduled_jobs_source", "agent_scheduled_jobs", ["source"])
    op.create_index("ix_agent_scheduled_jobs_next_run_at", "agent_scheduled_jobs", ["next_run_at"])
    op.create_index("ix_agent_scheduled_jobs_last_status", "agent_scheduled_jobs", ["last_status"])
    op.create_index("ix_agent_scheduled_jobs_last_task_id", "agent_scheduled_jobs", ["last_task_id"])


def downgrade() -> None:
    op.drop_table("agent_scheduled_jobs")

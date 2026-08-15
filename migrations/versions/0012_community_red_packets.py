"""add community red packets

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_red_packets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("packet_id", sa.String(length=64), nullable=False),
        sa.Column("creator_account_id", sa.Integer(), nullable=True),
        sa.Column("creator_user_id", sa.String(length=256), nullable=False),
        sa.Column("creator_name", sa.String(length=512), nullable=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("packet_count", sa.Integer(), nullable=False),
        sa.Column("remaining_points", sa.Integer(), nullable=False),
        sa.Column("remaining_count", sa.Integer(), nullable=False),
        sa.Column("allocations_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_community_red_packets_packet_id", "community_red_packets", ["packet_id"], unique=True)
    op.create_index("ix_community_red_packets_status", "community_red_packets", ["status"])
    op.create_index("ix_community_red_packet_conversation_status", "community_red_packets", ["conversation_id", "status"])
    op.create_index("ix_community_red_packet_creator_created", "community_red_packets", ["creator_account_id", "created_at"])
    op.create_table(
        "community_red_packet_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("packet_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("packet_id", "account_id", name="uq_community_red_packet_claim"),
    )
    op.create_index("ix_community_red_packet_claim_account_created", "community_red_packet_claims", ["account_id", "created_at"])


def downgrade() -> None:
    op.drop_table("community_red_packet_claims")
    op.drop_table("community_red_packets")

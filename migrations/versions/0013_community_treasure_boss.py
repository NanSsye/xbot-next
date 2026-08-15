"""add community treasure and daily boss games

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_treasure_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("box_number", sa.Integer(), nullable=False),
        sa.Column("reward", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "account_id", "claim_date", name="uq_community_treasure_account_day"
        ),
    )
    op.create_index(
        "ix_community_treasure_claim_date",
        "community_treasure_claims",
        ["claim_date"],
    )
    op.create_table(
        "community_bosses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("boss_date", sa.Date(), nullable=False),
        sa.Column("max_hp", sa.Integer(), nullable=False),
        sa.Column("remaining_hp", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("payout_total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("defeated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "conversation_id", "boss_date", name="uq_community_boss_conversation_day"
        ),
    )
    op.create_index(
        "ix_community_boss_date_status",
        "community_bosses",
        ["boss_date", "status"],
    )
    op.create_table(
        "community_boss_attacks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("boss_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=512), nullable=False),
        sa.Column("attack_index", sa.Integer(), nullable=False),
        sa.Column("damage", sa.Integer(), nullable=False),
        sa.Column("reward", sa.Integer(), nullable=False),
        sa.Column("pool_reward", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_community_boss_attack_event"),
        sa.UniqueConstraint(
            "boss_id",
            "account_id",
            "attack_index",
            name="uq_community_boss_attack_index",
        ),
    )
    op.create_index(
        "ix_community_boss_attack_boss_account",
        "community_boss_attacks",
        ["boss_id", "account_id"],
    )


def downgrade() -> None:
    op.drop_table("community_boss_attacks")
    op.drop_table("community_bosses")
    op.drop_table("community_treasure_claims")

"""add hourly community horse races

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_horse_races",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("race_date", sa.Date(), nullable=False),
        sa.Column("race_hour", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("winning_horse", sa.Integer(), nullable=True),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("winner_count", sa.Integer(), nullable=False),
        sa.Column("payout_total", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "conversation_id", "race_date", "race_hour", name="uq_community_horse_race_round"
        ),
    )
    op.create_index(
        "ix_community_horse_race_status",
        "community_horse_races",
        ["status", "race_date", "race_hour"],
    )
    op.create_table(
        "community_horse_race_bets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("horse_number", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(length=512), nullable=True),
        sa.Column("reward", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "race_id", "account_id", name="uq_community_horse_race_bet_account"
        ),
    )
    op.create_index(
        "ix_community_horse_race_bet_horse",
        "community_horse_race_bets",
        ["race_id", "horse_number"],
    )
    op.create_table(
        "community_high_low_wagers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("wager_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("choice", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("roll", sa.Integer(), nullable=True),
        sa.Column("won", sa.Boolean(), nullable=True),
        sa.Column("payout", sa.Integer(), nullable=False),
        sa.Column("net_points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_community_high_low_wager_id",
        "community_high_low_wagers",
        ["wager_id"],
        unique=True,
    )
    op.create_index(
        "ix_community_high_low_status",
        "community_high_low_wagers",
        ["status"],
    )
    op.create_index(
        "ix_community_high_low_account_created",
        "community_high_low_wagers",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("community_high_low_wagers")
    op.drop_table("community_horse_race_bets")
    op.drop_table("community_horse_races")

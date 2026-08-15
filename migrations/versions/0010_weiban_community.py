"""add Weiban community points and activity tables

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "community_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invite_code", sa.String(length=8), nullable=False),
        sa.Column("points_balance", sa.Integer(), nullable=False),
        sa.Column("frozen", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_community_accounts_invite_code", "community_accounts", ["invite_code"], unique=True)
    op.create_index("ix_community_accounts_frozen", "community_accounts", ["frozen"])
    op.create_table(
        "community_identities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("nickname", sa.String(length=512), nullable=True),
        sa.Column("last_conversation_id", sa.String(length=512), nullable=True),
        sa.Column("bound_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("platform", "adapter", "user_id", name="uq_community_identity_user"),
        sa.UniqueConstraint("account_id", "platform", "adapter", name="uq_community_identity_account_channel"),
    )
    op.create_index("ix_community_identities_account", "community_identities", ["account_id"])
    op.create_table(
        "community_point_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=256), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_community_point_ledger_reason", "community_point_ledger", ["reason"])
    op.create_index("ix_community_point_ledger_reference_id", "community_point_ledger", ["reference_id"], unique=True)
    op.create_index("ix_community_point_ledger_conversation_id", "community_point_ledger", ["conversation_id"])
    op.create_index("ix_community_ledger_account_created", "community_point_ledger", ["account_id", "created_at"])
    op.create_index("ix_community_ledger_effective_date", "community_point_ledger", ["effective_date"])
    op.create_table(
        "community_checkins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("checkin_date", sa.Date(), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("reward", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "checkin_date", name="uq_community_checkin_day"),
    )
    op.create_index("ix_community_checkins_account_date", "community_checkins", ["account_id", "checkin_date"])
    op.create_table(
        "community_game_plays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("game", sa.String(length=32), nullable=False),
        sa.Column("play_date", sa.Date(), nullable=False),
        sa.Column("reference_id", sa.String(length=256), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_community_game_plays_reference_id", "community_game_plays", ["reference_id"], unique=True)
    op.create_index("ix_community_game_account_day", "community_game_plays", ["account_id", "game", "play_date"])
    op.create_table(
        "community_activity_settlements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "activity_date", name="uq_community_activity_settlement"),
    )
    op.create_index("ix_community_activity_settlements_conversation_id", "community_activity_settlements", ["conversation_id"])
    op.create_index("ix_community_activity_settlements_activity_date", "community_activity_settlements", ["activity_date"])
    op.create_table(
        "community_activity_awards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("reward", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "activity_date", "rank", name="uq_community_activity_award_rank"),
        sa.UniqueConstraint("conversation_id", "activity_date", "account_id", name="uq_community_activity_award_account"),
    )
    op.create_index("ix_community_activity_awards_account", "community_activity_awards", ["account_id"])


def downgrade() -> None:
    for table_name in (
        "community_activity_awards",
        "community_activity_settlements",
        "community_game_plays",
        "community_checkins",
        "community_point_ledger",
        "community_identities",
        "community_accounts",
        "community_config",
    ):
        op.drop_table(table_name)

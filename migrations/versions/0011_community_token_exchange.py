"""add community token exchange saga

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_token_exchanges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exchange_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("points_cost", sa.Integer(), nullable=False),
        sa.Column("token_amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_community_token_exchanges_exchange_id",
        "community_token_exchanges",
        ["exchange_id"],
        unique=True,
    )
    op.create_index(
        "ix_community_token_exchanges_idempotency_key",
        "community_token_exchanges",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_community_token_exchanges_status",
        "community_token_exchanges",
        ["status"],
    )
    op.create_index(
        "ix_community_token_exchange_account_created",
        "community_token_exchanges",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_community_token_exchange_account_status",
        "community_token_exchanges",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("community_token_exchanges")

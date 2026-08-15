"""add community character image exchanges

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_character_image_exchanges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exchange_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("points_cost", sa.Integer(), nullable=False),
        sa.Column("image_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_community_character_image_exchanges_exchange_id",
        "community_character_image_exchanges",
        ["exchange_id"],
        unique=True,
    )
    op.create_index(
        "ix_community_character_image_exchanges_idempotency_key",
        "community_character_image_exchanges",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_community_character_image_exchange_account_status",
        "community_character_image_exchanges",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("community_character_image_exchanges")

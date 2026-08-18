"""add per-group agent model override

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("agent_model", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "agent_model")

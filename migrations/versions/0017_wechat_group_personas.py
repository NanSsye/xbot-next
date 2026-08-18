"""add per-group agent personas

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "agent_persona_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("agent_persona_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("agent_persona_updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "agent_persona_updated_at")
    op.drop_column("conversations", "agent_persona_prompt")
    op.drop_column("conversations", "agent_persona_enabled")

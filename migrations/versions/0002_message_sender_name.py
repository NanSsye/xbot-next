"""add sender names to stored messages

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sender_name", sa.String(length=512), nullable=True))
    op.add_column(
        "conversation_messages",
        sa.Column("sender_name", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_messages", "sender_name")
    op.drop_column("messages", "sender_name")

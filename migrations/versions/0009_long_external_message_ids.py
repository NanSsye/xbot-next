"""allow long external platform message ids

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MESSAGE_ID_COLUMNS: tuple[tuple[str, str], ...] = (
    ("messages", "id"),
    ("replies", "quote_message_id"),
    ("message_envelopes", "message_id"),
    ("conversation_messages", "message_id"),
    ("conversation_summaries", "from_message_id"),
    ("conversation_summaries", "to_message_id"),
    ("message_attachments", "message_id"),
)


def _resize_message_ids(*, old_length: int, new_length: int) -> None:
    bind = op.get_bind()
    # SQLite cannot alter VARCHAR length in place.  The ORM schema already
    # treats SQLite text columns as unbounded, so this migration is a safe
    # no-op there; PostgreSQL still receives the explicit widening DDL.
    if bind is not None and bind.dialect.name == "sqlite":
        return
    for table_name, column_name in _MESSAGE_ID_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.String(length=old_length),
            type_=sa.String(length=new_length),
        )


def upgrade() -> None:
    _resize_message_ids(old_length=64, new_length=512)


def downgrade() -> None:
    # PostgreSQL will refuse this downgrade if long platform IDs exist, which is
    # intentionally safer than truncating identifiers and breaking reply links.
    _resize_message_ids(old_length=512, new_length=64)

"""profile batch query indexes

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_conversation_members_conversation_user", "conversation_members", ["conversation_id", "user_id"])
    op.create_index("ix_conversation_messages_conversation_sender_created", "conversation_messages", ["conversation_id", "sender_id", "created_at"])
    op.create_index("ix_message_attachments_conversation_sender_kind", "message_attachments", ["conversation_id", "sender_id", "kind"])
    op.create_index("ix_user_profiles_scope_lookup", "user_profiles", ["platform", "adapter", "conversation_id", "user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_user_profiles_scope_lookup", table_name="user_profiles")
    op.drop_index("ix_message_attachments_conversation_sender_kind", table_name="message_attachments")
    op.drop_index("ix_conversation_messages_conversation_sender_created", table_name="conversation_messages")
    op.drop_index("ix_conversation_members_conversation_user", table_name="conversation_members")

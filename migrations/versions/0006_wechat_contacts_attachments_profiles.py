"""wechat contacts attachments profiles

Revision ID: 0006
Revises: 0002
Create Date: 2026-06-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("nickname", sa.String(length=512), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("platform", "adapter", "user_id", name="uq_contacts_identity"),
    )
    op.create_index("ix_contacts_platform", "contacts", ["platform"])
    op.create_index("ix_contacts_adapter", "contacts", ["adapter"])
    op.create_index("ix_contacts_user_id", "contacts", ["user_id"])

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=False),
        sa.Column("sender_id", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("mime", sa.String(length=128), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=True),
        sa.Column("download_status", sa.String(length=64), nullable=False, server_default="metadata_only"),
        sa.Column("quoted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])
    op.create_index("ix_message_attachments_conversation_id", "message_attachments", ["conversation_id"])
    op.create_index("ix_message_attachments_sender_id", "message_attachments", ["sender_id"])
    op.create_index("ix_message_attachments_kind", "message_attachments", ["kind"])

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("conversation_id", sa.String(length=512), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("stats_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("platform", "adapter", "user_id", "conversation_id", name="uq_user_profiles_scope"),
    )
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])
    op.create_index("ix_user_profiles_conversation_id", "user_profiles", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_table("message_attachments")
    op.drop_table("contacts")


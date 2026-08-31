"""Add index on messages.conversation_id (Part A reliability)

Revision ID: 003_conversation_index
Revises: 002_owner_onboarding
Create Date: 2026-08-26

Part A requires indexes on the hot query columns owner_id, phone_number and
conversation_id. The `messages.conversation_id` column is a foreign key to
`conversations.id` that every inbox/history query filters on, but it was
missing an index. This migration adds it.

This migration is fully additive. Existing data is preserved.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_conversation_index"
down_revision: Union[str, None] = "002_owner_onboarding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Index the messages.conversation_id FK for fast inbox/history lookups.
    op.create_index(
        "ix_messages_conversation_id",
        "messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id", table_name="messages")
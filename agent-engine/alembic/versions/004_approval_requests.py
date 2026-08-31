"""Add approval_requests table + bookings.conversation_id (DB-backed approvals)

Revision ID: 004_approval_requests
Revises: 003_conversation_index
Create Date: 2026-08-31

Adds durable persistence for the human-in-the-loop approval workflow:
  * `approval_requests` table backing ApprovalEngine (survives restarts).
  * `bookings.conversation_id` for idempotent booking (dedup retries).

Both are additive; existing data is preserved.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_approval_requests"
down_revision: Union[str, None] = "003_conversation_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("requester_id", sa.String(128), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("required_approvers", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approver_roles", sa.JSON(), nullable=True),
        sa.Column("approvals", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=True),
        sa.Column("decided_at", sa.String(40), nullable=True),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
    )
    op.create_index("ix_approval_requests_client_id", "approval_requests", ["client_id"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    # Add idempotency column to bookings (additive; safe on existing tables).
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE bookings ADD COLUMN conversation_id VARCHAR(255)")
    op.create_index("ix_bookings_conversation_id", "bookings", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_bookings_conversation_id", table_name="bookings")
    op.drop_index("ix_approval_requests_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_client_id", table_name="approval_requests")
    op.drop_table("approval_requests")
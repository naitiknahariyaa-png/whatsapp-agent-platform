"""contact_lists + contact_list_members + campaign_sends

Revision ID: 005_broadcast_lists
Revises: 004_approval_requests
"""
from alembic import op
import sqlalchemy as sa

revision = "005_broadcast_lists"
down_revision = "004_approval_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_lists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), index=True, nullable=False),
        sa.Column("list_name", sa.String(length=100), index=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "contact_list_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("list_id", sa.Integer(), index=True, nullable=False),
        sa.Column("phone", sa.String(length=20), index=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "campaign_sends",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), index=True, nullable=False),
        sa.Column("phone", sa.String(length=20), index=True, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("campaign_sends")
    op.drop_table("contact_list_members")
    op.drop_table("contact_lists")

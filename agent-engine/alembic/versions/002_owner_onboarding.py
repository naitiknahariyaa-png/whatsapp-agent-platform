"""Owner onboarding tenant tables (Section 2)

Revision ID: 002_owner_onboarding
Revises: 001
Create Date: 2026-08-21

Adds four new tables — `owners`, `catalog_items`, `policies`, `owner_api_keys` —
all carrying `owner_id` for strict tenant isolation. The existing `clients`
table is untouched; an Owner is linked to a Client via `owner.client_id`
once onboarding completes.

This migration is fully additive. Existing data is preserved.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = "002_owner_onboarding"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── owners ─────────────────────────────────────────────────────────
    op.create_table(
        "owners",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("owner_name", sa.String(255), nullable=False),
        sa.Column("owner_phone", sa.String(255), nullable=False),
        sa.Column("owner_phone_hash", sa.String(64), nullable=True),
        sa.Column("owner_email", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("business_category", sa.String(50), nullable=False, server_default="general"),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("business_hours", sa.String(255), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("brand_voice", sa.String(20), nullable=False, server_default="casual"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("escalation_contact", sa.String(255), nullable=True),
        sa.Column("escalation_channel", sa.String(20), nullable=True),
        sa.Column("quiet_hours_start", sa.String(8), nullable=True),
        sa.Column("quiet_hours_end", sa.String(8), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("onboarded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_owners_client_id_clients"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_owners_client_id"), "owners", ["client_id"])
    op.create_index(op.f("ix_owners_owner_phone_hash"), "owners", ["owner_phone_hash"])

    # ── catalog_items ─────────────────────────────────────────────────
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("prep_time_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("prep_time_tier", sa.String(10), nullable=False, server_default="normal"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("popularity_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("margin", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], name="fk_catalog_items_owner_id_owners"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_catalog_items_owner_id"), "catalog_items", ["owner_id"])

    # ── policies ───────────────────────────────────────────────────────
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("refund_policy", sa.Text(), nullable=True),
        sa.Column("cancellation_policy", sa.Text(), nullable=True),
        sa.Column("delivery_radius_km", sa.Float(), nullable=True),
        sa.Column("min_order_amount", sa.Float(), nullable=True),
        sa.Column("discount_rules", sa.JSON(), nullable=True),
        sa.Column("quiet_hours", sa.JSON(), nullable=True),
        sa.Column("relaxation_policy", sa.String(20), nullable=False, server_default="prefer_speed"),
        sa.Column("fastest_guarantee_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("max_autonomous_discount_pct", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("max_autonomous_substitution", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("escalation_triggers", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], name="fk_policies_owner_id_owners"),
        sa.UniqueConstraint("owner_id", name="uq_policies_owner_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_policies_owner_id"), "policies", ["owner_id"])

    # ── owner_api_keys ─────────────────────────────────────────────────
    op.create_table(
        "owner_api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("key_id", sa.String(255), nullable=True),
        sa.Column("encrypted_key", sa.String(2048), nullable=True),
        sa.Column("encrypted_secret", sa.String(2048), nullable=True),
        sa.Column("key_mask", sa.String(40), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], name="fk_owner_api_keys_owner_id_owners"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_owner_api_keys_owner_id"), "owner_api_keys", ["owner_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_owner_api_keys_owner_id"), table_name="owner_api_keys")
    op.drop_table("owner_api_keys")
    op.drop_index(op.f("ix_policies_owner_id"), table_name="policies")
    op.drop_table("policies")
    op.drop_index(op.f("ix_catalog_items_owner_id"), table_name="catalog_items")
    op.drop_table("catalog_items")
    op.drop_index(op.f("ix_owners_owner_phone_hash"), table_name="owners")
    op.drop_index(op.f("ix_owners_client_id"), table_name="owners")
    op.drop_table("owners")

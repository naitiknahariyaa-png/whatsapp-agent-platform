"""Initial schema - auto-generated from current models

Revision ID: 001
Revises: 
Create Date: 2026-08-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("vertical", sa.String(20), nullable=False, server_default="general"),
        sa.Column("whatsapp_number", sa.String(20), nullable=False),
        sa.Column("plan", sa.String(20), nullable=False, server_default="trial"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_clients_whatsapp_number"), "clients", ["whatsapp_number"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_client_id"), "conversations", ["client_id"], unique=False)
    op.create_index(op.f("ix_conversations_phone_number"), "conversations", ["phone_number"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("message_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("media_url", sa.Text(), nullable=True),
        sa.Column("direction", sa.String(10), nullable=False, server_default="incoming"),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_client_id"), "messages", ["client_id"], unique=False)
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_messages_phone_number"), "messages", ["phone_number"], unique=False)
    op.create_index(op.f("ix_messages_created_at"), "messages", ["created_at"], unique=False)

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("tags", sqlite.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("lead_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lead_status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contacts_client_id"), "contacts", ["client_id"], unique=False)
    op.create_index(op.f("ix_contacts_phone_number"), "contacts", ["phone_number"], unique=False)

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("appointment_date", sa.String(20), nullable=True),
        sa.Column("appointment_time", sa.String(20), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("calendar_event_id", sa.String(255), nullable=True),
        sa.Column("sector_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_appointments_client_id"), "appointments", ["client_id"], unique=False)
    op.create_index(op.f("ix_appointments_phone_number"), "appointments", ["phone_number"], unique=False)
    op.create_index(op.f("ix_appointments_created_at"), "appointments", ["created_at"], unique=False)

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("business_id", sa.String(50), nullable=True),
        sa.Column("business_type", sa.String(50), nullable=False, server_default="general"),
        sa.Column("intent", sa.String(50), nullable=False, server_default="booking_request"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("date", sa.String(20), nullable=True),
        sa.Column("time", sa.String(20), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=True),
        sa.Column("service_type", sa.String(255), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_contact", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_extracted", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(50), nullable=False, server_default="web_chat"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bookings_client_id"), "bookings", ["client_id"], unique=False)
    op.create_index(op.f("ix_bookings_created_at"), "bookings", ["created_at"], unique=False)

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("session_state", sa.String(50), nullable=False, server_default="browsing"),
        sa.Column("intent", sa.String(50), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("slot_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("context", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_user_message", sa.Text(), nullable=True),
        sa.Column("last_bot_message", sa.Text(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_human_takeover", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_sessions_client_id"), "conversation_sessions", ["client_id"], unique=False)
    op.create_index(op.f("ix_conversation_sessions_phone_number"), "conversation_sessions", ["phone_number"], unique=False)
    op.create_index(op.f("ix_conversation_sessions_created_at"), "conversation_sessions", ["created_at"], unique=False)

    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column("args", sa.Text(), nullable=True),
        sa.Column("kwargs", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("failed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("dead_letter_jobs")
    op.drop_index(op.f("ix_conversation_sessions_created_at"), table_name="conversation_sessions")
    op.drop_index(op.f("ix_conversation_sessions_phone_number"), table_name="conversation_sessions")
    op.drop_index(op.f("ix_conversation_sessions_client_id"), table_name="conversation_sessions")
    op.drop_table("conversation_sessions")
    op.drop_index(op.f("ix_bookings_created_at"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_client_id"), table_name="bookings")
    op.drop_table("bookings")
    op.drop_index(op.f("ix_appointments_created_at"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_phone_number"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_client_id"), table_name="appointments")
    op.drop_table("appointments")
    op.drop_index(op.f("ix_contacts_phone_number"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_client_id"), table_name="contacts")
    op.drop_table("contacts")
    op.drop_index(op.f("ix_messages_created_at"), table_name="messages")
    op.drop_index(op.f("ix_messages_phone_number"), table_name="messages")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_client_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_phone_number"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_client_id"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_clients_whatsapp_number"), table_name="clients")
    op.drop_table("clients")

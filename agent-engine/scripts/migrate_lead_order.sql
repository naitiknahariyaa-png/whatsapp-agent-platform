-- Migration: Lead Visibility + Order Processing + Custom Agent Training
-- Safe to run multiple times (IF NOT EXISTS everywhere).
-- SQLite-compatible. Run: sqlite3 wap_data.db < scripts/migrate_lead_order.sql

-- 1) Order table (sales converted from leads)
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER NOT NULL REFERENCES clients(id),
    contact_id  INTEGER REFERENCES contacts(id),
    lead_id     INTEGER REFERENCES contacts(id),
    amount      REAL DEFAULT 0.0,
    currency    TEXT DEFAULT 'INR',
    status      TEXT DEFAULT 'pending',
    description TEXT,
    notes       TEXT,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders (client_id);
CREATE INDEX IF NOT EXISTS idx_orders_contact_id ON orders (contact_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);

-- 2) lead_status on contacts (already present in newer schemas; add if missing)
ALTER TABLE contacts ADD COLUMN lead_status TEXT DEFAULT 'new';
ALTER TABLE contacts ADD COLUMN source TEXT;
ALTER TABLE contacts ADD COLUMN custom_fields TEXT DEFAULT '{}';

-- 3) business_profile JSON on clients (custom-agent training data)
ALTER TABLE clients ADD COLUMN business_profile TEXT DEFAULT '{}';

-- 4) helpful indexes for lead visibility queries
CREATE INDEX IF NOT EXISTS idx_contacts_client_id ON contacts (client_id);
CREATE INDEX IF NOT EXISTS idx_contacts_lead_status ON contacts (lead_status);
CREATE INDEX IF NOT EXISTS idx_messages_phone_hash ON messages (phone_hash);

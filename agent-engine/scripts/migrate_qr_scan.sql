-- File: C:/Users/PC/Desktop/whatsapp-agent-platform/agent-engine/scripts/migrate_qr_scan.sql
-- QR-code scan tracking (run: sqlite3 agent.db < migrate_qr_scan.sql)
ALTER TABLE clients ADD COLUMN qr_tracking_enabled BOOLEAN DEFAULT 1;

CREATE TABLE IF NOT EXISTS qr_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    tag VARCHAR(64) NOT NULL,
    source VARCHAR(32),
    ip_hash VARCHAR(64),
    user_agent VARCHAR(255),
    meta JSON,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_qr_scans_client_id ON qr_scans(client_id);
CREATE INDEX IF NOT EXISTS ix_qr_scans_tag ON qr_scans(tag);
CREATE INDEX IF NOT EXISTS ix_qr_scans_created_at ON qr_scans(created_at);
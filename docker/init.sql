-- WhatsApp Agent Platform - Database Schema
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    phone_number VARCHAR(20) NOT NULL,
    contact_name VARCHAR(255),
    session_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',
    unread_count INT DEFAULT 0,
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INT REFERENCES conversations(id),
    phone_number VARCHAR(20) NOT NULL,
    message_type VARCHAR(20) DEFAULT 'text',
    content TEXT,
    media_url TEXT,
    direction VARCHAR(10) DEFAULT 'incoming',
    status VARCHAR(20) DEFAULT 'received',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    phone_number VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    tags TEXT[],
    notes TEXT,
    lead_score INT DEFAULT 0,
    lead_status VARCHAR(20) DEFAULT 'new',
    source VARCHAR(50),
    custom_fields JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS appointments (
    id SERIAL PRIMARY KEY,
    contact_id INT REFERENCES contacts(id),
    phone_number VARCHAR(20) NOT NULL,
    title VARCHAR(255),
    description TEXT,
    appointment_date DATE,
    appointment_time TIME,
    duration_minutes INT DEFAULT 30,
    status VARCHAR(20) DEFAULT 'scheduled',
    calendar_event_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id SERIAL PRIMARY KEY,
    conversation_id INT REFERENCES conversations(id),
    phone_number VARCHAR(20),
    agent_name VARCHAR(50),
    intent VARCHAR(100),
    action_taken TEXT,
    tokens_used INT DEFAULT 0,
    response_time_ms INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS broadcast_campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    message_template TEXT,
    target_filter JSONB,
    status VARCHAR(20) DEFAULT 'draft',
    total_recipients INT DEFAULT 0,
    sent_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    scheduled_at TIMESTAMP,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversations_phone ON conversations(phone_number);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_phone ON messages(phone_number);
CREATE INDEX idx_contacts_phone ON contacts(phone_number);
CREATE INDEX idx_contacts_status ON contacts(lead_status);
CREATE INDEX idx_appointments_date ON appointments(appointment_date);
CREATE INDEX idx_appointments_phone ON appointments(phone_number);
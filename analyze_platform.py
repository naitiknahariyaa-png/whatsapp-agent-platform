"""
WhatsApp Agent Platform - Data Analysis Script
Analyzes messages, contacts, conversations, and platform health.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from pathlib import Path


DB_PATH = Path(__file__).parent / "agent-engine" / "wap_data.db"
REPORT_PATH = Path(__file__).parent / "platform_analysis_report.md"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def analyze_messages(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages")
    total = cur.fetchone()[0]

    cur.execute("SELECT direction, message_type, status, COUNT(*) FROM messages GROUP BY direction, message_type, status")
    rows = cur.fetchall()

    cur.execute("SELECT date(created_at) as day, COUNT(*) FROM messages GROUP BY day ORDER BY day")
    daily = cur.fetchall()

    cur.execute("SELECT phone_number, COUNT(*) as cnt, direction FROM messages GROUP BY phone_number, direction ORDER BY cnt DESC LIMIT 10")
    top_numbers = cur.fetchall()

    cur.execute("SELECT content, created_at, direction FROM messages ORDER BY created_at DESC LIMIT 5")
    recent = cur.fetchall()

    return {
        "total": total,
        "breakdown": [dict(r) for r in rows],
        "daily_volume": [dict(r) for r in daily],
        "top_numbers": [dict(r) for r in top_numbers],
        "recent_messages": [dict(r) for r in recent],
    }


def analyze_contacts(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM contacts")
    total = cur.fetchone()[0]

    cur.execute("SELECT lead_status, COUNT(*) FROM contacts GROUP BY lead_status")
    status_dist = cur.fetchall()

    cur.execute("SELECT source, COUNT(*) FROM contacts GROUP BY source")
    source_dist = cur.fetchall()

    cur.execute("SELECT lead_score, COUNT(*) FROM contacts GROUP BY lead_score ORDER BY lead_score DESC LIMIT 10")
    score_dist = cur.fetchall()

    cur.execute("SELECT name, phone_number, lead_score, lead_status FROM contacts ORDER BY lead_score DESC LIMIT 10")
    top_leads = cur.fetchall()

    return {
        "total": total,
        "status_distribution": [dict(r) for r in status_dist],
        "source_distribution": [dict(r) for r in source_dist],
        "score_distribution": [dict(r) for r in score_dist],
        "top_leads": [dict(r) for r in top_leads],
    }


def analyze_conversations(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM conversations")
    total = cur.fetchone()[0]

    cur.execute("SELECT status, COUNT(*) FROM conversations GROUP BY status")
    status_dist = cur.fetchall()

    cur.execute("SELECT phone_number, last_message_at FROM conversations ORDER BY last_message_at DESC LIMIT 10")
    recent = cur.fetchall()

    return {
        "total": total,
        "status_distribution": [dict(r) for r in status_dist],
        "recent_conversations": [dict(r) for r in recent],
    }


def analyze_sessions(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM conversation_sessions")
    total = cur.fetchone()[0]

    cur.execute("SELECT session_state, COUNT(*) FROM conversation_sessions GROUP BY session_state")
    state_dist = cur.fetchall()

    cur.execute("SELECT is_human_takeover, COUNT(*) FROM conversation_sessions GROUP BY is_human_takeover")
    takeover = cur.fetchall()

    return {
        "total": total,
        "state_distribution": [dict(r) for r in state_dist],
        "human_takeover": [dict(r) for r in takeover],
    }


def analyze_platform_health(conn):
    tables = [
        "clients", "conversations", "messages", "contacts",
        "appointments", "bookings", "conversation_sessions",
        "broadcast_lists", "broadcast_campaigns", "leads"
    ]
    table_counts = {}
    for table in tables:
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            table_counts[table] = cur.fetchone()[0]
        except Exception:
            table_counts[table] = "ERROR"

    return {"table_counts": table_counts}


def generate_report(msgs, contacts, convs, sessions, health):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = []
    lines.append("# WhatsApp Agent Platform - Data Analysis Report")
    lines.append(f"\n**Generated:** {now}")
    lines.append(f"**Database:** `{DB_PATH}`")

    lines.append("\n---\n")
    lines.append("## 1. Executive Summary")

    lines.append(f"- **Total Messages:** {msgs['total']}")
    lines.append(f"- **Total Contacts:** {contacts['total']}")
    lines.append(f"- **Total Conversations:** {convs['total']}")
    lines.append(f"- **Total Sessions:** {sessions['total']}")

    lines.append("\n---\n")
    lines.append("## 2. Message Analysis")

    lines.append(f"### Total Messages: {msgs['total']}")
    if msgs["breakdown"]:
        lines.append("\n| Direction | Type | Status | Count |")
        lines.append("|-----------|------|--------|-------|")
        for row in msgs["breakdown"]:
            lines.append(f"| {row['direction']} | {row['message_type']} | {row['status']} | {row['COUNT(*)']} |")

    if msgs["daily_volume"]:
        lines.append("\n### Daily Message Volume")
        lines.append("\n| Date | Count |")
        lines.append("|------|-------|")
        for row in msgs["daily_volume"]:
            lines.append(f"| {row['day']} | {row['COUNT(*)']} |")

    lines.append("\n### Top Active Numbers")
    if msgs["top_numbers"]:
        lines.append("\n| Phone | Count | Direction |")
        lines.append("|-------|-------|-----------|")
        for row in msgs["top_numbers"]:
            lines.append(f"| {row['phone_number']} | {row['cnt']} | {row['direction']} |")

    lines.append("\n### Recent Messages")
    for row in msgs["recent_messages"]:
        content_preview = (row["content"] or "")[:80].replace("|", "\\|")
        lines.append(f"- **{row['created_at']}** [{row['direction']}] {content_preview}...")

    lines.append("\n---\n")
    lines.append("## 3. Contact & Lead Analysis")

    lines.append(f"### Total Contacts: {contacts['total']}")
    if contacts["status_distribution"]:
        lines.append("\n| Status | Count |")
        lines.append("|--------|-------|")
        for row in contacts["status_distribution"]:
            lines.append(f"| {row['lead_status']} | {row['COUNT(*)']} |")

    if contacts["source_distribution"]:
        lines.append("\n### Contact Sources")
        lines.append("\n| Source | Count |")
        lines.append("|--------|-------|")
        for row in contacts["source_distribution"]:
            lines.append(f"| {row['source'] or 'unknown'} | {row['COUNT(*)']} |")

    if contacts["top_leads"]:
        lines.append("\n### Top Leads")
        lines.append("\n| Name | Phone | Score | Status |")
        lines.append("|------|-------|-------|--------|")
        for row in contacts["top_leads"]:
            lines.append(f"| {row['name'] or 'N/A'} | {row['phone_number']} | {row['lead_score']} | {row['lead_status']} |")

    lines.append("\n---\n")
    lines.append("## 4. Conversation Analysis")

    lines.append(f"### Total Conversations: {convs['total']}")
    if convs["status_distribution"]:
        lines.append("\n| Status | Count |")
        lines.append("|--------|-------|")
        for row in convs["status_distribution"]:
            lines.append(f"| {row['status']} | {row['COUNT(*)']} |")

    lines.append("\n### Recent Conversations")
    for row in convs["recent_conversations"]:
        lines.append(f"- **{row['phone_number']}** last active: {row['last_message_at']}")

    lines.append("\n---\n")
    lines.append("## 5. Session & State Analysis")

    lines.append(f"### Total Sessions: {sessions['total']}")
    if sessions["state_distribution"]:
        lines.append("\n| State | Count |")
        lines.append("|-------|-------|")
        for row in sessions["state_distribution"]:
            lines.append(f"| {row['session_state']} | {row['COUNT(*)']} |")

    lines.append("\n---\n")
    lines.append("## 6. Database Health")

    lines.append("\n| Table | Row Count |")
    lines.append("|-------|-----------|")
    for table, count in health["table_counts"].items():
        lines.append(f"| {table} | {count} |")

    lines.append("\n---\n")
    lines.append("## 7. Recommendations")

    recs = []
    if msgs["total"] == 0:
        recs.append("- No messages recorded yet. Run the bridge and send a test message.")
    if contacts["total"] == 0:
        recs.append("- No contacts in the database. Upload contacts or receive inbound messages.")
    if sessions["total"] == 0:
        recs.append("- No conversation sessions recorded. Ensure the orchestrator is processing messages.")
    if convs["total"] == 0:
        recs.append("- No conversations tracked. Verify `save_message` is being called in the webhook handler.")

    if not recs:
        recs.append("- Platform is collecting data. Monitor growth and lead scores.")

    lines.extend(recs)

    return "\n".join(lines)


def main():
    if not DB_PATH.exists():
        print(f"[!] Database not found at {DB_PATH}")
        return

    conn = get_connection()
    try:
        msgs = analyze_messages(conn)
        contacts = analyze_contacts(conn)
        convs = analyze_conversations(conn)
        sessions = analyze_sessions(conn)
        health = analyze_platform_health(conn)
    finally:
        conn.close()

    report = generate_report(msgs, contacts, convs, sessions, health)

    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[v] Analysis report saved to: {REPORT_PATH}")
    print("\n" + "=" * 60)
    print(report)


if __name__ == "__main__":
    main()

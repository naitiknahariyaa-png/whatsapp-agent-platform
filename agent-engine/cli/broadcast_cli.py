#!/usr/bin/env python3
"""
Broadcast CLI — bulk-import phone numbers and run sequential, anti-ban-paced
WhatsApp campaigns.

Usage:
  python -m cli.broadcast_cli import --file numbers.csv --list-name diwali_2026
  python -m cli.broadcast_cli import --paste --list-name walkin_leads
  python -m cli.broadcast_cli list-show --list-name diwali_2026
  python -m cli.broadcast_cli send --list-name diwali_2026 --message "Diwali sale! 20% off" [--force] [--ignore-quiet-hours]
  python -m cli.broadcast_cli status --campaign-id 12
  python -m cli.broadcast_cli pause|resume|cancel --campaign-id 12

Auth: WAP_TOKEN, or WAP_EMAIL + WAP_PASSWORD (same as cli.py).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import List, Tuple

import httpx

API_BASE = os.getenv("WAP_API_BASE", "http://127.0.0.1:8000")
TIMEOUT = 180


def _token() -> str:
    tok = os.getenv("WAP_TOKEN", "")
    if tok:
        return tok
    email = os.getenv("WAP_EMAIL", "")
    password = os.getenv("WAP_PASSWORD", "")
    if not (email and password):
        try:
            email = input("WAP_EMAIL: ").strip()
            password = input("WAP_PASSWORD: ").strip()
        except EOFError:
            sys.exit("No credentials. Set WAP_TOKEN or WAP_EMAIL + WAP_PASSWORD.")
    r = httpx.post(f"{API_BASE}/auth/login",
                   json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Login failed: {r.status_code} {r.text[:150]}")
    return r.json()["access_token"]


def _call(method: str, path: str, token: str, json_body=None):
    try:
        r = httpx.request(method, f"{API_BASE}{path}",
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"},
                          json=json_body, timeout=TIMEOUT)
    except httpx.ConnectError:
        sys.exit(f"Server not reachable at {API_BASE}. Run: python cli.py start-server")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail") or r.json().get("error") or r.text[:200]
        except Exception:
            detail = r.text[:200]
        sys.exit(f"HTTP {r.status_code}: {detail}")
    try:
        return r.json()
    except Exception:
        return r.text


def _read_entries(args) -> Tuple[List[Tuple[str, str]], str]:
    entries: List[Tuple[str, str]] = []
    source = "txt"
    if getattr(args, "paste", False):
        print("Paste numbers (one per line, optional name after a comma). "
              "Finish with Ctrl+Z then Enter (Windows) / Ctrl+D (Linux):")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 1)
            entries.append((parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""))
        source = "paste"
    else:
        path = args.file
        if not path or not os.path.exists(path):
            sys.exit(f"File not found: {path}")
        source = "csv" if path.lower().endswith(".csv") else "txt"
        if source == "csv":
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if not row or not row[0].strip():
                        continue
                    if row[0].strip().lower() in ("phone", "phone_number", "number"):
                        continue  # header row
                    entries.append((row[0].strip(),
                                    row[1].strip() if len(row) > 1 else ""))
        else:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",", 1)
                    entries.append((parts[0].strip(),
                                    parts[1].strip() if len(parts) > 1 else ""))
    if getattr(args, "source", None):
        source = args.source
    return entries, source


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="broadcast_cli",
                                description="Bulk broadcast CLI (anti-ban paced)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("import", help="Import numbers from file or paste")
    s.add_argument("--file")
    s.add_argument("--paste", action="store_true")
    s.add_argument("--list-name", required=True)
    s.add_argument("--source")

    s = sub.add_parser("list-show", help="Show a list's contents and stats")
    s.add_argument("--list-name", required=True)

    s = sub.add_parser("send", help="Launch a campaign against a list")
    s.add_argument("--list-name", required=True)
    s.add_argument("--message", required=True)
    s.add_argument("--force", action="store_true",
                   help="Required for lists above the confirmation threshold")
    s.add_argument("--ignore-quiet-hours", action="store_true")

    s = sub.add_parser("status", help="Live campaign progress")
    s.add_argument("--campaign-id", type=int, required=True)

    for cmd in ("pause", "resume", "cancel"):
        s = sub.add_parser(cmd)
        s.add_argument("--campaign-id", type=int, required=True)

    args = p.parse_args(argv)
    token = _token()

    if args.command == "import":
        entries, source = _read_entries(args)
        if not entries:
            sys.exit("No numbers found in input.")
        print(f"Read {len(entries)} raw entries; importing...")
        data = _call("POST", "/api/broadcast/import", token, json_body={
            "list_name": args.list_name,
            "numbers": [{"phone": ph, "name": nm} for ph, nm in entries],
            "source": source,
        })
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\nSummary: {data.get('imported')} imported, "
              f"{data.get('invalid')} invalid, "
              f"{data.get('duplicates_in_list')} duplicates skipped, "
              f"{data.get('already_customers')} already customers, "
              f"{len(data.get('opted_out_excluded') or [])} opted-out excluded. "
              f"List total: {data.get('list_total')}")
        return 0

    if args.command == "list-show":
        data = _call("GET", f"/api/broadcast/list/{args.list_name}", token)
        print(f"List '{data['list_name']}' — {data['total']} recipient(s)")
        for m in data.get("members", []):
            print(f"  {m['phone']}  {m.get('name') or '-'}  [{m.get('source')}]")
        return 0

    if args.command == "send":
        data = _call("POST", "/api/broadcast/send", token, json_body={
            "list_name": args.list_name, "message": args.message,
            "force": args.force, "ignore_quiet_hours": args.ignore_quiet_hours,
        })
        if data.get("needs_force"):
            print(data.get("message"))
            print("Re-run with --force to confirm.")
            return 2
        if data.get("error"):
            print(f"ERROR: {data['error']}")
            return 1
        print(f"Campaign {data['campaign_id']} started — {data['total']} recipients.")
        print(f"Progress: python -m cli.broadcast_cli status --campaign-id {data['campaign_id']}")
        return 0

    if args.command == "status":
        d = _call("GET", f"/api/broadcast/status/{args.campaign_id}", token)
        print(f"Campaign: {d.get('list_name')} ({d.get('campaign_id')})")
        print(f"Status: {str(d.get('status')).upper()}")
        print(f"Sent:      {d.get('sent')} / {d.get('total')}")
        print(f"Failed:    {d.get('failed')}")
        print(f"Skipped:   {d.get('skipped')} (opted out)")
        print(f"Replies:   {d.get('replies')} ({d.get('reply_rate_pct')}% reply rate)")
        print(f"Est. time remaining: ~{d.get('est_minutes_remaining')} min")
        return 0

    data = _call("POST", f"/api/broadcast/{args.command}/{args.campaign_id}", token)
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

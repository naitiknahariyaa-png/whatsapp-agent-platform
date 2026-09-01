#!/usr/bin/env python3
"""
WhatsApp Agent Platform — Ops CLI

Usage:
  python cli.py start-server [--port 8000]
  python cli.py generate-report [--client-id 1]
  python cli.py run-reengage
  python cli.py stop-reengage --lead-id 12 [--reason opted_out]
  python cli.py list-alerts
  python cli.py trigger-alerts
  python cli.py approval-request --action refund [--amount 5000] [--payload-file p.json]
  python cli.py approval-pending
  python cli.py approval-decision --id <request-id> --approve|--reject [--comment "..."]
  python cli.py business-setup          # guided form: business details + menu
  python cli.py my-business             # show saved business profile + catalog

Auth: set WAP_TOKEN, or WAP_EMAIL + WAP_PASSWORD (auto-login).
"""
from __future__ import annotations

import argparse
import json
import sys

import cli_commands as cc


def _pp(data) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def _need_token(args) -> str:
    token = cc.get_token(getattr(args, "token", None))
    if not token:
        print("No auth token. Set WAP_TOKEN (or WAP_EMAIL + WAP_PASSWORD), "
              "or pass --token.", file=sys.stderr)
        sys.exit(2)
    return token


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cli.py",
                                description="WhatsApp Agent Platform ops CLI")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start-server", help="Start the backend (uvicorn)")
    s.add_argument("--port", type=int, default=8000)

    s = sub.add_parser("generate-report", help="Generate the weekly CEO report")
    s.add_argument("--client-id", type=int, default=1)
    s.add_argument("--token")

    s = sub.add_parser("run-reengage", help="Run one re-engagement scan now")
    s.add_argument("--token")

    s = sub.add_parser("stop-reengage", help="Stop nudges for a lead")
    s.add_argument("--lead-id", type=int, required=True)
    s.add_argument("--reason", default="converted", choices=["converted", "opted_out"])
    s.add_argument("--token")

    s = sub.add_parser("list-alerts", help="Evaluate and list current alerts")
    s.add_argument("--token")

    s = sub.add_parser("trigger-alerts", help="Run alert checks now and dispatch")
    s.add_argument("--token")

    s = sub.add_parser("approval-request", help="Create a human-approval request")
    s.add_argument("--action", required=True, help="e.g. refund, invoice, bulk_message")
    s.add_argument("--amount", type=float)
    s.add_argument("--conversation-id")
    s.add_argument("--payload-file", help="JSON file with action details")
    s.add_argument("--token")

    s = sub.add_parser("approval-pending", help="List pending approval requests")
    s.add_argument("--token")

    s = sub.add_parser("approval-decision", help="Approve or reject a request")
    s.add_argument("--id", required=True, help="approval request id")
    s.add_argument("--approve", action="store_true")
    s.add_argument("--reject", action="store_true")
    s.add_argument("--comment", default="")
    s.add_argument("--token")

    s = sub.add_parser("business-setup",
                       help="Guided form: enter your business details + menu (powers business-specific AI replies)")
    s.add_argument("--token")

    s = sub.add_parser("my-business", help="Show your saved business profile and catalog")
    s.add_argument("--token")

    s = sub.add_parser("manager-message",
                       help="Compose (and optionally send) a WhatsApp message AS your business manager, using ONLY your business profile facts")
    s.add_argument("--to", required=True, help="customer phone, e.g. 919876543210")
    s.add_argument("--topic", required=True,
                   help="what to write, e.g. 'tell them everything about the hotel and today's menu'")
    s.add_argument("--send", action="store_true",
                   help="actually send via WhatsApp (default: only compose and print)")
    s.add_argument("--token")

    args = p.parse_args(argv)

    if args.command == "start-server":
        ok, msg = cc.cmd_start_server(args.port)
        print(msg)
        return 0 if ok else 1

    token = _need_token(args)

    if args.command == "generate-report":
        ok, data = cc.cmd_generate_report(args.client_id, token)
    elif args.command == "run-reengage":
        ok, data = cc.cmd_run_reengage(token)
    elif args.command == "stop-reengage":
        ok, data = cc.cmd_stop_reengage(args.lead_id, args.reason, token)
    elif args.command == "list-alerts":
        ok, data = cc.cmd_list_alerts(token)
    elif args.command == "trigger-alerts":
        ok, data = cc.cmd_trigger_alerts(token)
    elif args.command == "approval-request":
        ok, data = cc.cmd_approval_request(
            args.action, args.amount,
            cc.load_payload_file(args.payload_file),
            args.conversation_id, token)
    elif args.command == "approval-pending":
        ok, data = cc.cmd_pending_approvals(token)
    elif args.command == "approval-decision":
        if args.approve == args.reject:
            print("Choose exactly one of --approve / --reject.", file=sys.stderr)
            return 2
        ok, data = cc.cmd_approval_decision(args.id, args.approve, args.comment, token)
    elif args.command == "business-setup":
        token = token or cc.get_token(None)  # env-based login if available
        ok, data = cc.business_setup_interactive(token)
        if not ok:
            print(data, file=sys.stderr)
        return 0 if ok else 1

    elif args.command == "my-business":
        ok, data = cc.get_my_business(token)

    elif args.command == "manager-message":
        ok, data = cc.cmd_manager_message(args.to, args.topic, args.send, token)
        if ok and isinstance(data, dict):
            print(f"\n--- Message from {data.get('business', 'your business')} "
                  f"({data.get('status')}) ---")
            print(data.get("message", ""))
            if data.get("send_error"):
                print(f"\n[!] {data['send_error']}", file=sys.stderr)
            return 0

    else:  # pragma: no cover
        p.print_help()
        return 2

    _pp(data)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
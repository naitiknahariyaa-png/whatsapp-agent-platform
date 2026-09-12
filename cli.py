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
  python cli.py toggle-subscription <client_id> on|off   # admin: AI subscription
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
    s.add_argument("--profile", default="",
                   help="Optional path to profile.json (menu/brand_voice/languages/business_hours)")
    s.add_argument("--token")

    s = sub.add_parser("my-business", help="Show your saved business profile and catalog")
    s.add_argument("--token")

    s = sub.add_parser("toggle-subscription",
                       help="Admin: enable/disable a client's AI (subscription switch)")
    s.add_argument("client_id", type=int)
    s.add_argument("state", choices=["on", "off"])
    s.add_argument("--token")

    s = sub.add_parser("persona",
                       help="Preview the AI's 'speak-as-the-business' system prompt built from your profile")
    s.add_argument("--token")

    s = sub.add_parser("manager-message",
                       help="Compose (and optionally send) a WhatsApp message AS your business manager, using ONLY your business profile facts")
    s.add_argument("--to", required=True, help="customer phone, e.g. 919876543210")
    s.add_argument("--topic", required=True,
                   help="what to write, e.g. 'tell them everything about the hotel and today's menu'")
    s.add_argument("--send", action="store_true",
                   help="actually send via WhatsApp (default: only compose and print)")
    s.add_argument("--token")

    # ── Lead & Order CLI ──────────────────────────────────────────────────────
    s = sub.add_parser("list-leads", help="List leads for a shop (optional --status filter)")
    s.add_argument("client_id", type=int)
    s.add_argument("--status", default="", help="new|contacted|qualified|won|lost")
    s.add_argument("--token")

    s = sub.add_parser("view-lead", help="Show full message thread for a lead")
    s.add_argument("client_id", type=int)
    s.add_argument("lead_id", type=int)
    s.add_argument("--token")

    s = sub.add_parser("mark-lead", help="Update lead status")
    s.add_argument("client_id", type=int)
    s.add_argument("lead_id", type=int)
    s.add_argument("--status", required=True, help="new|contacted|qualified|won|lost")
    s.add_argument("--token")

    s = sub.add_parser("create-order", help="Convert a lead into an order/sale")
    s.add_argument("client_id", type=int)
    s.add_argument("lead_id", type=int)
    s.add_argument("--amount", type=float, required=True)
    s.add_argument("--currency", default="INR")
    s.add_argument("--description", default="")
    s.add_argument("--token")

    s = sub.add_parser("list-orders", help="List orders for a shop")
    s.add_argument("client_id", type=int)
    s.add_argument("--status", default="")
    s.add_argument("--token")

    s = sub.add_parser("upload-profile", help="Upload a business profile JSON (onboarding / custom-agent training)")
    s.add_argument("client_id", type=int)
    s.add_argument("path", help="path/to/profile.json")
    s.add_argument("--token")

    s = sub.add_parser("admin-overview", help="Platform-wide stats (admin only)")
    s.add_argument("--token")

    s = sub.add_parser("report-broadcast",
                       help="Generate (and optionally send) outreach messages from a contacts report (XLSX/CSV)")
    s.add_argument("path", help="path to the report file (.xlsx or .csv)")
    s.add_argument("--dry-run", action="store_true", default=True,
                   help="print the messages without sending (default)")
    s.add_argument("--send", action="store_true",
                   help="actually send via WhatsApp (requires connected bridge)")
    s.add_argument("--voice", default="playful",
                   help="brand voice: formal | casual | playful (default: playful)")
    s.add_argument("--client-id", type=int, default=1)
    s.add_argument("--token")

    s = sub.add_parser("creative-broadcast",
                       help="Broadcast-Lead-Creative-AI: A/B template human-like one-by-one sends (Meta Cloud first)")
    s.add_argument("path", help="path to the report file (.xlsx or .csv)")
    s.add_argument("--dry-run", action="store_true", default=True,
                   help="print the plan without sending (default)")
    s.add_argument("--send", action="store_true",
                   help="actually send one-by-one with ~55-65s gaps")
    s.add_argument("--self-test", dest="self_test",
                   help="send one test message to this number first, then stop")
    s.add_argument("--voice", default="casual",
                   help="brand voice: formal | casual | playful")
    s.add_argument("--use-bridge", dest="use_bridge", action="store_true",
                   help="use the WhatsApp bridge instead of Meta Cloud API")
    s.add_argument("--client-id", type=int, default=1)
    s.add_argument("--limit", type=int, default=0,
                   help="only send the first N contacts (0 = all)")
    s.add_argument("--pace", choices=["human", "bot"], default="human",
                   help="human = ~55-65s jittered gap per send (default); "
                        "bot = spec anti_ban 2-7s jitter, max 20/min via limiter")

    # -- Multi-Account Manager ------------------------------------------------
    s = sub.add_parser("accounts-setup",
                       help="Create many business accounts + owners from one profiles JSON (parallel AI per account)")
    s.add_argument("path", help="path to profiles.json (see samples/profiles.sample.json)")

    s = sub.add_parser("accounts-list", help="List all business accounts (tenants)")

    s = sub.add_parser("accounts-run",
                       help="Run ALL accounts in parallel - each AI writes+sends only its own business outreach")
    s.add_argument("--live", action="store_true",
                   help="real sends via Meta Cloud API / bridge (default: simulate in-terminal)")
    s.add_argument("--limit", type=int, default=0,
                   help="first N contacts per account (0 = all)")
    s.add_argument("--ids", default="",
                   help="comma-separated client_ids to run (default: all active)")
    s.add_argument("--fast", action="store_true",
                   help="minimal pacing (simulate/testing only)")

    # -- AI model ----------------------------------------------------------------
    s = sub.add_parser("model",
                       help="Show or change the AI model/provider used by every agent")
    s.add_argument("--set", help="set LLM_MODEL (e.g. llama-3.3-70b-versatile)")
    s.add_argument("--provider", choices=["groq", "ollama", "openai"],
                   help="also set LLM_PROVIDER")
    s.add_argument("--list", action="store_true",
                   help="list providers and popular models")

    # -- Functional registry (every new functional lands here) --------------------
    s = sub.add_parser("functional",
                       help="Run ANY registered platform function from the terminal")
    s.add_argument("name", nargs="?", default="",
                   help="registered functional name (no name = list all)")
    s.add_argument("--args", dest="args_json", default="",
                   help="JSON kwargs for the functional")
    s.add_argument("--args-file", dest="args_file", default="",
                   help="path to a JSON file with kwargs (avoids shell quoting)")

    args = p.parse_args(argv)

    if args.command == "start-server":
        ok, msg = cc.cmd_start_server(args.port)
        print(msg)
        return 0 if ok else 1

    if args.command == "model":
        import sys as _sys
        import os as _os
        if hasattr(_sys.stdout, "reconfigure"):
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.path.insert(0, "agent-engine")
        envp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "agent-engine", ".env")
        if args.set:
            kv = [("LLM_MODEL", args.set)]
            if args.provider:
                kv.append(("LLM_PROVIDER", args.provider))
                if args.provider == "openai":
                    kv.append(("OPENAI_MODEL", args.set))
            lines = []
            if _os.path.exists(envp):
                with open(envp, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            for key, val in kv:
                hit = False
                for i, line in enumerate(lines):
                    if line.strip().startswith(key + "="):
                        lines[i] = key + "=" + val
                        hit = True
                        break
                if not hit:
                    lines.append(key + "=" + val)
            with open(envp, "w", encoding="utf-8") as f:
                f.write(chr(10).join(lines) + chr(10))
            print("Saved to " + envp)
            for key, val in kv:
                print("  " + key + "=" + val)
            return 0
        from config import settings
        print("provider:     " + settings.llm_provider)
        print("model:        " + settings.llm_model)
        print("openai_model:" + settings.openai_model)
        print("ollama_url:   " + settings.ollama_base_url)
        print("per-task overrides (env):")
        for t in ("CONVERSATION", "PLANNING", "GENERATION",
                  "REASONING", "VERIFICATION"):
            print("  " + t + "_MODEL = " + _os.getenv(t + "_MODEL", "(LLM_MODEL)"))
        if args.list:
            print("providers: groq | ollama | openai | mock")
            print("popular groq models:")
            for m in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                      "qwen/qwen3.8-27b", "gemma2-9b-it",
                      "deepseek-r1-distill-llama-70b"):
                print("  " + m)
        return 0

    if args.command == "functional":
        import sys as _sys
        if hasattr(_sys.stdout, "reconfigure"):
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.path.insert(0, "agent-engine")
        from cli_registry import list_functional, run_functional
        if not args.name:
            print("Registered functionals (run: python cli.py functional <name> "
                  "--args JSON)")
            for r in list_functional():
                print("  " + r["name"] + "  -  " + r["help"])
                if r["params"]:
                    print("      params: " + json.dumps(r["params"]))
            return 0
        if args.args_json:
            kwargs = json.loads(args.args_json)
        elif args.args_file:
            with open(args.args_file, "r", encoding="utf-8") as f:
                kwargs = json.load(f)
        else:
            kwargs = {}
        data = run_functional(args.name, kwargs)
        print(json.dumps(data, indent=2, default=str))
        return 0

    if args.command == "accounts-setup":
        import asyncio
        import sys as _sys
        if hasattr(_sys.stdout, "reconfigure"):
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.path.insert(0, "agent-engine")
        from multi_accounts import setup_accounts
        res = asyncio.run(setup_accounts(args.path))
        print(f"Created {len(res['created'])} accounts:")
        for c in res["created"]:
            print(f"  #{c['client_id']} {c['business_name']} "
                  f"({c['vertical']}) {c['whatsapp_number']}")
        if res["skipped"]:
            print(f"Skipped {len(res['skipped'])} (duplicate numbers):")
            for c in res["skipped"]:
                print(f"  #{c['client_id']} {c['business_name']} - {c['reason']}")
        return 0 if res["created"] else 1

    if args.command == "accounts-list":
        import asyncio
        _sys_path_backup = sys.path
        sys.path.insert(0, "agent-engine")
        from multi_accounts import list_accounts
        rows = asyncio.run(list_accounts())
        sys.path = _sys_path_backup
        print(f"{len(rows)} accounts:")
        for a in rows:
            state = "on " if a["is_active"] else "OFF"
            print(f"  #{a['client_id']} [{state}] {a['business_name']} "
                  f"({a['vertical']}, {a['plan']}) {a['whatsapp_number']} "
                  f"- {a['contacts']} contacts")
        return 0

    if args.command == "accounts-run":
        import asyncio
        import sys as _sys
        if hasattr(_sys.stdout, "reconfigure"):
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.path.insert(0, "agent-engine")
        from multi_accounts import run_all
        ids = [int(x) for x in args.ids.split(",") if x.strip()] if args.ids else None
        mode = "live" if args.live else "simulate"
        print(f"Running accounts in PARALLEL ({mode})...")

        async def on_status(cid, biz, i, tot, phone, kind, text):
            print(f"[{biz}] [{i}/{tot}] {phone} -> {kind}")
            print(f"    {text}")

        res = asyncio.run(run_all(mode=mode, client_ids=ids, limit=args.limit,
                                  fast=args.fast, on_status=on_status))
        print("PER-ACCOUNT RESULTS:")
        for r in res.get("results", []):
            print(f"  #{r['client_id']} {r['business_name']}: "
                  f"{r['sent']} sent, {r['failed']} failed, {r['total']} contacts")
        if res.get("error"):
            print("ERROR:", res["error"])
        print("RESULT:", {k: v for k, v in res.items() if k != "results"})
        return 0 if res.get("ok") else 1

    if args.command == "report-broadcast":
        import asyncio
        import sys as _sys
        if hasattr(_sys.stdout, "reconfigure"):
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.path.insert(0, "agent-engine")
        from report_broadcast import load_report, build_all, send_valid
        rows = load_report(args.path)
        if not rows:
            print(f"No usable rows found in {args.path} "
                  "(need 'Business Name' + 'Contact Number' columns)", file=sys.stderr)
            return 1
        msgs = build_all(rows, brand_voice=args.voice)
        valid = [m for m in msgs if m["valid"]]
        print(f"Loaded {len(msgs)} rows: {len(valid)} valid, "
              f"{len(msgs) - len(valid)} skipped (invalid/duplicate)\n")
        for m in msgs:
            status = "OK " if m["valid"] else f"SKIP ({m.get('reason', '?')})"
            print(f"[{status}] {m['phone'] or m['raw_phone']} "
                  f"({m['business_name']}) [{m['chars']} chars]")
            print(f"       {m['text']}\n")
        if args.send:
            if input(f"Send {len(valid)} messages now? Type 'yes' to confirm: "
                     ).strip().lower() != "yes":
                print("Aborted - nothing sent.")
                return 1
            result = asyncio.run(send_valid(valid, client_id=args.client_id))
            print(result)
            return 0 if result.get("ok") else 1
        print("(dry-run: nothing sent. Add --send to deliver.)")
        return 0

    if args.command == "creative-broadcast":
        import asyncio
        import sys as _sys
        if hasattr(_sys.stdout, "reconfigure"):
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.path.insert(0, "agent-engine")
        from report_broadcast import load_report, normalize_phone
        from creative_broadcast import (plan_creative_batch, send_human_like,
                                        MAX_LEN, is_affirmative,
                                        HUMAN_MIN, HUMAN_MAX)

        rows = load_report(args.path)
        if not rows:
            print(f"No usable rows found in {args.path}", file=sys.stderr)
            return 1
        # the loader keyed phones under 'phone'; normalize + map first name
        contacts = []
        for r in rows:
            ph = normalize_phone(r.get("phone", ""))
            if not ph:
                continue
            contacts.append({"first_name": r.get("first_name") or r.get("name") or "",
                             "phone": ph, "tags": {}})
        if args.limit > 0:
            contacts = contacts[:args.limit]
        profile = {"business_name": "Your Business", "vertical": "general",
                   "brand_voice": args.voice,
                   "service_name": "AI-Powered Booking Assistant",
                   "service_one_liner": ("automates WhatsApp conversations and "
                                         "books appointments 24/7"),
                   "key_benefits": ["fill slots 30% faster",
                                    "cut admin time by 2 hrs daily",
                                    "boost revenue by up to 20%"],
                   "cta_text": "Reply YES for a 14-day free trial",
                   "cta_link": ""}

        async def status(i, total, entry, kind):
            if entry.get("action") == "SKIP":
                print(f"[{i}/{total}] {entry.get('phone')}  -> {kind}")
                return
            print(f"[{i}/{total}] {entry['phone']} (T{entry['template_id']}, "
                  f"+{entry['delay_seconds']:.0f}s)  -> {kind}")
            if entry.get("message"): print(f"    {entry['message'][:120]}")
            else: print(f"    [media] {entry['media']['url']} | {entry['media']['caption'][:60]}")

        if args.self_test:
            tpl = {"phone": args.self_test, "first_name": "there",
                   "delay_seconds": 0, "template_id": "A",
                   "message": "Self-test: AI assistant ready. Reply YES to book a demo."}
            print("Sending self-test to", args.self_test)
            async def _st():
                return await send_human_like([tpl], client_id=args.client_id,
                                             use_meta=not args.use_bridge,
                                             on_status=status)
            res = asyncio.run(_st())
            print("SELF-TEST RESULT:", res)
            return 0 if res.get("ok") else 1

        plan = plan_creative_batch(contacts, profile, rotate=True,
                                   client_id=args.client_id)
        gap = "~55-65s human gaps" if args.pace == "human" else "2-7s anti-ban jitter"
        print(f"Planned {len(plan)} messages (A/B rotated, {gap})\n")
        if args.send:
            ans = input(f"Send {len(plan)} one-by-one now? Type 'yes' to confirm: ")
            if ans.strip().lower() != "yes":
                print("Aborted - nothing sent.")
                return 1
            result = asyncio.run(send_human_like(
                plan, client_id=args.client_id, use_meta=not args.use_bridge,
                on_status=status,
                gap_range=(HUMAN_MIN, HUMAN_MAX) if args.pace == "human" else None))
            print("\nRESULT:", result)
            return 0 if result.get("ok") else 1
        async def _dry():
            for i, p in enumerate(plan):
                await status(i+1, len(plan), p, "DRY")
        asyncio.run(_dry())
        print("\n(dry-run: nothing sent. Add --send to deliver one-by-one.)")
        return 0

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
        ok, data = cc.business_setup_interactive(token, profile_path=args.profile)
        if not ok:
            print(data, file=sys.stderr)
        return 0 if ok else 1

    elif args.command == "toggle-subscription":
        ok, data = cc.cmd_toggle_subscription(
            args.client_id, args.state == "on", token)

    elif args.command == "my-business":
        ok, data = cc.get_my_business(token)

    elif args.command == "persona":
        ok, data = cc.cmd_persona(token)
        print(data)
        return 0 if ok else 1

    elif args.command == "manager-message":
        ok, data = cc.cmd_manager_message(args.to, args.topic, args.send, token)
        if ok and isinstance(data, dict):
            print(f"\n--- Message from {data.get('business', 'your business')} "
                  f"({data.get('status')}) ---")
            print(data.get("message", ""))
            if data.get("send_error"):
                print(f"\n[!] {data['send_error']}", file=sys.stderr)
            return 0

    elif args.command == "list-leads":
        ok, data = cc.cmd_list_leads(args.client_id, args.status, token)
    elif args.command == "view-lead":
        ok, data = cc.cmd_view_lead(args.client_id, args.lead_id, token)
    elif args.command == "mark-lead":
        ok, data = cc.cmd_mark_lead(args.client_id, args.lead_id, args.status, token)
    elif args.command == "create-order":
        ok, data = cc.cmd_create_order(
            args.client_id, args.lead_id, args.amount, args.currency, args.description, token)
    elif args.command == "list-orders":
        ok, data = cc.cmd_list_orders(args.client_id, args.status, token)
    elif args.command == "upload-profile":
        ok, data = cc.cmd_upload_profile(args.client_id, args.path, token)
    elif args.command == "admin-overview":
        ok, data = cc.cmd_admin_overview(token)

    else:  # pragma: no cover
        p.print_help()
        return 2

    _pp(data)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
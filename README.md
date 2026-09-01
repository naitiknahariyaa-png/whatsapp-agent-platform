# WhatsApp AI Agent Company — Full Platform

> A multi-tenant, production-grade AI company that runs entirely over WhatsApp.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ANDROID CONTROL CENTER                        │
│                   (Thin client — no AI logic here)                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                     FASTAPI BACKEND (agent-engine)                   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────────┐   │
│  │   Manager   │  │   Workers    │  │   Constraint Engine        │   │
│  │   Agent     │  │  (11 agents) │  │   (Hinglish/multi-lang)    │   │
│  └─────────────┘  └──────────────┘  └───────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              Onboarding Wizard + Encrypted Vault             │    │
│  └─────────────────────────────────────────────────────────────┘    │
└───────────────┬─────────────────────────────┬───────────────────────┘
                │                             │
    ┌───────────▼───────────┐     ┌───────────▼───────────┐
    │   POSTGRES + ALEMBIC  │     │   REDIS + CHROMADB    │
    │   (tenant-scoped DB)  │     │   (cache + vector DB) │
    └───────────────────────┘     └───────────────────────┘
                │
    ┌───────────▼───────────┐
    │  WHATSAPP BRIDGE      │
    │  (Node.js + Puppeteer)│
    │  HMAC-signed webhooks │
    └───────────────────────┘
```

## Build Status by Part

| Part | Component | Status |
|------|-----------|--------|
| **A** | PostgreSQL + Redis + ChromaDB + Prometheus + Grafana | ✅ Docker Compose ready |
| **A** | Alembic migrations (initial + owner onboarding) | ✅ Migrations present |
| **A** | Outbound anti-ban queue (Redis-backed, 5-20s delay) | ✅ `outbound_limiter.py` |
| **A** | HMAC-signed bridge webhooks + timestamp validation | ✅ `security.py` |
| **A** | Secrets manager (Fernet encryption) | ✅ `secrets_manager.py` |
| **A** | ARQ durable task queue | ✅ `task_manager.py` |
| **B** | Owner/Client/CatalogItem/Policy/OwnerApiKey models | ✅ DB + Alembic migration |
| **B** | Onboarding wizard (7-step) | ✅ `services/onboarding.py` |
| **B** | Encrypted API key vault | ✅ `OwnerApiKey` + `secrets.encrypt()` |
| **B** | Test conversation simulator | ✅ `run_test_conversation()` |
| **B** | FastAPI onboarding routes | ✅ 5 routes in `main.py` |
| **C** | BaseAgent (ReAct loop) | ✅ `agents/base.py` |
| **C** | Context Loader (tight context, no bloat) | ✅ `ContextLoader` |
| **C** | Planner (structured JSON output) | ✅ `Planner` with confidence thresholds |
| **C** | Router/Delegator (deterministic, 15s timeout) | ✅ `Router` |
| **C** | Verifier (conditional LLM check) | ✅ `Verifier` |
| **C** | Response Composer (WhatsApp-safe split) | ✅ `ResponseComposer` |
| **C** | Error/fallback chain | ✅ Retry → escalation, never silent drop |
| **D** | Escalation Agent | ✅ `agents/escalation.py` |
| **D** | Support Agent (RAG) | ✅ `agents/support.py` |
| **D** | Sales Agent | ✅ `agents/sales.py` |
| **D** | Scheduling Agent | ✅ `agents/concierge.py` |
| **D** | Billing Agent | ✅ `agents/billing.py` |
| **D** | QA Agent | ✅ `agents/qa_agent.py` |
| **D** | Analytics Agent | ✅ `agents/analytics.py` (reporting.py) |
| **D** | Marketing Agent | ✅ `agents/marketing.py` |
| **D** | Content Agent | ✅ `agents/content.py` |
| **D** | Onboarding Agent | ✅ `agents/onboarding_agent.py` |
| **D** | Retention Agent | ✅ `agents/retention.py` |
| **D** | HR Agent | ✅ `agents/hr.py` |
| **D** | Legal Agent | ✅ `agents/legal.py` |
| **D** | DevOps Agent | ✅ `agents/devops.py` |
| **E** | Language/tone detection (Hinglish) | ✅ `detect_language_and_tone()` |
| **E** | Constraint extraction (LLM + keyword fallback) | ✅ `extract_constraints()` |
| **E** | Catalog filtering + ranking | ✅ `apply_catalog_filters()` + `rank_catalog_items()` |
| **E** | Fallback constraint relaxation | ✅ `find_relaxable_constraint()` |
| **E** | Tone-mirrored response composition | ✅ `compose_reply()` with 3 language templates |
| **E** | Complaint detection → escalation | ✅ `detect_complaint()` |
| **E** | Negotiation bounds checker | ✅ `check_negotiation_bounds()` |
| **E** | 22-example Hinglish eval set | ✅ `test_constraint_extraction_eval.py` |
| **F** | Lead Nurture Loop (4-stage) | ✅ `lead_funnel.py` |
| **F** | Appointment Guard Loop | ✅ `appointment_nurture.py` |
| **F** | Re-engagement Loop (30-day scan) | ✅ `reengagement_loop.py` |
| **F** | Weekly CEO Report + Quality Audit | ✅ `weekly_report.py` |
| **G** | Messaging/anti-ban guards | ✅ `utils/messaging.py` |
| **G** | Reliability wrappers | ✅ `utils/reliability.py` |
| **G** | Memory helpers | ✅ `utils/memory.py` |
| **G** | RAG helpers | ✅ `utils/rag.py` |
| **G** | Security utilities | ✅ `utils/security.py` |
| **G** | Analytics | ✅ `utils/analytics.py` |
| **G** | Integrations (Whisper, Vision, Translate) | ✅ `utils/integrations.py` |
| **H** | Android App (thin client) | ✅ `android-app/` scaffolded |
| **H** | Foreground WebSocket Service | ✅ `WebSocketService.kt` |
| **H** | WorkManager periodic sync | ✅ `SyncWorker.kt` |
| **H** | REST API layer | ✅ `AgentApiService.kt` |
| **H** | Repository + encrypted TokenManager | ✅ `AgentRepository.kt` |
| **H** | Dashboard + Live Chat + Leads screens | ✅ Layout XMLs |
| **I** | Docker Compose (full stack) | ✅ `docker-compose.yml` |
| **I** | Staging environment | ✅ `backend_staging` + `bridge_staging` |
| **I** | Observability (Prometheus + Grafana + Alertmanager) | ✅ In Compose |
| **I** | Structured logging with trace_id | ✅ `logging_setup.py` |

## Quick Start

```bash
# 1. Clone and enter
git clone <repo-url>
cd whatsapp-agent-platform

# 2. Start infrastructure
docker-compose up -d postgres redis chromadb

# 3. Install Python deps
cd agent-engine
pip install -r requirements.txt

# 4. Run migrations
alembic upgrade head

# 5. Start backend
uvicorn main:app --reload --port 8000

# 6. Start WhatsApp bridge (in another terminal)
cd whatsapp-bridge
npm install
npm start

# 7. (Optional) Start Android app
cd android-app
./gradlew assembleDebug
```

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://wap_user:wap_pass@localhost:5432/whatsapp_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM
GROQ_API_KEY=gsk_...
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile

# Security
JWT_SECRET_KEY=your-secret-key-here
WA_BRIDGE_SECRET=wap_bridge_secret_2026

# WhatsApp
META_ACCESS_TOKEN=...
META_PHONE_NUMBER_ID=...
META_VERIFY_TOKEN=...

# Payments
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
```

## Key Design Decisions

1. **Multi-tenancy**: Every table, cache key, and vector embedding carries `owner_id`. Cross-tenant isolation is enforced at the query layer and verified by automated tests.

2. **No silent failures**: Every failure path in the Manager Agent resolves to retry-with-feedback or human escalation. Never a raw error to the customer.

3. **Anti-ban by default**: All outbound messaging goes through a Redis-backed queue with randomized 5-20s delays, daily caps, and per-recipient cooldowns.

4. **Constraint-aware replies**: The engine extracts budget, urgency, dietary flags, and time constraints from messy mixed-language input, then filters the owner's actual catalog — never a full menu dump.

5. **Small functions, reused everywhere**: 55+ granular utilities (`utils/`) for messaging, security, analytics, scheduling, payments — built once, called everywhere.

## Testing

```bash
# Run all tests
cd agent-engine
pytest tests/

# Run tenant isolation tests specifically
pytest tests/test_tenant_isolation.py -v

# Run constraint extraction eval set
pytest tests/test_constraint_extraction_eval.py -v
```

## Bulk Broadcast CLI

Bulk-import phone numbers and run sequential, anti-ban-paced campaigns.
Every send goes through the **same outbound pipeline** (opt-out checks, daily
caps, per-recipient cooldown, randomized 5–20s delay) — there is no second sender.

```powershell
# from agent-engine/
python -m cli.broadcast_cli import --file numbers.csv --list-name diwali_2026
python -m cli.broadcast_cli import --paste --list-name walkin_leads
python -m cli.broadcast_cli list-show --list-name diwali_2026
python -m cli.broadcast_cli send --list-name diwali_2026 --message "Diwali sale! 20% off" --force
python -m cli.broadcast_cli status --campaign-id 12
python -m cli.broadcast_cli pause|resume|cancel --campaign-id 12
```

CSV format: first column = phone, optional second column = name (used for
`{name}` personalization). Imports report invalid numbers (written to
`invalid_numbers.txt`), duplicates, opted-out exclusions, and numbers that are
already customers. Lists over 500 recipients require `--force`; quiet hours
(`BROADCAST_QUIET_START`/`BROADCAST_QUIET_END`) are respected unless
`--ignore-quiet-hours`. Campaigns survive crashes — `resume` continues from
the first pending recipient and never double-sends.


## License

Proprietary — WhatsApp Agent Platform

## Ops CLI

```bash
# Auth (one of):
export WAP_TOKEN=<jwt>            # or WAP_EMAIL + WAP_PASSWORD for auto-login

python cli.py start-server                          # boot the backend
python cli.py generate-report --client-id 1         # weekly CEO report
python cli.py run-reengage                          # one re-engagement scan
python cli.py stop-reengage --lead-id 12            # stop nudges for a lead
python cli.py list-alerts                           # evaluate alerts
python cli.py trigger-alerts                        # run + dispatch alerts
python cli.py approval-request --action refund --amount 5000
python cli.py approval-pending
python cli.py approval-decision --id <request-id> --approve
```

All commands call the same FastAPI endpoints the UI uses (HTTP only, no direct DB access).
The interactive `wap-cli.py` exposes the same operations under menu **A. Ops & Jobs**.

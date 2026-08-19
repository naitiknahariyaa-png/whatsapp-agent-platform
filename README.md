# WhatsApp Agent Platform — Terminal Edition

> **No website. Pure terminal. Full power.**

A fully functional WhatsApp AI agent platform that runs entirely in your terminal. Manage leads, appointments, drip campaigns, and WhatsApp conversations — all from a beautiful command-line interface.

---

## What This Is

This is a **local, terminal-only** version of the WhatsApp Agent Platform. The web frontend has been removed. Everything runs via:

- **`wap-cli.py`** — Terminal control panel (the only UI you need)
- **Backend API** — FastAPI server running in the background
- **WhatsApp Bridge** — Node.js process for WhatsApp Web connectivity

---

## Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Python | 3.10+ | Backend API + CLI |
| Node.js | 20.x+ | WhatsApp Web bridge |
| Chrome/Edge | Any | WhatsApp Web automation |
| Groq API Key | Free tier ok | AI responses (or use Ollama locally) |

---

## Quick Start (Windows)

### 1. Install Python Dependencies

```powershell
cd agent-engine
pip install -r requirements.txt
```

### 2. Install Bridge Dependencies

```powershell
cd whatsapp-bridge
npm install
cd ..
```

### 3. Configure Environment

```powershell
cd agent-engine
copy .env.example .env
notepad .env
```

**Required fields in `.env`:**
- `GROQ_API_KEY` — Get free key at https://console.groq.com
- `WA_BRIDGE_SECRET` — Keep default or set your own
- `TELEGRAM_BOT_TOKEN` — Optional, from @BotFather

### 4. Launch Terminal App

```powershell
python wap-cli.py
```

Or double-click `start-terminal.bat`.

---

## Terminal Menu Guide

When you run `wap-cli.py`, you get this menu:

```
1. Dashboard          — System overview, stats, connection status
2. WhatsApp Bridge    — Start/stop bridge, scan QR, send messages
3. Chat Simulator     — Test AI conversations locally in terminal
4. Lead CRM           — Create leads, update status, view pipeline
5. Appointments       — Book appointments, view schedule
6. Drip Campaigns     — Create campaigns, enroll contacts
7. LLM Settings       — Check AI provider status
8. Send Message       — Send WhatsApp message to any number
9. Diagnostics        — System health check
0. Exit
```

---

## How Each Feature Works

### Dashboard
Shows real-time status of:
- Backend API server
- WhatsApp bridge connection
- LLM provider (Groq / Ollama / Mock)
- Database stats (leads, appointments, campaigns)

### WhatsApp Bridge
The bridge connects to WhatsApp Web via Chrome. Steps:
1. Select **"Start Bridge"**
2. A QR code appears in terminal — scan with WhatsApp app
3. Once connected, you can send/receive messages

**Note:** Keep the terminal open while the bridge is running.

### Chat Simulator
Test your AI assistant without sending real WhatsApp messages:
- Enter a customer phone number
- Type messages and see AI responses in real-time
- The AI uses your configured LLM (Groq by default)

### Lead CRM
Manage your sales pipeline:
- **Create Lead**: Add phone, name, source
- **Update Status**: Move leads through new → qualified → contacted → converted/lost
- **View Detail**: See full lead profile and score

Lead scoring is automatic based on:
- Name provided: +20 points
- Location provided: +20 points
- Budget provided: +30 points
- Requirement provided: +30 points

### Appointments
Schedule and manage appointments:
- Create appointments with date/time
- The system automatically sends reminders 1 hour before
- View all appointments or filter by date

### Drip Campaigns
Automated message sequences:
- **Create Campaign**: Name and description
- **Enroll Contact**: Add a phone/contact to a campaign
- **View Stats**: See enrollment counts

Campaigns run automatically in the background.

### LLM Settings
Shows which AI provider is active:
- **Groq** (cloud, fast) — default
- **Ollama** (local, private) — requires `ollama serve`
- **OpenAI** (optional fallback)
- **MockLLM** (last resort, keyword-based)

### Send Message
Send a WhatsApp message directly from terminal:
- Enter recipient phone (with country code, e.g., `919876543210`)
- Type your message
- Sent via the WhatsApp bridge

---

## Project Structure

```
whatsapp-agent-platform/
├── agent-engine/          # Python backend (FastAPI + AI + DB)
│   ├── main.py            # API server (terminal mode supported)
│   ├── orchestrator.py    # AI message processing
│   ├── lead_gen.py        # Lead CRM models & logic
│   ├── db.py              # SQLAlchemy database models
│   ├── llm_setup.py       # Multi-provider LLM setup
│   ├── scheduler.py       # Background reminders + campaigns
│   ├── whatsapp_connector.py  # Bridge lifecycle
│   └── .env               # Your API keys (gitignored)
├── whatsapp-bridge/       # Node.js WhatsApp Web bridge
│   ├── bridge.js          # Main bridge server
│   ├── package.json       # Dependencies
│   └── .wwebjs_auth/      # WhatsApp session (gitignored)
├── services/              # Business logic modules
│   ├── drip_campaigns.py  # Campaign engine
│   ├── lead_scoring.py    # Lead scoring algorithm
│   └── ...
├── wap-cli.py             # ★ TERMINAL CONTROL PANEL
├── run-backend.py         # Backend launcher (no frontend)
└── start-terminal.bat     # Windows launcher
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | (empty) | Groq LLM API key |
| `LLM_PROVIDER` | `groq` | AI provider: groq/ollama/openai/mock |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `DATABASE_URL` | `sqlite+aiosqlite:///./wap_data.db` | Database |
| `WHATSAPP_BRIDGE_URL` | `http://localhost:3001` | Bridge URL |
| `PORT` | `8000` | Backend API port |
| `BRIDGE_HTTP_PORT` | `3001` | Bridge HTTP port |
| `WAP_TERMINAL_MODE` | `1` | Disable frontend (set by run-backend.py) |

---

## Troubleshooting

### Backend won't start
- Check if port 8000 is already in use: `netstat -ano | findstr :8000`
- Make sure Python dependencies are installed: `pip install -r agent-engine/requirements.txt`

### Bridge won't start
- Make sure Node.js 20+ is installed: `node --version`
- Install deps: `cd whatsapp-bridge && npm install`
- Make sure Chrome or Edge is installed
- Check bridge logs in terminal output

### "No such table: leads"
- Restart the backend — it creates tables on startup
- Or manually run: `python -c "import asyncio; from db import init_db; asyncio.run(init_db())"`

### LLM returns mock responses
- Check `GROQ_API_KEY` in `.env`
- Verify at: `http://localhost:8000/api/llm/status`
- Or switch to Ollama: set `LLM_PROVIDER=ollama` and run `ollama serve`

### QR code doesn't appear
- Make sure bridge is started: look for `[Bridge] Connected` or `[Bridge] Authenticated` in output
- Try refreshing QR from Bridge menu
- Check that WhatsApp Web is not already logged in elsewhere

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   TERMINAL (wap-cli.py)                  │
│  Dashboard | Bridge | Chat | Leads | Appts | Campaigns   │
└───────────────────────┬─────────────────────────────────┘
                        │ imports / HTTP
                        ▼
┌─────────────────────────────────────────────────────────┐
│              BACKEND API (FastAPI :8000)                 │
│  Routes: /api/message, /api/crm, /api/appointments...   │
│  Orchestrator → LLM → DB → Bridge forwarder             │
└───────────────────────┬─────────────────────────────────┘
                        │ webhook
                        ▼
┌─────────────────────────────────────────────────────────┐
│         WHATSAPP BRIDGE (Node.js :3001)                  │
│  whatsapp-web.js → Chrome → WhatsApp Web                 │
│  QR / Status / Send / Receive                            │
└─────────────────────────────────────────────────────────┘
```

---

## Security Notes

- `.env` contains API keys — never commit it
- `.wwebjs_auth/` contains WhatsApp session — never commit it
- JWT tokens expire after 24 hours
- Backend binds to `127.0.0.1` in terminal mode (not exposed externally)

---

## What's Alive vs What's Not

| Feature | Status |
|---------|--------|
| WhatsApp Bridge | ✅ Working (QR scan required) |
| AI Chat (Groq) | ✅ Working (key pre-configured) |
| AI Chat (Ollama) | ✅ Working (if Ollama running) |
| Lead CRM | ✅ Working |
| Appointments | ✅ Working |
| Drip Campaigns | ✅ Working |
| Telegram Bridge | ✅ Configured (token in .env) |
| Payments (Razorpay) | ⚠️ Configured but keys are placeholders |
| Frontend | ❌ Disabled (terminal only) |
| ChromaDB / Vector Store | ⚠️ Code exists, not wired in CLI |

---

## Next Steps

1. **Scan WhatsApp QR** — Start bridge and connect your phone
2. **Test AI Chat** — Use Chat Simulator to verify responses
3. **Create First Lead** — Add a test lead in Lead CRM
4. **Book Appointment** — Schedule a test appointment
5. **Start Campaign** — Create a drip campaign for onboarding

---

*Built with FastAPI, SQLAlchemy, whatsapp-web.js, and Groq LLM.*

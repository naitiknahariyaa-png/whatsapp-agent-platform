# 🚀 Deployment Guide — WhatsApp Agent Platform

## Quick Deploy (Pick One)

### Option A: Render (Recommended — Free Tier Available)

1. **Push to GitHub:**
   ```bash
   cd C:\Users\PC\Desktop\whatsapp-agent-platform
   git add .
   git commit -m "Production-ready: security, Figma, Telegram, tests"
   ```
   - Create a repo on [github.com](https://github.com/new)
   - Push: `git remote add origin https://github.com/YOUR_USERNAME/whatsapp-agent-platform.git && git push -u origin main`

2. **Deploy on Render:**
   - Go to [render.com](https://render.com) → New → Web Service
   - Connect your GitHub repo
   - Render auto-detects `render.yaml`
   - Add environment variables (see below)
   - Deploy!

3. **Your site will be live at:** `https://whatsapp-agent-platform.onrender.com`

---

### Option B: Railway

1. **Push to GitHub** (same as above)

2. **Deploy on Railway:**
   - Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
   - Railway auto-detects `railway.json`
   - Add environment variables
   - Deploy!

3. **Your site will be live at:** `https://whatsapp-agent-platform.up.railway.app`

---

### Option C: Docker (Any Cloud)

```bash
# Build
docker build -t whatsapp-agent-platform .

# Run
docker run -p 8000:8000 --env-file agent-engine/.env whatsapp-agent-platform

# Or with docker-compose
docker-compose -f docker/docker-compose.yml up -d
```

---

## Required Environment Variables

Set these in your hosting dashboard (Render/Railway/Docker):

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ Yes | Get from [console.groq.com](https://console.groq.com) |
| `JWT_SECRET_KEY` | ✅ Yes | Generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DATABASE_URL` | ✅ Yes | Use SQLite for free: `sqlite+aiosqlite:///./wap.db` |
| `LLM_MODEL` | Optional | Default: `llama-3.3-70b-versatile` |
| `LLM_PROVIDER` | Optional | Default: `groq` |
| `TELEGRAM_BOT_TOKEN` | Optional | From @BotFather on Telegram |
| `FIGMA_API_TOKEN` | Optional | From Figma account settings |
| `FIGMA_FILE_KEY` | Optional | Your Figma file key |
| `RAZORPAY_KEY_ID` | Optional | From [razorpay dashboard](https://dashboard.razorpay.com) |
| `RAZORPAY_KEY_SECRET` | Optional | From Razorpay dashboard |
| `WA_BRIDGE_SECRET` | Optional | HMAC secret for webhook signing |
| `PORT` | Optional | Default: `8000` |

---

## URLs After Deployment

| Page | URL |
|------|-----|
| **Landing Page** | `https://YOUR_DOMAIN/` |
| **Dashboard** | `https://YOUR_DOMAIN/frontend/dashboard.html` |
| **Storefront** | `https://YOUR_DOMAIN/frontend/storefront.html` |
| **Onboarding** | `https://YOUR_DOMAIN/frontend/onboarding.html` |
| **API Health** | `https://YOUR_DOMAIN/health` |
| **API Docs** | `https://YOUR_DOMAIN/docs` |
| **Themes** | `https://YOUR_DOMAIN/api/themes` |
| **Business Types** | `https://YOUR_DOMAIN/api/business/types` |

---

## Post-Deployment Checklist

- [ ] Visit `https://YOUR_DOMAIN/health` → should return `{"status":"ok"}`
- [ ] Visit `https://YOUR_DOMAIN/` → landing page loads
- [ ] Visit `https://YOUR_DOMAIN/frontend/dashboard.html` → dashboard loads
- [ ] Register a user at `/auth/register`
- [ ] Login and create a business profile
- [ ] Test the AI agent via `/api/message`
- [ ] Set up WhatsApp bridge (separate process, needs a server with Chrome)

---

## Notes

- **WhatsApp Bridge** (`whatsapp-bridge/bridge.js`) requires Chrome/Puppeteer and cannot run on free hosting tiers. Run it on a VPS or your local machine.
- **SQLite** works for development/small deployments. For production with many users, use PostgreSQL.
- **Redis** is optional — the app falls back to in-memory state machine if Redis is unavailable.
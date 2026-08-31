# ──────────────────────────────────────────────────────────────────────
# Staging Environment Setup Guide
# ──────────────────────────────────────────────────────────────────────

## What is Staging?
A complete, isolated copy of production for testing changes before they
touch real leads. It has:
- Its own PostgreSQL database (whatsapp_agent_staging)
- Its own Redis DB (redis://redis:6379/1)
- Its own WhatsApp Bridge with a SEPARATE WhatsApp number
- Its own backend API on port 8001 (vs prod 8000)
- Its own bridge on port 3003 (vs prod 3001)

## Quick Start
```bash
# 1. Copy and configure
cp .env.staging .env.staging.local
# Edit .env.staging.local with your staging WhatsApp number and keys

# 2. Start staging stack
docker-compose --profile staging up -d

# 3. Verify
curl http://localhost:8001/health
curl http://localhost:3003/health

# 4. Scan QR on bridge_staging (port 3003)
# Open http://localhost:3003/qr in browser
```

## Separate WhatsApp Number
**Critical:** You MUST use a different WhatsApp number for staging.
- Get a second SIM or use WhatsApp Business API test number
- Scan QR on staging bridge (port 3003), NOT production bridge
- This prevents test messages from reaching real customers

## Database Isolation
Staging uses `postgres_staging` container on port 5433 with database
`whatsapp_agent_staging`. No data is shared with production.

## Running Tests Against Staging
```bash
# Run integration tests against staging
ENVIRONMENT=staging pytest tests/integration/ -v

# Run agent evaluation harness against staging
python -m evaluation.run_harness --env staging
```

## Promoting Staging → Production
```bash
# 1. Run full test suite on staging
docker-compose --profile staging run --rm test-runner

# 2. If all pass, promote via CI/CD
# (GitHub Actions: "promote-staging-to-production" workflow)

# 3. Blue-green deploy to production
docker-compose up -d --no-deps backend
```

## Cost Optimization in Staging
- Uses `llama-3.1-8b-instant` for ALL tasks (cheapest)
- Aggressive rate limits (100 msgs/day vs 1000 prod)
- Longer cooldowns (10 min vs 5 min)
- Mock external APIs optional

## Data Seeding for Staging
```bash
# Seed with synthetic test data
docker-compose --profile staging run --rm backend_staging \
    python -m scripts.seed_staging_data
```
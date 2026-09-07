# Ops Notes — Postgres, Docker, Background Worker

## 1. Migrating from SQLite to PostgreSQL

1. Add the driver: `pip install asyncpg` (SQLAlchemy async URL format below).
2. Change the URL in `agent-engine/.env`:

   ```
   DATABASE_URL=postgresql+asyncpg://wap_user:wap_pass@localhost:5432/wap
   ```

   (`db.py` already reads `DATABASE_URL`; no code change needed.)
3. Create the DB and tables:
   ```sql
   CREATE DATABASE wap;
   CREATE USER wap_user WITH PASSWORD 'wap_pass';
   GRANT ALL PRIVILEGES ON DATABASE wap TO wap_user;
   ```
   ```bash
   cd agent-engine && python -c "import db, asyncio; asyncio.run(db.init_db())"
   ```
4. Migrate existing data (small datasets — one-off script):
   ```bash
   python - <<'EOF'
   import sqlite3, json, asyncpg, os, datetime
   src = sqlite3.connect("agent-engine/agent.db"); src.row_factory = sqlite3.Row
   async def main():
       conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg",""))
       for table in ("clients", "contacts", "messages", "orders"):
           rows = [dict(r) for r in src.execute(f"SELECT * FROM {table}")]
           if not rows: continue
           cols = list(rows[0].keys())
           for r in rows:
              vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in r.values()]
              try:
                 await conn.execute(
                   f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(f'${i+1}' for i in range(len(vals)))})",
                   *vals)
              except Exception as e:
                 print(table, e)
   asyncio.run(main())
   EOF
   ```
5. The raw-SQL migration `scripts/migrate_lead_order.sql` is SQLite-flavoured
   (`ALTER TABLE ... ADD COLUMN` works on Postgres too, but there is no
   `STORAGE` clause) — strip the SQLite-specific bits for Postgres. For
   versioned migrations going forward use Alembic
   (`alembic init migrations`, autogenerate against `db.Base`).

## 2. Dockerizing the stack

Three services: API, WhatsApp bridge, Postgres.

```yaml
# File: docker-compose.yml (repo root)
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: wap
      POSTGRES_USER: wap_user
      POSTGRES_PASSWORD: wap_pass
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wap_user"]
      interval: 5s

  api:
    build: ./agent-engine
    env_file: agent-engine/.env
    environment:
      DATABASE_URL: postgresql+asyncpg://wap_user:wap_pass@db:5432/wap
    ports: ["8000:8000"]
    depends_on:
      db: {condition: service_healthy}

  bridge:
    build: ./whatsapp-bridge
    environment:
      AGENT_ENGINE_URL: http://api:8000
    ports: ["3001:3001"]
    volumes: [wadata:/app/.wwebjs_auth]   # persist WhatsApp session
    depends_on: [api]

volumes: {pgdata: {}, wadata: {}}
```

`agent-engine/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`whatsapp-bridge/Dockerfile`:
```dockerfile
FROM node:20-slim
# chromium deps for whatsapp-web.js / puppeteer
RUN apt-get update && apt-get install -y chromium && rm -rf /var/lib/apt/lists/*
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
CMD ["node", "bridge.js"]
```

Notes: mount `wadata` or you will re-scan the QR on every restart. Never
expose Postgres ports publicly; keep `API_TOKEN`/secrets in the env file only.

## 3. Background worker for reports

The heavy periodic jobs (weekly CEO report, re-engagement nudges, alert
checks — all already exposed as CLI commands) should run out-of-process so a
crash never takes down the API.

Simplest reliable option: **cron-style scheduler container** reusing the CLI:

```yaml
# add to docker-compose.yml
  worker:
    image: python:3.12-slim
    working_dir: /app
    volumes: ["./:/app"]
    env_file: agent-engine/.env
    environment:
      DATABASE_URL: postgresql+asyncpg://wap_user:wap_pass@db:5432/wap
      WAP_EMAIL: system@platform.local
      WAP_PASSWORD: ${WAP_SYSTEM_PASSWORD}
    depends_on: [api]
    command: >
      sh -c "while true; do
        python cli.py generate-report --client-id all;
        python cli.py run-reengage || true;
        python cli.py trigger-alerts || true;
        sleep 3600;
      done"
```

For heavier/queued work (per-message fan-out, retries) prefer **Celery +
Redis** (`celery -A tasks worker --beat`), or a managed scheduler on Render /
Railway / Cloud Run Jobs — the CLI commands already make each job an atomic,
auth'd HTTP entry point, so any scheduler works without code changes.

# Project Completion Goal

**Objective**: Deliver a fully‑functional local development platform that exposes all business‑logic via a FastAPI server, provides a lightweight UI (served on `http://localhost:8000`), includes a command‑line interface for ops, and ships with Docker support for easy startup.

---

## 1. Missing API Endpoints (FastAPI routers)

| Router file | Endpoints to add | Why needed |
|---|---|---|
| `onboarding.py` | `GET /owners/{owner_id}/state` (lightweight wizard state) | UI can load owner basics without pulling the whole catalog. |
| `alerts.py` | `GET /alerts` – list current alerts<br>`POST /alerts/trigger` – manual trigger for a named check | Allows UI & CLI to display health info and test alerts. |
| `weekly_report.py` | `POST /weekly_report/generate` – returns generated report JSON | UI button to view last week’s metrics; CLI command to dump report. |
| `reengagement_loop.py` | `POST /reengagement/run` – run once now<br>`POST /reengagement/stop` – cancel pending nudges for a lead ID | Enables manual control and UI monitoring. |
| `approval_gates.py` | `POST /approval/request` – create request (persisted) <br>`POST /approval/decision` – approve/reject <br>`GET /approval/pending` – list pending requests | Human‑in‑the‑loop workflow must be reachable via HTTP. |
| **Transaction safety** | Wrap catalog inserts (`add_catalog_item`, `add_catalog_items_bulk`) in `async with db.begin():` | Guarantees atomicity for bulk ops. |
| **Idempotent booking** | In `chat_assistant.py`, before `create_booking` check for existing booking with same `conversation_id` (unique constraint) | Prevent duplicate rows on retries. |
| **Error handling** | Return proper HTTP 4xx/5xx when `business_manager.load_profile` fails; surface message to user. |
| **LLM token truncation** | Add a helper that trims the chat history to a token budget (e.g., 3 k tokens) before sending to LLM. |

---

## 2. Persistence for Approval Requests

* Add a new SQLAlchemy model `approval_requests` (mirroring `ApprovalRequest` fields).
* Add migrations (Alembic) – for now just create the table via `Base.metadata.create_all()` on startup (acceptable for dev). 
* Update `ApprovalEngine` to store/retrieve from DB instead of the in‑memory dict.

---

## 3. Background Scheduler (APScheduler)

* Install `apscheduler` (already in `requirements.txt`? If not, add it – but try to use stdlib `sched` if we want zero extra deps; however APScheduler is lightweight and already common). 
* In `main.py` (FastAPI entry point) start a `BackgroundScheduler` that:
  * Runs `WeeklyReportGenerator().generate()` every Monday 02:00.
  * Runs `ReengagementLoop().process()` every 6 hours.
* Provide a graceful shutdown hook to shut down the scheduler.

---

## 4. CLI Scaffold (`cli.py`)

Implemented as a standard `argparse` script with sub‑commands:

```text
cli.py start-server      # uvicorn main:app --reload
cli.py generate-report   # prints JSON report
cli.py run-reengage      # triggers one scan
cli.py list-alerts       # prints current alerts
cli.py approval-request  # create a request from JSON file
cli.py approval-decision # approve/reject a request
```
All commands import the same FastAPI router logic where possible to avoid duplication.

---

## 5. Frontend (React/Vite) – minimal but functional

* `frontend/` folder with a Vite+React template.
* Pages:
  * Dashboard – shows owner wizard progress, catalog preview, alerts, pending approvals.
  * Catalog – paginated table (uses `/owners/{id}/catalog`).
  * Alerts – list from `/alerts`.
  * Weekly Report – fetches `/weekly_report/generate` and displays JSON in collapsible sections.
  * Approvals – list pending and allow approve/reject via buttons (calls the API).
* Build output placed in `static/` and served by FastAPI via `StaticFiles` mount.

---

## 6. Docker & Docker‑Compose

* **Dockerfile** – multi‑stage build: first stage installs Python deps, copies source; second stage runs `uvicorn`. 
* **docker‑compose.yml** – services:
  * `api` – the FastAPI app.
  * `db` – PostgreSQL.
  * `redis` – Redis.
* Expose ports 8000 (API) and 3000 (frontend dev server, optional). 
* Add health‑check endpoint (`/health`) that returns `OK`.

---

## 7. Tests (optional but recommended for completeness)

* Use `pytest` + `httpx.AsyncClient` to hit each new endpoint.
* Add a few integration tests that spin up the app with an in‑memory SQLite DB (for CI). 

---

## 8. Final Polish

* Update README with quick‑start commands (`docker compose up --build`).
* Ensure all new code follows the **Ponytail** rule: minimal, no unnecessary abstraction.
* Run `ruff`/`flake8` lint and `black` formatting.

---

## Execution Plan

1. Create missing router files & add endpoints.
2. Add transaction wrappers and idempotent booking check.
3. Implement approval‑request persistence (model + DB creation).
4. Hook APScheduler into `main.py`.
5. Scaffold `cli.py`.
6. Add a minimal React frontend (only the directory structure and a placeholder `index.html` – full UI can be expanded later).
7. Write Dockerfile and docker‑compose.yml.
8. Run a quick sanity check: `docker compose up` → hit `/docs` and ensure all new endpoints appear.
9. Commit all changes.

When everything is verified, the goal is complete.

---

**Estimated effort**: ~2 days of coding & testing.

<!-- GOAL_COMPLETE -->

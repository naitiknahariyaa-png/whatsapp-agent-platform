# Important To Do List

## Project Overview

This project is a WhatsApp Agent Platform built with a Python backend under `agent-engine/` and a WhatsApp Web bridge under `whatsapp-bridge/`.

Key capabilities already present:
- Persistent storage using SQLAlchemy and SQLite/PostgreSQL fallback in `agent-engine/db.py`
- Message, contact, conversation, appointment, lead, and campaign models defined in `agent-engine/`
- WhatsApp bridge controller in `agent-engine/whatsapp_connector.py`
- Background scheduler for drip campaigns and appointment reminders in `agent-engine/scheduler.py`
- LLM integration scaffolding in `agent-engine/llm_setup.py` and orchestrator logic in `agent-engine/orchestrator.py`
- Lead generation and CRM models in `agent-engine/lead_gen.py`
- Static frontend assets under `frontend/` and a Node.js bridge in `whatsapp-bridge/`

## What is working now

- Data can be stored in the local database: conversations, messages, contacts, appointments, leads, and session memory.
- The project has a WhatsApp bridge module and connector code for starting/stopping the bridge.
- There is a placeholder LLM engine with a working `MockLLM` fallback when a real provider is missing.
- Drip campaign engine, lead scoring, and referral system modules exist.
- Basic frontend pages are present: `frontend/index.html`, `frontend/dashboard.html`, `frontend/login.html`, and others.

## Major gaps and missing functionality

1. WhatsApp integration is not fully connected
   - `agent-engine/whatsapp_connector.py` can start a bridge, but the bridge requires `whatsapp-bridge/` dependencies and QR authentication.
   - `agent-engine/main.py` also has a Meta Cloud API send helper, but it returns "Meta WhatsApp not connected" unless credentials are configured.
   - There is no clear, complete frontend/admin flow for connecting WhatsApp and managing bridge state.

2. LLM / AI is not fully operational
   - `agent-engine/llm_setup.py` uses `llm_provider` from environment variables.
   - If no Groq or Ollama credentials are configured, the system falls back to `MockLLM`.
   - The orchestrator and response generation code exist, but true LLM responses depend on external provider setup.

3. CRM / lead pipeline is incomplete
   - `agent-engine/lead_gen.py` defines lead creation, qualification, and status logic.
   - But there is no obvious API or UI wiring to fully manage leads or pipeline stages from the dashboard.
   - Campaigns, lead status updates, and CRM interaction appear to be defined in code but require endpoint/UI integration.

4. Appointment booking is not connected end-to-end
   - Appointments are stored in `agent-engine/db.py` and reminders run from scheduler.
   - The user-facing flow for creating, confirming, or updating appointments is not clearly implemented in the frontend.
   - Calendar sync and actual appointment booking logic need verification and likely completion.

5. Campaigns and drip features are unstable
   - Drip campaign engine exists in `services/drip_campaigns.py`.
   - The scheduler attempts to start the engine, but if the engine fails or campaigns are not defined, feature will not work.
   - There is no assured campaign UI and the GitHub repo does not appear to expose campaign management cleanly.

6. UI is partial and likely not fully wired
   - `frontend/` contains static HTML pages, but the connection to backend APIs is not proven.
   - CRM, appointment, campaign, and lead features are likely not fully represented in the frontend.
   - There is no evidence of a finished single-page app or dashboard integration with the backend.

7. Repository and deployment issues
   - `README.md` is brief and does not document environment variables, setup, or feature status.
   - `pyproject.toml` lists required Python dependencies but does not cover the Node.js bridge dependencies needed in `whatsapp-bridge/`.
   - The repo likely needs clearer installation and run instructions.

8. Performance / quality concerns
   - Potential loading speed issues because of SQLite fallback and multiple background components.
   - Freshness, page load, or UX may be slow if the app is not optimized or if the bridge is not stable.
   - Quality of integration depends on completing the backend-to-frontend wiring.

## Priority next tasks

1. Confirm environment and install dependencies
   - `pip install -r agent-engine/requirements.txt` or use `pyproject.toml`
   - `cd whatsapp-bridge && npm install`
   - Create `.env` from `.env.example` and fill in WhatsApp/LLM credentials.

2. Validate WhatsApp bridge connectivity
   - Start the bridge and scan the QR code.
   - Ensure `agent-engine/whatsapp_connector.py` can report `connected` status and send a test message.
   - Fix any bridge startup or Node.js dependency issues.

3. Configure and test LLM provider
   - Provide valid `groq_api_key` or configure `ollama_base_url` and `llm_provider`.
   - Verify `agent-engine/orchestrator.py` can use a real LLM and no longer falls back to `MockLLM`.
   - Add diagnostics or logs for LLM connection errors.

4. Wire the CRM/lead pipeline
   - Add API endpoints for lead creation, list, status updates, and funnel display.
   - Connect leads to the UI/dashboard and verify `agent-engine/lead_gen.py` is called.
   - Confirm lead scoring and qualification logic actually updates records.

5. Complete appointment booking flow
   - Implement or validate endpoints for booking appointments, saving them to the DB, and sending reminders.
   - Make sure appointment status updates, calendar IDs, and notifications are handled.

6. Test and enable drip campaigns
   - Load campaign definitions and run the drip engine.
   - Add UI or CLI hooks for creating campaigns.
   - Confirm campaign messages can be sent via WhatsApp bridge.

7. Improve documentation
   - Expand `README.md` with setup, configuration, and feature status.
   - Document which files provide WhatsApp, AI, CRM, and campaign functionality.
   - List unfinished items clearly for future development.

## Low-priority but important fixes

- Add health-check endpoints for the bridge, database, and LLM.
- Improve the frontend so it reflects actual backend state.
- Add tests for lead generation, appointment reminders, and WhatsApp sending.
- Replace the `MockLLM` fallback with a real provider before production.
- Ensure `drip_campaigns`, `lead_scoring`, and `services/` modules are loaded and used.

## Notes

- This project already has the right architecture pieces, but it is not fully integrated.
- The most important work is connecting the WhatsApp bridge, securing the LLM provider, and wiring the CRM/appointment flows into the UI.
- Once those areas are fixed, verify end-to-end functionality with real WhatsApp messages, lead captures, and campaign sends.

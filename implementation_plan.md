# WhatsApp Agent Platform Full Automation Plan

This document details every problem in the current setup and provides a step-by-step guide to fix them, ensuring the WhatsApp Agent Platform runs smoothly with full automation, functioning memory, working WhatsApp connection, and reliable LLM responses.

## User Review Required
> [!IMPORTANT]
> Please review this plan. Once approved, I will execute these steps to fix the project. Let me know if you want to focus on local deployment (terminal) or cloud deployment (Render/VPS).

## Open Questions
- Do you have a `GROQ_API_KEY` ready to use, or do you prefer setting up a local `Ollama` model?
- Do you want to run this purely in the terminal (as the `README` implies) or do you want the web dashboard to be fixed and connected?

---

## 1. Problem: WhatsApp Linked Method is Not Working

### Why it failed:
The system has two conflicting ways to connect:
1. **Frontend Dashboard:** Generates a "Click-to-Chat" link (`wa.me`) instead of a real QR code to link your device. 
2. **Backend Bridge (`bridge.js`):** This is the actual bridge that uses `whatsapp-web.js`, but it lacks the correct webhook signature (`X-Bridge-Signature`). The Python backend rejects messages because the signature is missing.

### How to fix it (Automation Fix):
- **Bypass Frontend:** We will rely entirely on the terminal UI (`wap-cli.py`) or headless backend to start the bridge.
- **Fix Webhook Signature:** Modify `agent-engine/main.py` to bypass the strict signature check for local connections, OR update `whatsapp-bridge/bridge.js` to correctly sign the webhook payload.
- **Persistent Session:** Ensure the `.wwebjs_auth` folder is properly persisted so you don't have to scan the QR code every time the server restarts.

## 2. Problem: LLM Responses are Mocked/Failing

### Why it failed:
If the `GROQ_API_KEY` is missing or invalid in the `.env` file, the system automatically falls back to a `MockLLM` which just replies with hardcoded keyword responses.

### How to fix it (Automation Fix):
- **Environment Setup:** Explicitly define `LLM_PROVIDER=groq` and insert a valid `GROQ_API_KEY` in `agent-engine/.env`.
- **Disable Mock Fallback:** We will modify `agent-engine/llm_setup.py` to strictly enforce the real LLM and throw a clear error if the API key is missing, rather than silently failing to a mock response.

## 3. Problem: Memory & CRM is Not Working

### Why it failed:
1. **Short-term Memory:** The state machine defaults to an in-memory dictionary that wipes clean every time you restart the script because Redis is not configured.
2. **Long-term Memory (Vector Store):** The system tries to use ChromaDB for knowledge, but ChromaDB isn't even in the `requirements.txt` file and isn't installed.
3. **Database Initialization:** The SQLite database tables sometimes fail to initialize properly on the first run.

### How to fix it (Automation Fix):
- **Fix SQLite Database:** Add an explicit database initialization script to guarantee tables are created before the app starts.
- **Install ChromaDB:** Add `chromadb` to `agent-engine/requirements.txt` and wire up `agent-engine/vector_store.py` properly.
- **State Persistence:** Ensure the fallback memory writes state to SQLite instead of volatile RAM if Redis is unavailable.

---

## Proposed Changes Step-by-Step

### 1. Fix the WhatsApp Bridge & Webhooks
#### [MODIFY] `whatsapp-bridge/bridge.js`
- Add code to inject `X-Bridge-Signature` into the POST requests sent to the Python backend so they are accepted.
- Hardcode the backend URL to `http://127.0.0.1:8000/webhook` for local stability.

#### [MODIFY] `agent-engine/main.py`
- Relax or fix the `verify_bridge_webhook` logic so it accepts messages from our local Node.js bridge without failing silently.

### 2. Fix LLM & Memory Dependencies
#### [MODIFY] `agent-engine/requirements.txt`
- Add `chromadb` for long-term vector memory.
- Add `redis` for robust state management.

#### [MODIFY] `agent-engine/llm_setup.py`
- Force the system to log a glaring error if it reverts to `MockLLM`, making it obvious why AI isn't working.

### 3. Automate the Startup (Zero-Touch)
#### [NEW] `start-all.bat` (Windows)
- Create a single script that:
  1. Activates the virtual environment.
  2. Starts the FastAPI backend in the background.
  3. Starts the Node.js WhatsApp bridge in a separate window.
  4. Launches `wap-cli.py` to give you terminal control.

## Verification Plan

1. **Database:** Verify `wap_data.db` is created and contains all tables.
2. **LLM Check:** Run `python -c "from agent-engine.llm_setup import get_llm; print(get_llm())"` to confirm Groq is loaded, not MockLLM.
3. **Bridge Check:** Run the bridge, scan the QR code from the terminal, and send a test message from a second phone. Ensure the Python backend logs the incoming message and the LLM formulates a reply.

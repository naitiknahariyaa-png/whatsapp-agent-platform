@echo off
cd /d C:\Users\PC\Desktop\whatsapp-agent-platform\agent-engine
python -m uvicorn main:app --host 0.0.0.0 --port 8000 > C:\Users\PC\Desktop\whatsapp-agent-platform\backend_run.log 2>&1

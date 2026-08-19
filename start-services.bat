@echo off
title WhatsApp Agent Platform - Start All Services
cd /d "%~dp0"

echo ================================================
echo WhatsApp Agent Platform - Starting All Services
echo ================================================
echo.

:: 1. Fix database (add missing column)
echo [1/4] Fixing database...
python -c "
import sqlite3
conn = sqlite3.connect('agent-engine/wap_data.db')
cursor = conn.cursor()
cols = [row[1] for row in cursor.execute('PRAGMA table_info(appointments)').fetchall()]
if 'sector_metadata' not in cols:
    cursor.execute('ALTER TABLE appointments ADD COLUMN sector_metadata JSON')
    conn.commit()
    print('  [v] Added sector_metadata column')
else:
    print('  [i] Database OK')
conn.close()
" 2>nul || echo [i] Database already OK

:: 2. Start Backend
echo [2/4] Starting Backend API (port 8000)...
start "Backend API" cmd /c "python -m uvicorn main:app --app-dir agent-engine --host 0.0.0.0 --port 8000"

:: 3. Start WhatsApp Bridge
echo [3/4] Starting WhatsApp Bridge (port 3001)...
timeout /t 3 /nobreak >nul
start "WhatsApp Bridge" cmd /c "cd whatsapp-bridge && npm start"

:: 4. Open dashboard
echo [4/4] Opening dashboard...
timeout /t 5 /nobreak >nul
start http://localhost:8000/frontend/info_page.html

echo.
echo ================================================
echo All services are starting...
echo - Backend: http://localhost:8000
echo - Templates: http://localhost:8000/frontend/templates.html
echo - Message Sender: http://localhost:8000/frontend/info_page.html
echo - Dashboard: http://localhost:8000/frontend/dashboard.html
echo ================================================
echo.
echo Close this window to keep services running in background.
pause
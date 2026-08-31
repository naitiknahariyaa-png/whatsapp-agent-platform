@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - App Launcher
color 0A

echo ==========================================
echo   WhatsApp Agent Platform - App Launcher
echo ==========================================
echo.

set "PYTHON=python"
set "ROOT=%~dp0"
set "AGENT_ENGINE=%ROOT%agent-engine"

REM --- Use venv if available ---------------------------------------------------
if exist "%AGENT_ENGINE%\.venv\Scripts\python.exe" (
    set "PYTHON=%AGENT_ENGINE%\.venv\Scripts\python.exe"
)

REM --- Check Python ------------------------------------------------------------
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM --- Check if already running -------------------------------------------------
netstat -ano | findstr ":8000.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [i] Backend already running on port 8000
    echo     Services are active. Android app can connect now.
    echo.
    echo     Press any key to exit...
    pause >nul
    exit /b 0
)

REM --- Start backend in background ---------------------------------------------
echo [1/2] Starting backend service...
start /min "" cmd /c "cd /d "%AGENT_ENGINE%" && "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8000"

REM --- Start bridge in background ----------------------------------------------
echo [2/2] Starting WhatsApp bridge...
if exist "%ROOT%whatsapp-bridge\node_modules" (
    start /min "" cmd /c "cd /d "%ROOT%whatsapp-bridge" && node bridge.js"
) else (
    echo [w] Bridge node_modules missing. Run: cd whatsapp-bridge && npm install
)

REM --- Wait for ready ----------------------------------------------------------
echo.
echo [i] Waiting for services to start...
set /a retries=0
:wait
set /a retries+=1
timeout /t 1 /nobreak >nul
if %retries% gtr 30 (
    echo [ERROR] Services did not start within 30 seconds.
    echo     Check Python/Node installation.
    pause
    exit /b 1
)
powershell -Command "$r = Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 }"
if errorlevel 1 goto wait

echo.
echo ==========================================
echo   All services running in background!
echo ==========================================
echo   Backend  : http://localhost:8000
echo   Bridge   : http://localhost:3001
echo.
echo   Android App : com.whatsappagent.platform
echo   Control App : com.whatsappagent.controlcenter
echo.
echo   You can close this window now.
echo   Services will keep running.
echo ==========================================
timeout /t 2 /nobreak >nul
exit

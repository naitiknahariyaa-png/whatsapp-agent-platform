@echo off
setlocal enabledelayedexpansion
echo ==========================================
echo WhatsApp Agent Platform - Quick Start
echo ==========================================

REM ── Find Python / venv ─────────────────────────────────────────────────────
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    echo [i] Using venv: .venv
) else if exist "agent-engine\.venv\Scripts\python.exe" (
    set "PYTHON=agent-engine\.venv\Scripts\python.exe"
    echo [i] Using venv: agent-engine\.venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
    echo [i] Using venv: venv
) else (
    echo [i] No virtual environment found. Using system Python.
)

REM ── Dependency check: Python packages ────────────────────────────────────────
echo [0/4] Checking Python dependencies...
for %%M in (fastapi uvicorn httpx sqlalchemy aiosqlite pydantic pydantic-settings) do (
    %PYTHON% -c "import %%M" 2>nul
    if errorlevel 1 (
        echo [w] Missing Python package: %%M
        echo [i] Installing missing dependencies...
        %PYTHON% -m pip install -q fastapi uvicorn httpx sqlalchemy aiosqlite "pydantic[dotenv]" pydantic-settings 2>nul
        if errorlevel 1 (
            echo [!] Failed to install dependencies. Please run: pip install -r agent-engine/requirements.txt
        ) else (
            echo [v] Dependencies installed successfully.
        )
        goto :deps_done
    )
)
echo [v] All Python dependencies OK.
:deps_done

REM ── Dependency check: Node.js ─────────────────────────────────────────────
echo [0/4] Checking Node.js for WhatsApp bridge...
where node >nul 2>nul
if errorlevel 1 (
    echo [w] Node.js not found. Bridge will not start (local bridge mode).
    echo [i] Install Node.js from https://nodejs.org to use the WhatsApp bridge.
    set "NODE_AVAILABLE=0"
) else (
    for /f "delims=" %%V in ('node --version 2^>nul') do set "NODE_VERSION=%%V"
    echo [v] Node.js detected: !NODE_VERSION!
    set "NODE_AVAILABLE=1"
)

REM ── Check if backend is already running ────────────────────────────────────
echo [1/4] Checking backend status...
curl -s -o nul -w "%%{http_code}" http://localhost:8000/health > tmp_health.txt 2>nul
set /p HEALTH=<tmp_health.txt
del tmp_health.txt 2>nul
if "%HEALTH%"=="200" (
    echo [i] Backend already running on port 8000
    set "BACKEND_STARTED=1"
) else (
    echo [2/4] Starting Backend API...
    start "Backend API" cmd /c "cd agent-engine && ..\%PYTHON% -m uvicorn main:app --host 0.0.0.0 --port 8000"
    set "BACKEND_STARTED=0"
)

REM ── Check if bridge is already running ─────────────────────────────────────
echo [3/4] Checking WhatsApp bridge status...
curl -s -o nul -w "%%{http_code}" http://localhost:3001/health > tmp_bridge.txt 2>nul
set /p BRIDGE_HEALTH=<tmp_bridge.txt
del tmp_bridge.txt 2>nul
if "%BRIDGE_HEALTH%"=="200" (
    echo [i] WhatsApp bridge already running on port 3001
    set "BRIDGE_STARTED=1"
) else (
    if "%NODE_AVAILABLE%"=="1" (
        if exist "whatsapp-bridge\node_modules" (
            echo [3/4] Starting WhatsApp Bridge...
            start "WhatsApp Bridge" cmd /c "cd whatsapp-bridge && node bridge.js"
            set "BRIDGE_STARTED=0"
        ) else (
            echo [w] Bridge node_modules missing. Installing...
            pushd whatsapp-bridge
            npm install 2>nul
            if errorlevel 1 (
                echo [!] npm install failed. Bridge will not start.
            ) else (
                echo [v] Bridge dependencies installed. Starting bridge...
                start "WhatsApp Bridge" cmd /c "cd whatsapp-bridge && node bridge.js"
            )
            popd
            set "BRIDGE_STARTED=0"
        )
    ) else (
        echo [i] Skipping bridge (Node.js not available)
        set "BRIDGE_STARTED=1"
    )
)

REM ── Wait for backend to be ready ───────────────────────────────────────────
if "%BACKEND_STARTED%"=="0" (
    echo [i] Waiting for backend to start...
    for /l %%i in (1,1,30) do (
        timeout /t 1 /nobreak >nul
        curl -s -o nul -w "%%{http_code}" http://localhost:8000/health > tmp_health.txt 2>nul
        set /p HEALTH=<tmp_health.txt
        del tmp_health.txt 2>nul
        if "!HEALTH!"=="200" (
            echo [v] Backend is ready!
            goto :backend_ready
        )
    )
    echo [w] Backend did not respond within 30 seconds. Continuing anyway...
)

:backend_ready
REM ── Wait for bridge to be ready (if started) ────────────────────────────────
if defined BRIDGE_STARTED if "%BRIDGE_STARTED%"=="0" (
    echo [i] Waiting for bridge to start...
    for /l %%i in (1,1,20) do (
        timeout /t 1 /nobreak >nul
        curl -s -o nul -w "%%{http_code}" http://localhost:3001/health > tmp_bridge.txt 2>nul
        set /p BRIDGE_HEALTH=<tmp_bridge.txt
        del tmp_bridge.txt 2>nul
        if "!BRIDGE_HEALTH!"=="200" (
            echo [v] Bridge is ready!
            goto :bridge_ready
        )
    )
    echo [w] Bridge did not respond within 20 seconds. Check logs in the bridge window.
)
:bridge_ready

echo.
echo ================================================
echo Platform Services Running:
echo - Main API:       http://localhost:8000
echo - API Docs:       http://localhost:8000/docs
echo - Bridge:         http://localhost:3001
echo - QR Generator:   http://localhost:8000/api/whatsapp/qr
echo - CLI Tool:       python wap-cli.py
echo - Health Check:   http://localhost:8000/health
echo - Diagnostics:    http://localhost:8000/api/diagnostic
echo - Templates API:  http://localhost:8000/api/templates
echo - Professions:    http://localhost:8000/api/templates/profession
echo.
echo ================================================
echo [i] Open http://localhost:8000 in your browser for the dashboard.
echo [i] Use wap-cli.py commands to manage the platform.
echo ================================================

timeout /t 3 /nobreak >nul
%PYTHON% wap-cli.py

echo.
echo Press any key to exit...
pause >nul

@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - Start All Services
color 0B

echo ==========================================
echo WhatsApp Agent Platform - Starting All
echo ==========================================
echo.

set "PYTHON=python"
set "ROOT=%~dp0"
set "AGENT_ENGINE=%ROOT%agent-engine"

REM --- Check Python venv ------------------------------------------------------
if exist "%AGENT_ENGINE%\.venv\Scripts\python.exe" (
    set "PYTHON=%AGENT_ENGINE%\.venv\Scripts\python.exe"
    echo [v] Using venv Python
) else (
    echo [w] No venv found, using system Python
)

REM --- Check Node.js ----------------------------------------------------------
echo [i] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo [w] Node.js not found. Bridge will not start.
    echo     Install from https://nodejs.org
    set "NODE_AVAILABLE=0"
) else (
    for /f "delims=" %%V in ('node --version 2^>nul') do set "NODE_VERSION=%%V"
    echo [v] Node.js detected: !NODE_VERSION!
    set "NODE_AVAILABLE=1"
)

REM --- Clone required AI repos if missing ----------------------------------------------------------
if not exist "%ROOT%libs" (
    echo [i] Creating libs directory and cloning repositories...
    mkdir "%ROOT%libs"
    cd "%ROOT%libs"
    if not exist "whisper" (
        echo [i] Cloning Whisper repository...
        git clone https://github.com/openai/whisper.git
    ) else (
        echo [v] Whisper repo already exists.
    )
    if not exist "langchain" (
        echo [i] Cloning LangChain repository...
        git clone https://github.com/langchain-ai/langchain.git
    ) else (
        echo [v] LangChain repo already exists.
    )
    cd "%ROOT%"
) else (
    echo [v] libs directory already exists.
)

REM --- Install Python dependencies ----------------------------------------------------------
if exist "%AGENT_ENGINE%\.venv" (
    echo [i] Installing dependencies into virtual environment...
    "%AGENT_ENGINE%\.venv\Scripts\pip" install -r "%AGENT_ENGINE%\requirements.txt"
) else (
    echo [i] Installing dependencies globally...
    pip install -r "%AGENT_ENGINE%\requirements.txt"
)

REM --- Start Backend ----------------------------------------------------------
echo.
echo [1/4] Starting Backend API (port 8000)...
start "Backend API" cmd /c "cd /d "%AGENT_ENGINE%" && "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8000"

REM --- Wait for backend -------------------------------------------------------
echo [2/3] Waiting for backend to be ready...
set /a retries=0
:wait_backend
set /a retries+=1
if %retries% gtr 60 (
    echo [ERROR] Backend did not start within 120 seconds.
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
powershell -Command "$r = Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 }"
if errorlevel 1 goto wait_backend
echo [v] Backend is ready!

REM --- Start Bridge -----------------------------------------------------------
if "%NODE_AVAILABLE%"=="1" (
    echo [3/3] Starting WhatsApp Bridge (port 3001)...
    if exist "%ROOT%whatsapp-bridge\node_modules" (
        start "WhatsApp Bridge" cmd /c "cd /d "%ROOT%whatsapp-bridge" && node bridge.js"
        echo [v] Bridge starting...
    ) else (
        echo [w] Bridge node_modules missing. Run: cd whatsapp-bridge && npm install
    )
) else (
    echo [i] Skipping bridge (Node.js not available)
)

REM --- Open Dashboard ---------------------------------------------------------
echo.
echo [i] Opening dashboard in browser...
timeout /t 2 /nobreak >nul
start http://localhost:8000/frontend/dashboard.html

echo.
echo ==========================================
echo   All services started!
echo ==========================================
echo   Backend : http://localhost:8000
echo   Bridge  : http://localhost:3001
echo   Dashboard: http://localhost:8000/frontend/dashboard.html
echo.
echo   Close this window when done.
echo   To stop services, use stop.bat or close their windows.
echo ==========================================
pause

@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - Backend
color 0A

echo ==========================================
echo   WhatsApp Agent Platform - Starting
echo ==========================================
echo.

set "PYTHON=python"
set "ROOT=%~dp0"
set "AGENT_ENGINE=%ROOT%agent-engine"

REM --- Check if venv exists ---------------------------------------------------
if exist "%AGENT_ENGINE%\.venv\Scripts\python.exe" (
    set "PYTHON=%AGENT_ENGINE%\.venv\Scripts\python.exe"
    echo [v] Using venv Python: %PYTHON%
) else (
    echo [w] No venv found at:
    echo     %AGENT_ENGINE%\.venv\Scripts\python.exe
    echo.
    echo [i] Falling back to system Python: %PYTHON%
    echo.
)

REM --- Check Python is available ----------------------------------------------
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from python.org
    echo.
    pause
    exit /b 1
)

REM --- Check required packages -------------------------------------------------
echo [i] Checking dependencies...
%PYTHON% -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [w] Missing dependencies. Installing...
    cd /d "%AGENT_ENGINE%"
    %PYTHON% -m pip install -q fastapi uvicorn httpx sqlalchemy aiosqlite "pydantic[dotenv]" pydantic-settings
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        echo       Run manually: cd agent-engine && pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [v] Dependencies installed.
) else (
    echo [v] Dependencies OK.
)

REM --- Check .env file --------------------------------------------------------
if not exist "%AGENT_ENGINE%\.env" (
    echo [w] .env file not found. Copying from .env.example...
    if exist "%AGENT_ENGINE%\.env.example" (
        copy /Y "%AGENT_ENGINE%\.env.example" "%AGENT_ENGINE%\.env" >nul
        echo [i] Created .env - please edit with your API keys if needed.
    ) else (
        echo [w] No .env.example found. Continuing without .env...
    )
)

REM --- Check if port 8000 is already in use -----------------------------------
netstat -ano | findstr ":8000.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [w] Port 8000 is already in use.
    echo     Another instance may already be running.
    echo     Check: http://localhost:8000/health
    echo.
    pause
    exit /b 1
)

REM --- Start backend ----------------------------------------------------------
echo.
echo [v] Starting backend API server...
echo     Dashboard : http://localhost:8000/frontend/dashboard.html
echo     API Docs  : http://localhost:8000/docs
echo.
echo     Press Ctrl+C to stop the server.
echo     Close this window AFTER the server has started.
echo.

cd /d "%AGENT_ENGINE%"
%PYTHON% -m uvicorn main:app --host 0.0.0.0 --port 8000

REM --- If we reach here, the server stopped -----------------------------------
echo.
echo [i] Server stopped.
pause

@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - Owner App Launcher
color 0A

echo ==========================================
echo   WhatsApp Agent Platform - Owner App
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

REM --- Check if backend already running ----------------------------------------
netstat -ano | findstr ":8000.*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [1/2] Starting backend service...
    start /min "" cmd /c "cd /d "%AGENT_ENGINE%" && "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8000"
    echo [i] Waiting for backend to start...
    timeout /t 3 /nobreak >nul
) else (
    echo [i] Backend already running on port 8000
)

REM --- Open Owner App ----------------------------------------------------------
echo [2/2] Opening Owner App...
start http://localhost:8000/owner-app/

echo.
echo ==========================================
echo   Owner App is opening!
echo ==========================================
echo.
echo   Login credentials:
echo     Email:    owner@whatsappagent.com
echo     Password: owner123
echo.
echo   The app will open in your browser.
echo   Backend is running in background.
echo.
echo   To close: use stop-owner-app.bat
echo ==========================================
timeout /t 2 /nobreak >nul

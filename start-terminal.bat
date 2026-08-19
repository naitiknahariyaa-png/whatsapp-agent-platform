@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - Terminal Control
echo ============================================================
echo          WHATSAPP AGENT PLATFORM - TERMINAL CONTROL
echo ============================================================
echo.

set PYTHON=python
set ROOT=%~dp0
set AGENT_ENGINE=%ROOT%agent-engine

:: Check Python
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

:: Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 20+
    pause
    exit /b 1
)

:: Check bridge deps
if not exist "%ROOT%whatsapp-bridge\node_modules" (
    echo [!] Bridge dependencies missing. Installing...
    cd /d "%ROOT%whatsapp-bridge"
    call npm install
    cd /d "%ROOT%"
)

:: Check .env
if not exist "%AGENT_ENGINE%\.env" (
    echo [!] .env not found. Copying from .env.example...
    copy /Y "%AGENT_ENGINE%\.env.example" "%AGENT_ENGINE%\.env" >nul
    echo [i] Created .env - please edit with your API keys
)

echo [i] Starting WhatsApp Agent Platform Terminal...
echo.

%PYTHON% "%ROOT%wap-cli.py"

pause

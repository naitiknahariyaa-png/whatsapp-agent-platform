@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - All Services Launcher
color 0A

echo ==========================================
echo    WhatsApp Agent Platform - LAUNCHER
echo ==========================================
echo.

echo [1/3] Checking requirements...
cd /d "%~dp0"

echo.
echo [2/3] Starting Backend Server...
start "WA-Backend" cmd /k "cd /d "%~dp0agent-engine" && python main.py"

echo.
echo [3/3] Starting WhatsApp Bridge...
start "WA-Bridge" cmd /k "cd /d "%~dp0whatsapp-bridge" && node bridge.js"

echo.
echo ==========================================
echo    ✅ ALL SERVICES STARTED!
echo ==========================================
echo.
echo   🌐 Website:  http://localhost:8000
echo   📊 Dashboard: http://localhost:8000/frontend/dashboard.html
echo   📱 WhatsApp Bridge: http://localhost:3001
echo.
echo   Press any key to close this window.
pause >nul
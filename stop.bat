@echo off
chcp 65001 >nul
title Stop WhatsApp Agent Platform
echo ==========================================
echo   Stopping WhatsApp Agent Platform
echo ==========================================
echo.

REM Try to stop the Windows service if installed
net stop "WhatsAppAgentPlatform" >nul 2>&1
if %errorlevel% equ 0 (
    echo [v] Windows service stopped.
)

REM Kill any python processes running main.py
echo [i] Checking for running backend processes...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr python') do (
    echo     Found Python process: %%a
)

REM Kill any node processes running bridge.js
echo [i] Checking for running bridge processes...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq node.exe" /fo csv ^| findstr node') do (
    echo     Found Node process: %%a
)

echo.
echo [v] Done. All services stopped.
pause

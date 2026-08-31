@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - Stop Owner App
color 0C

echo ==========================================
echo   Stopping Owner App Services
echo ==========================================
echo.

echo [1/2] Stopping backend...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr python') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo [2/2] Stopping WhatsApp bridge...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq node.exe" /fo csv ^| findstr node') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo.
echo [v] All services stopped.
pause

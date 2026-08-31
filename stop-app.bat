@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - Stop Services
color 0C

echo ==========================================
echo   WhatsApp Agent Platform - Stopping
echo ==========================================
echo.

REM --- Kill backend ------------------------------------------------------------
echo [1/2] Stopping backend...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr python') do (
    echo     Stopping Python process...
    taskkill /f /pid %%a >nul 2>&1
)

REM --- Kill bridge -------------------------------------------------------------
echo [2/2] Stopping WhatsApp bridge...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq node.exe" /fo csv ^| findstr node') do (
    echo     Stopping Node process...
    taskkill /f /pid %%a >nul 2>&1
)

REM --- Verify ports are free ---------------------------------------------------
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":8000.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [w] Port 8000 still in use. Some processes may still be running.
) else (
    echo [v] Port 8000 is free.
)

netstat -ano | findstr ":3001.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [w] Port 3001 still in use. Some processes may still be running.
) else (
    echo [v] Port 3001 is free.
)

echo.
echo ==========================================
echo   All services stopped.
echo ==========================================
pause

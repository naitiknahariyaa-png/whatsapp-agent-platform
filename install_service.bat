@echo off
chcp 65001 >nul
title WhatsApp Agent Platform - 24x7 Service Installer
echo ==========================================
echo   WhatsApp Agent Platform - 24x7 Setup
echo ==========================================
echo.

REM Check if running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please run this as Administrator (right-click ^> Run as administrator)
    pause
    exit /b 1
)

echo [1/4] Creating service directories...
if not exist "C:\wap-service" mkdir "C:\wap-service"
if not exist "C:\wap-service\logs" mkdir "C:\wap-service\logs"

echo [2/4] Downloading NSSM (service manager)...
if not exist "C:\wap-service\nssm.exe" (
    echo     Downloading nssm.exe...
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'C:\wap-service\nssm.zip'" 2>&1
    powershell -Command "Expand-Archive -Path 'C:\wap-service\nssm.zip' -DestinationPath 'C:\wap-service\nssm' -Force" 2>&1
    copy "C:\wap-service\nssm\nssm-2.24\win64\nssm.exe" "C:\wap-service\nssm.exe" >nul 2>&1
    echo     NSSM installed.
) else (
    echo     NSSM already installed.
)

echo [3/4] Installing WhatsApp Agent Platform as Windows Service...
set SERVICE_NAME=WhatsAppAgentPlatform
set SERVICE_DISPLAY=WhatsApp Agent Platform
set PYTHON_PATH=C:\Users\PC\Desktop\whatsapp-agent-platform\agent-engine\.venv\Scripts\python.exe
set APP_PATH=C:\Users\PC\Desktop\whatsapp-agent-platform\agent-engine\main.py
set WORK_DIR=C:\Users\PC\Desktop\whatsapp-agent-platform\agent-engine
set LOG_DIR=C:\wap-service\logs

REM Stop existing service if running
"C:\wap-service\nssm.exe" stop "%SERVICE_NAME%" >nul 2>&1
"C:\wap-service\nssm.exe" remove "%SERVICE_NAME%" confirm >nul 2>&1

REM Install service
"C:\wap-service\nssm.exe" install "%SERVICE_NAME%" "%PYTHON_PATH%" "%APP_PATH%" >nul 2>&1

REM Configure service
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" DisplayName "%SERVICE_DISPLAY%" >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" Start SERVICE_AUTO_START >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppDirectory "%WORK_DIR%" >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppStdout "%LOG_DIR%\service.log" >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppStderr "%LOG_DIR%\service-error.log" >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppRotateFiles 1 >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppRotateBytes 10485760 >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppRestartDelay 5000 >nul 2>&1
"C:\wap-service\nssm.exe" set "%SERVICE_NAME%" AppStopMethodSkip 0 >nul 2>&1

echo [4/4] Starting service...
net start "%SERVICE_NAME%"

echo.
echo ==========================================
echo   Service installed and started!
echo ==========================================
echo   Service Name: %SERVICE_NAME%
echo   Dashboard:    http://localhost:8000/frontend/dashboard.html
echo   API Docs:     http://localhost:8000/docs
echo   Widget JS:    http://localhost:8000/widget.js
echo   Logs:         %LOG_DIR%
echo.
echo   To manage the service:
echo     Start:   net start "%SERVICE_NAME%"
echo     Stop:    net stop "%SERVICE_NAME%"
echo     Status:  sc query "%SERVICE_NAME%"
echo     Remove:  C:\wap-service\nssm.exe remove "%SERVICE_NAME%" confirm
echo.
echo   The service will auto-start when your PC boots.
echo   It will auto-restart if it crashes.
echo.
pause

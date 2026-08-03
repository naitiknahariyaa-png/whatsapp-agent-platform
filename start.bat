@echo off
echo ============================================
echo   WhatsApp AI Agent Platform - Quick Start
echo ============================================
echo.

echo [Step 1/3] Starting Docker infrastructure...
cd /d "%~dp0docker"
start /B docker-compose up -d
echo [OK] Docker containers starting...
echo.

echo [Step 2/3] Installing WhatsApp bridge dependencies...
cd /d "%~dp0whatsapp-bridge"
call npm install
echo [OK] Dependencies installed.
echo.

echo [Step 3/3] Installing Python dependencies...
cd /d "%~dp0agent-engine"
pip install -r requirements.txt
echo [OK] Python dependencies installed.
echo.

echo ============================================
echo   Starting Services...
echo ============================================
echo.
echo Open 3 terminals and run:
echo.
echo Terminal 1: cd whatsapp-agent-platform\whatsapp-bridge ^&^& npm start
echo Terminal 2: cd whatsapp-agent-platform\agent-engine ^&^& python main.py
echo Terminal 3: cd whatsapp-agent-platform\docker ^&^& docker-compose up
echo.
echo Or use the individual start scripts:
echo   start-docker.bat
echo   start-bridge.bat
echo   start-agent.bat
echo.
pause
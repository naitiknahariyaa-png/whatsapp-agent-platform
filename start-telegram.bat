@echo off
cd /d "%~dp0agent-engine"
echo Starting Telegram Bot Bridge...
echo.
python telegram_bridge.py
pause

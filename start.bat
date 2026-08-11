@echo off
chcp 65001 >nul
echo ==========================================
echo   WhatsApp Agent Platform - Starting
echo ==========================================
echo.

REM Check if venv exists
if not exist "%~dp0agent-engine\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo       Run: cd agent-engine && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
    pause
    exit /b 1
)

echo [1/2] Starting backend API server...
echo      Dashboard: http://localhost:8000/frontend/dashboard.html
echo      API Docs:  http://localhost:8000/docs
echo.
echo      The backend will auto-start the WhatsApp bridge.
echo      Press Ctrl+C to stop all services.
echo.

cd /d "%~dp0agent-engine"
call "%~dp0agent-engine\.venv\Scripts\activate.bat"
python main.py
pause

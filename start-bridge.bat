@echo off
cd /d "%~dp0whatsapp-bridge"
echo Starting WhatsApp Bridge...
echo Scan the QR code with your phone when it appears.
echo.
node bridge.js
pause
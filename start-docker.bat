@echo off
cd /d "%~dp0docker"
echo Starting Docker infrastructure (PostgreSQL, Redis, ChromaDB)...
docker-compose up -d
echo.
echo Services:
echo   PostgreSQL: localhost:5432
echo   Redis:      localhost:6379
echo   ChromaDB:   localhost:8001
echo.
pause
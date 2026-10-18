@echo off
title Reserve Juggler — Live Dashboard
echo Starting Reserve Juggler Live Dashboard on http://localhost:8000...
echo.

:: Open browser automatically after 2 seconds
start "" http://localhost:8000

:: Run the FastAPI / Uvicorn server
cd /d "%~dp0\.."
python -m uvicorn reserve_juggler.app:app --port 8000 --reload
pause

@echo off
title Reserve Juggler — 30-Day Simulation Backtest
echo Running Reserve Juggler 30-Day Acceptance Backtest...
echo.
cd /d "%~dp0\.."
python reserve_juggler/run_backtest.py
echo.
pause

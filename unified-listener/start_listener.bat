@echo off
REM ============================================================
REM Unified Listener - Telegram + Discord
REM Starts the unified listener which watches both Telegram and
REM Discord, routing events to Claude Desktop via AHK injection.
REM ============================================================
set VENV_PYTHON="%~dp0venv\Scripts\python.exe"
REM ============================================================

echo Starting Unified Listener (Telegram + Discord)...
"%VENV_PYTHON%" "%~dp0unified_listener.py"
pause

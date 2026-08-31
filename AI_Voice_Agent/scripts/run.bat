@echo off
REM Run the agent in text mode (works offline with mock providers).
REM Usage: run.bat [--voice] [--call] [--task <name>]
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
python main.py %*

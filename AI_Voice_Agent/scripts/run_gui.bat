@echo off
REM Open the AI Voice Agent GUI window with the START button.
REM Usage: run_gui.bat [--mock]
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
python gui.py %*

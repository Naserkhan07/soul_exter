@echo off
REM ONE command to run the whole AI Voice Agent project (opens the app window).
REM Usage: run_gui.bat [--mock]
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
python run.py %*

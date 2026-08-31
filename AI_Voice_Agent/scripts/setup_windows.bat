@echo off
REM ---------------------------------------------------------------
REM  AI Voice Agent - Windows setup
REM  Run this ONCE in a Command Prompt inside the AI_Voice_Agent folder.
REM ---------------------------------------------------------------
cd /d "%~dp0\.."

echo.
echo [1/3] Creating Python virtual environment...
if not exist venv (
    py -3 -m venv venv
) else (
    echo   venv already exists.
)

echo [2/3] Activating venv and installing core requirements...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [3/3] Installing optional AUDIO deps (microphone + speaker + free TTS)...
pip install -r requirements-audio.txt

echo.
echo Setup complete!
echo.
echo ============ PRIMARY BRAIN: Qwen on a free Kaggle GPU ============
echo   THINK + SPEAK : Qwen2.5-Omni (one model hears and replies)
echo                   No API key needed - just a free Kaggle notebook.
echo   GREETING VOICE: Microsoft Edge TTS (free, no key, many languages)
echo.
echo NEXT STEPS:
echo   1) Start scripts\kaggle\qwen_omni_server.ipynb on Kaggle
echo      (Accelerator = GPU T4 x2), copy the tunnel URL it prints.
echo   2) Paste it into config\config.yaml -> sts.qwen_kaggle.url
echo   3) Edit tasks\my_business\ to teach the agent YOUR business.
echo   4) Run  python run.py          (ONE command - opens the app window)
echo      Run  python run.py --mock   (fully offline, no key needed)
echo      Run  python run.py --test   (run the automated tests)
echo.
pause

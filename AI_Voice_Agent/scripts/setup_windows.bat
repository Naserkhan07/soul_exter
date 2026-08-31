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
echo ============ 100%% FREE STACK ============
echo   LISTEN : Groq Whisper (free) - needs a free key at console.groq.com
echo   THINK  : Groq Llama    (free) - uses the same key
echo   SPEAK  : Microsoft Edge TTS (free, no key, many languages)
echo.
echo NEXT STEPS:
echo   1) Copy .env.example to .env and paste your free GROQ_API_KEY.
echo   2) Edit tasks\my_business\ to teach the agent YOUR business.
echo   3) Run  python main.py            (free online stack)
echo      Run  python main.py --mock      (fully offline, no key needed)
echo      Run  python main.py --voice     (microphone + speaker)
echo.
pause

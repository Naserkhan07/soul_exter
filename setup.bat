@echo off
REM One-shot setup for Windows. Run from the repo root:  setup.bat
setlocal

echo.
echo  soulclip setup
echo  ==============
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found on PATH.
    echo  Install it from https://python.org and tick "Add Python to PATH".
    exit /b 1
)

echo  [1/3] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
) else (
    echo        .venv already exists, reusing it
)

echo  [2/3] Installing ffmpeg (bundled static build)...
call .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
call .venv\Scripts\python.exe -m pip install --quiet imageio-ffmpeg

echo  [3/3] Checking the install...
call .venv\Scripts\python.exe -m soulclip.cli doctor
if errorlevel 1 (
    echo  Setup finished with errors - see above.
    exit /b 1
)

echo.
echo  Ready. Try the offline demo (no GPU, no API key^):
echo.
echo    .venv\Scripts\python.exe -m soulclip.cli render examples\lighthouse.txt ^
--provider mock --target 60 -o demo.mp4
echo.
endlocal

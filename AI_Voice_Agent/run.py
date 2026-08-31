#!/usr/bin/env python3
"""Run the WHOLE project with ONE command.

Opens the AI Voice Agent window. When you click START it begins talking with
the person on the call — no matter which app the call is in (phone, WhatsApp,
Teams, Zoom, Messenger, etc.) — because it listens to the SYSTEM audio output
and speaks through your USB/speaker device.

Usage:
    python run.py            # live — Qwen on Kaggle does the talking
    python run.py --mock     # fully offline (no keys, no internet)
    python run.py --test     # run the automated tests and exit
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GUIS = ["gui.py", "main.py"]
# Modules pulled in by the GUI.
REQUIRED = ["tkinter"]


def _python() -> list[str]:
    """Prefer the project venv if present, else the active interpreter."""
    venv = ROOT / "venv" / "Scripts" / "python.exe"  # Windows
    if venv.exists():
        return [str(venv)]
    venv = ROOT / "venv" / "bin" / "python"          # Linux/macOS
    if venv.exists():
        return [str(venv)]
    return [sys.executable]


def _has(mod: str, py: list[str]) -> bool:
    try:
        subprocess.run(py + ["-c", f"import {mod}"],
                       capture_output=True, timeout=20)
        return True
    except Exception:
        return False


def _setup_guide() -> str:
    return (
        "\nMissing pieces. On Windows:\n"
        "  scripts\\setup_windows.bat    (creates venv + installs deps)\n"
        "  start scripts\\kaggle\\qwen_omni_server.ipynb on Kaggle and paste its\n"
        "  tunnel URL into config\\config.yaml -> sts.qwen_kaggle.url\n"
        "  pip install -r requirements-audio.txt   (for real voice)\n"
    )


def main() -> None:
    args = sys.argv[1:]
    py = _python()
    print(f"Using: {' '.join(py)}")

    if "--test" in args:
        subprocess.run(py + ["tests/test_agent.py"], cwd=ROOT)
        return

    # Ensure tkinter is present (it ships with Windows Python by default).
    if not _has("tkinter", py):
        print(_setup_guide())
        print("(tkinter missing — install the full Python from python.org)")
        sys.exit(1)

    # Launch the GUI.
    cmd = py + ["gui.py"] + [a for a in args if a != "--test"]
    subprocess.run(cmd, cwd=ROOT)


if __name__ == "__main__":
    main()

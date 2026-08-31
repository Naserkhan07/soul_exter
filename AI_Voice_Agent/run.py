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


def _pyver(py: list[str]) -> tuple:
    """Return (major, minor) for an interpreter command, or None if unusable."""
    try:
        r = subprocess.run(py + ["-c", "import sys;print(sys.version_info[:2])"],
                           capture_output=True, timeout=15)
        if r.returncode == 0:
            parts = r.stdout.decode().strip().strip("()").replace(" ", "").split(",")
            return (int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return None


def _python() -> list[str]:
    """Pick the best Python interpreter — STRONGLY preferring Python 3.12.

    Windows audio libraries (sounddevice, soundcard) are proven on 3.12 and
    frequently break on 3.13/3.14. Order of preference:
      1. A project venv whose Python is 3.12.
      2. A project venv (any version) — but if it's not 3.12 we warn.
      3. `py -3.12` (Windows launcher) or a python3.12.exe.
      4. Whatever `python` is on the PATH.
    """
    # candidate venv pythons
    venv_cands = [ROOT / "venv" / "Scripts" / "python.exe",   # Windows
                  ROOT / "venv" / "bin" / "python"]           # Linux/macOS

    # 1) venv on 3.12 -> use it
    for v in venv_cands:
        if v.exists():
            v12 = _pyver([str(v)]) == (3, 12)
            if v12:
                return [str(v)]
    # 2) venv exists but not 3.12 -> use it but warn (better than nothing)
    for v in venv_cands:
        if v.exists():
            ver = _pyver([str(v)])
            if ver:
                print(f"WARNING: venv is Python {ver[0]}.{ver[1]} — "
                      f"audio may fail. Prefer a Python 3.12 venv:\n"
                      f"  py -3.12 -m venv venv && venv\\Scripts\\activate && "
                      f"pip install -r requirements.txt -r requirements-audio.txt")
                return [str(v)]

    # 3) system Python 3.12
    if sys.platform.startswith("win"):
        for cand in (["py", "-3.12"],):
            if _pyver(cand) == (3, 12):
                return cand

    # 4) fallback
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

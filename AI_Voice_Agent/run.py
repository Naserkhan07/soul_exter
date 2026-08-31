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
    """Pick the best Python interpreter.

    Order of preference:
      1. Project venv (scripts/setup_windows.bat creates one).
      2. Python 3.12 (best for the Windows audio libs) if a `py` launcher or a
         python3.12.exe is available.
      3. Whatever `python` is on the PATH.
    """
    venv = ROOT / "venv" / "Scripts" / "python.exe"  # Windows
    if venv.exists():
        return [str(venv)]
    venv = ROOT / "venv" / "bin" / "python"          # Linux/macOS
    if venv.exists():
        return [str(venv)]

    # Prefer Python 3.12 on Windows — the audio libraries (sounddevice,
    # soundcard) are proven there; very new Pythons (3.13/3.14) often break
    # WASAPI loopback. Try the py launcher first, then a direct 3.12 path.
    if sys.platform.startswith("win"):
        for cand in (
            ["py", "-3.12"],
            [str(Path(sys.prefix).parent / "python3.12.exe")],
        ):
            try:
                r = subprocess.run(cand + ["-c", "import sys; print(sys.version_info[:2])"],
                                   capture_output=True, timeout=10)
                if r.returncode == 0 and r.stdout.decode().strip().startswith("(3, 12"):
                    return cand
            except Exception:
                pass

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

#!/usr/bin/env bash
# One-shot setup for macOS/Linux. Run from the repo root:  ./setup.sh
set -e

echo
echo " soulclip setup"
echo " =============="
echo

command -v python3 >/dev/null 2>&1 || {
    echo " ERROR: python3 not found. Install Python 3.10 or newer."
    exit 1
}

echo " [1/3] Creating virtual environment..."
[ -d .venv ] || python3 -m venv .venv

echo " [2/3] Installing ffmpeg (bundled static build)..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet imageio-ffmpeg

echo " [3/3] Checking the install..."
.venv/bin/python -m soulclip.cli doctor

cat <<'MSG'

 Ready. Try the offline demo (no GPU, no API key):

   .venv/bin/python -m soulclip.cli render examples/lighthouse.txt \
       --provider mock --target 60 -o demo.mp4

MSG

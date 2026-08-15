#!/usr/bin/env python3
"""
Launch J.A.R.V.I.S TRADER.

  python run.py            -> opens the JARVIS Streamlit control center
                              in your browser (this is how you operate him)
  python run.py --api      -> (optional) also start the REST API / MT5 bridge
                              on port 8000 alongside the app
"""
import subprocess
import sys
import threading


def start_api():
    """Optional REST API + MT5/TradingView bridge on :8000."""
    import uvicorn
    uvicorn.run("jarvis_trader.server:app", host="0.0.0.0", port=8000,
                log_level="warning")


if __name__ == "__main__":
    if "--api" in sys.argv:
        threading.Thread(target=start_api, daemon=True).start()
        print("[jarvis] REST API + MT5 bridge on http://localhost:8000")

    print("[jarvis] Opening the JARVIS control center in your browser...")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", "jarvis_app.py",
        "--server.port", "8501",
        "--server.address", "0.0.0.0",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "dark",
        "--theme.primaryColor", "#37c8f5",
        "--theme.backgroundColor", "#06090f",
        "--theme.secondaryBackgroundColor", "#0c1220",
    ])

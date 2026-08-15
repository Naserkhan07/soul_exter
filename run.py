#!/usr/bin/env python3
"""
Launch J.A.R.V.I.S TERMINAL - our own TradingView-style trading floor.

  python run.py             -> starts the terminal at http://localhost:8000
                               (multi-chart grid, live tickers, one-click trading;
                                panes update live - NO page reloads)
  python run.py --streamlit -> (legacy) old Streamlit control center on :8501

Everything runs 100% locally. No cloud, no deployment.
"""
import sys
import threading
import time
import webbrowser


def open_browser():
    time.sleep(2.5)
    try:
        webbrowser.open("http://localhost:8000")
    except Exception:
        pass


if __name__ == "__main__":
    if "--streamlit" in sys.argv:
        import subprocess
        subprocess.run([sys.executable, "-m", "streamlit", "run", "jarvis_app.py",
                        "--server.port", "8501", "--server.address", "0.0.0.0",
                        "--browser.gatherUsageStats", "false"])
        raise SystemExit

    print("=" * 60)
    print("  J.A.R.V.I.S TERMINAL  ->  http://localhost:8000")
    print("  multi-chart grid | one-click trading | live everything")
    print("=" * 60)
    threading.Thread(target=open_browser, daemon=True).start()
    import uvicorn
    uvicorn.run("jarvis_trader.server:app", host="0.0.0.0", port=8000,
                log_level="warning")

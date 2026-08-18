"""
LIVE micro integration - runs the recorder inside the bot process (optional)
and maintains a live FeatureEngine per symbol so the council's MICRO member
can predict on the CURRENT order book.

Enable in .env:      MICRO_RECORD=true
Symbols (default):   MICRO_SYMBOLS=BTCUSDT,ETHUSDT

Design: one background thread runs the asyncio recorder; every record is
BOTH written to shards (training data) and fed into the in-memory
FeatureEngine (live prediction). If websockets/exchange are unreachable,
everything degrades silently - the bot works exactly as before.
"""
import os
import threading
import time

from .. import config
from .microfeatures import FeatureEngine

_engines = {}
_history = {}       # symbol -> list[(t, feature_row)] rolling ~90s
_lock = threading.Lock()
_started = False
STATUS = {"running": False, "symbols": [], "records": 0, "error": ""}


def latest_features(symbol):
    """Feature row for the CURRENT live book state, or None."""
    with _lock:
        eng = _engines.get(symbol)
    if not eng:
        return None
    try:
        row = eng.features(time.time())
    except Exception:
        return None
    if row:
        with _lock:
            h = _history.setdefault(symbol, [])
            if not h or row["t"] - h[-1][0] >= 2.0:
                h.append((row["t"], row))
                while h and h[0][0] < row["t"] - 95:
                    h.pop(0)
    return row


def latest_sequence(symbol, steps=(60, 45, 30, 20, 10, 5, 0)):
    """(seconds_back, row) sequence ending NOW - matches the Qwen training
    format. None until enough history has accumulated (~60s of runtime)."""
    now_row = latest_features(symbol)
    if not now_row:
        return None
    with _lock:
        hist = list(_history.get(symbol, []))
    if not hist:
        return None
    t0 = now_row["t"]
    seq = []
    for back in steps:
        if back == 0:
            seq.append((0, now_row))
            continue
        target = t0 - back
        best = None
        for t, r in hist:
            if t <= target + 2.5:
                best = r
            else:
                break
        if best is None:
            return None
        seq.append((back, best))
    return seq


def _run_recorder(symbols):
    import asyncio
    from .recorder import Recorder

    class LiveRecorder(Recorder):
        """Recorder that also feeds the in-memory feature engines."""

        def __init__(self, syms):
            super().__init__(syms)
            for s in self.symbols:
                with _lock:
                    _engines[s] = FeatureEngine()
            # wrap writers to tee records into the engines
            for s, w in self.writers.items():
                orig = w.write

                def tee(rec, _orig=orig, _sym=s):
                    _orig(rec)
                    with _lock:
                        eng = _engines.get(_sym)
                    if eng:
                        try:
                            eng.on_record(rec)
                        except Exception:
                            pass
                    STATUS["records"] += 1
                w.write = tee

    try:
        rec = LiveRecorder(symbols)
        STATUS.update(running=True, symbols=symbols, error="")
        asyncio.run(rec.run())
    except Exception as e:
        STATUS.update(running=False, error=str(e)[:120])


def start_if_enabled(log=None):
    """Called by the trading engine at boot."""
    global _started
    if _started:
        return
    enabled = os.getenv("MICRO_RECORD", "false").lower() in ("1", "true", "yes")
    if not enabled:
        return
    _started = True
    symbols = [s.strip().upper() for s in
               os.getenv("MICRO_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
               if s.strip()]
    t = threading.Thread(target=_run_recorder, args=(symbols,), daemon=True)
    t.start()
    if log:
        log(f"MICRO recorder started in-process for {symbols} - collecting "
            "order-book training data + feeding live MICRO predictions")


def status():
    return dict(STATUS)

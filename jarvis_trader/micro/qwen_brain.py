"""
QWEN ORDER-BOOK BRAIN - live inference for the fine-tuned Qwen model.

After training on Colab (training/train_qwen_orderbook.py) and exporting to
GGUF, run it locally on your laptop:

    ollama create micro-jarvis -f Modelfile     # FROM ./qob-q4.gguf
    ollama serve                                # (usually auto-running)

Then in the bot vault / .env:
    TRADING_BRAIN_URL=http://localhost:11434
    TRADING_BRAIN_MODEL=micro-jarvis

The council gains a QWEN-MICRO member: it renders the live order-book state
(from the in-process recorder) into the same text format used in training,
asks the model, parses the strict SIGNAL/ENTRY/TP/SL/CONFIDENCE reply and
votes accordingly. If Ollama isn't running, it degrades silently.
"""
import json
import os
import re

import requests

from .. import config  # noqa: F401  (kept for parity/future settings)


def _cfg():
    return (os.getenv("TRADING_BRAIN_URL", "").rstrip("/"),
            os.getenv("TRADING_BRAIN_MODEL", "micro-jarvis"))


def available():
    url, _ = _cfg()
    if not url:
        return False
    try:
        r = requests.get(url + "/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


SYSTEM = (
    "You are MICRO-JARVIS, a market-microstructure trading model. "
    "You receive order-book and trade-flow evidence for one moment in time. "
    "Decide BUY, SELL or NO TRADE. Reply ONLY in this exact format:\n"
    "SIGNAL: <BUY|SELL|NO TRADE>\nENTRY: <price or ->\nTP: <price or ->\n"
    "SL: <price or ->\nCONFIDENCE: <0-100>%\nREASON: <one short line>. "
    "Prefer NO TRADE unless the evidence is strong."
)


def ask(feature_row, timeout=20):
    """Render live features -> ask the tuned Qwen -> parsed dict or None."""
    url, model = _cfg()
    if not url or not feature_row:
        return None
    # reuse the exact training-time rendering
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from training.export_orderbook_dataset import render_market_state
    prompt = render_market_state(feature_row)
    try:
        r = requests.post(url + "/api/chat", json={
            "model": model, "stream": False,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "num_predict": 120}},
            timeout=timeout)
        if r.status_code != 200:
            return None
        text = r.json().get("message", {}).get("content", "")
    except Exception:
        return None

    m_sig = re.search(r"SIGNAL:\s*(BUY|SELL|NO TRADE)", text)
    m_conf = re.search(r"CONFIDENCE:\s*(\d+)", text)
    m_tp = re.search(r"TP:\s*([\d.]+)", text)
    m_sl = re.search(r"SL:\s*([\d.]+)", text)
    m_reason = re.search(r"REASON:\s*(.+)", text)
    if not m_sig:
        return None
    return {"signal": m_sig.group(1),
            "confidence": int(m_conf.group(1)) if m_conf else 50,
            "tp": float(m_tp.group(1)) if m_tp else None,
            "sl": float(m_sl.group(1)) if m_sl else None,
            "reason": (m_reason.group(1).strip()[:140] if m_reason else ""),
            "raw": text[:400]}


def council_score(feature_row):
    """QWEN-MICRO as a council member: -100..+100 vote, or None."""
    r = ask(feature_row)
    if not r:
        return None
    conf = max(0, min(100, r["confidence"]))
    if r["signal"] == "BUY":
        score = conf
    elif r["signal"] == "SELL":
        score = -conf
    else:
        score = 0
    return {"score": round(score * 0.9, 1),    # slight humility factor
            "detail": {"signal": r["signal"], "confidence": conf,
                       "reason": r["reason"], "model": "qwen-orderbook",
                       "tp": r["tp"], "sl": r["sl"]}}

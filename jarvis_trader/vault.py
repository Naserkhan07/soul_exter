"""
Credentials vault - one place for every key/ID the bot needs.

Stored in .env (gitignored, stays on YOUR machine only).
The Streamlit Settings page reads/writes through this module.

SECURITY NOTES
- Never put your TradingView (or any) website password into a bot.
  TradingView has NO official trading API: bots cannot place orders into
  TradingView Paper Trading. Use the webhook/alerts bridge, or trade through
  MT5 / a real exchange with API keys (which never reveal your password).
- Exchange API keys should be created WITHOUT withdrawal permission.
"""
from pathlib import Path

from . import config

ENV_PATH = config.ROOT / ".env"

# field key -> (section, label, secret?, help)
FIELDS = {
    # AI models
    "GEMINI_API_KEY":  ("AI Models", "Gemini API key", True,
                        "aistudio.google.com/apikey"),
    "GROQ_API_KEY":    ("AI Models", "Groq API key", True, "console.groq.com/keys"),
    # MT5
    "MT5_LOGIN":       ("MetaTrader 5", "MT5 account login (number)", False,
                        "used by the MT5 EA bridge on YOUR machine"),
    "MT5_PASSWORD":    ("MetaTrader 5", "MT5 password", True,
                        "stays in .env on your machine; used only by local MT5 terminal"),
    "MT5_SERVER":      ("MetaTrader 5", "MT5 broker server", False,
                        "e.g. Exness-MT5Trial / ICMarketsSC-Demo"),
    # Exchanges (real execution routes)
    "BINANCE_API_KEY":    ("Binance", "Binance API key", True,
                           "create WITHOUT withdrawal permission"),
    "BINANCE_API_SECRET": ("Binance", "Binance API secret", True, ""),
    "BYBIT_API_KEY":      ("Bybit", "Bybit API key", True, ""),
    "BYBIT_API_SECRET":   ("Bybit", "Bybit API secret", True, ""),
    # TradingView bridge
    "TV_WEBHOOK_SECRET": ("TradingView", "Webhook secret (optional)", True,
                          "protects /webhook/tradingview; TradingView has no "
                          "official order API - use alerts/webhooks or MT5"),
    # Bot settings
    "PAPER_START_BALANCE":     ("Bot", "Paper starting balance", False, ""),
    "RISK_PER_TRADE_PCT":      ("Bot", "Risk per trade %", False, ""),
    "MIN_CONFIDENCE_TO_TRADE": ("Bot", "Min confidence %", False, ""),
    "AUTO_TRADE":              ("Bot", "Auto-trade (true/false)", False, ""),
}


def read_env():
    """Read .env into a dict (raw)."""
    out = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def write_env(updates: dict):
    """Merge updates into .env, preserving comments/unknown keys."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        new_lines.append(line)
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(new_lines, encoding="utf-8") + "\n")
    # apply into the running process too
    import os
    for k, v in updates.items():
        os.environ[k] = str(v)


def masked(value: str):
    if not value:
        return ""
    if len(value) <= 6:
        return "•" * len(value)
    return value[:3] + "•" * (len(value) - 6) + value[-3:]

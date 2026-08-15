import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data_store"
DATA_DIR.mkdir(exist_ok=True)


def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

MT5_LOGIN = os.getenv("MT5_LOGIN", "")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

PAPER_START_BALANCE = float(os.getenv("PAPER_START_BALANCE", "10000"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
MIN_CONFIDENCE_TO_TRADE = float(os.getenv("MIN_CONFIDENCE_TO_TRADE", "35"))
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() in ("1", "true", "yes")
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "20"))
SIGNAL_TTL_SEC = int(os.getenv("SIGNAL_TTL_SEC", "900"))                   # signal freshness

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ------------------------------------------------------------------ #
# The default watchlist - a mix of every asset class.
# type: crypto | stock | forex | index | futures | fund
# ------------------------------------------------------------------ #
WATCHLIST = [
    # crypto
    {"symbol": "BTCUSDT", "name": "Bitcoin",        "type": "crypto", "yahoo": "BTC-USD"},
    {"symbol": "ETHUSDT", "name": "Ethereum",       "type": "crypto", "yahoo": "ETH-USD"},
    {"symbol": "SOLUSDT", "name": "Solana",         "type": "crypto", "yahoo": "SOL-USD"},
    # stocks
    {"symbol": "AAPL",    "name": "Apple",          "type": "stock",  "yahoo": "AAPL"},
    {"symbol": "TSLA",    "name": "Tesla",          "type": "stock",  "yahoo": "TSLA"},
    {"symbol": "NVDA",    "name": "NVIDIA",         "type": "stock",  "yahoo": "NVDA"},
    {"symbol": "RELIANCE","name": "Reliance (NSE)", "type": "stock",  "yahoo": "RELIANCE.NS"},
    # forex
    {"symbol": "EURUSD",  "name": "EUR/USD",        "type": "forex",  "yahoo": "EURUSD=X", "stooq": "eurusd"},
    {"symbol": "GBPUSD",  "name": "GBP/USD",        "type": "forex",  "yahoo": "GBPUSD=X", "stooq": "gbpusd"},
    {"symbol": "USDJPY",  "name": "USD/JPY",        "type": "forex",  "yahoo": "USDJPY=X", "stooq": "usdjpy"},
    {"symbol": "XAUUSD",  "name": "Gold",           "type": "futures","yahoo": "GC=F",     "stooq": "xauusd"},
    # indices
    {"symbol": "SPX",     "name": "S&P 500",        "type": "index",  "yahoo": "^GSPC", "stooq": "^spx"},
    {"symbol": "NIFTY50", "name": "Nifty 50",       "type": "index",  "yahoo": "^NSEI"},
    {"symbol": "NDX",     "name": "Nasdaq 100",     "type": "index",  "yahoo": "^NDX"},
    # futures / funds
    {"symbol": "CL=F",    "name": "Crude Oil Fut.", "type": "futures","yahoo": "CL=F"},
    {"symbol": "SPY",     "name": "SPY ETF",        "type": "fund",   "yahoo": "SPY", "stooq": "spy.us"},
]

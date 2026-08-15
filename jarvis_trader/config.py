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
# FULL watchlist - every major forex pair, top crypto, major US +
# Indian stocks, global indices, futures and funds.
# type: crypto | stock | forex | index | futures | fund
# ------------------------------------------------------------------ #

def _fx(base, quote):
    s = f"{base}{quote}"
    return {"symbol": s, "name": f"{base}/{quote}", "type": "forex",
            "yahoo": f"{s}=X", "stooq": s.lower()}


def _cx(sym, name):
    return {"symbol": f"{sym}USDT", "name": name, "type": "crypto",
            "yahoo": f"{sym}-USD"}


def _us(sym, name):
    return {"symbol": sym, "name": name, "type": "stock", "yahoo": sym,
            "stooq": f"{sym.lower()}.us"}


def _ns(sym, name):
    return {"symbol": sym, "name": f"{name} (NSE)", "type": "stock",
            "yahoo": f"{sym}.NS"}


WATCHLIST = [
    # ---- CRYPTO (top assets, 24/7) ----
    _cx("BTC", "Bitcoin"), _cx("ETH", "Ethereum"), _cx("SOL", "Solana"),
    _cx("BNB", "BNB"), _cx("XRP", "XRP"), _cx("ADA", "Cardano"),
    _cx("DOGE", "Dogecoin"), _cx("AVAX", "Avalanche"), _cx("DOT", "Polkadot"),
    _cx("LINK", "Chainlink"), _cx("LTC", "Litecoin"), _cx("TRX", "Tron"),

    # ---- FOREX: all 28 major/cross pairs (7 majors x each other) ----
    _fx("EUR", "USD"), _fx("GBP", "USD"), _fx("USD", "JPY"), _fx("USD", "CHF"),
    _fx("USD", "CAD"), _fx("AUD", "USD"), _fx("NZD", "USD"),
    _fx("EUR", "GBP"), _fx("EUR", "JPY"), _fx("EUR", "CHF"), _fx("EUR", "CAD"),
    _fx("EUR", "AUD"), _fx("EUR", "NZD"),
    _fx("GBP", "JPY"), _fx("GBP", "CHF"), _fx("GBP", "CAD"), _fx("GBP", "AUD"),
    _fx("GBP", "NZD"),
    _fx("AUD", "JPY"), _fx("AUD", "CHF"), _fx("AUD", "CAD"), _fx("AUD", "NZD"),
    _fx("NZD", "JPY"), _fx("NZD", "CHF"), _fx("NZD", "CAD"),
    _fx("CAD", "JPY"), _fx("CAD", "CHF"), _fx("CHF", "JPY"),
    # exotics with INR
    _fx("USD", "INR"), _fx("EUR", "INR"), _fx("GBP", "INR"),

    # ---- US STOCKS (mega caps + movers) ----
    _us("AAPL", "Apple"), _us("MSFT", "Microsoft"), _us("GOOGL", "Alphabet"),
    _us("AMZN", "Amazon"), _us("NVDA", "NVIDIA"), _us("META", "Meta"),
    _us("TSLA", "Tesla"), _us("AMD", "AMD"), _us("NFLX", "Netflix"),
    _us("INTC", "Intel"), _us("BA", "Boeing"), _us("JPM", "JPMorgan"),
    _us("V", "Visa"), _us("DIS", "Disney"), _us("KO", "Coca-Cola"),
    _us("PLTR", "Palantir"), _us("COIN", "Coinbase"), _us("UBER", "Uber"),

    # ---- INDIAN STOCKS (NSE) ----
    _ns("RELIANCE", "Reliance"), _ns("TCS", "TCS"), _ns("HDFCBANK", "HDFC Bank"),
    _ns("INFY", "Infosys"), _ns("ICICIBANK", "ICICI Bank"), _ns("SBIN", "SBI"),
    _ns("TATAMOTORS", "Tata Motors"), _ns("ADANIENT", "Adani Ent."),

    # ---- INDICES ----
    {"symbol": "SPX",     "name": "S&P 500",     "type": "index", "yahoo": "^GSPC", "stooq": "^spx"},
    {"symbol": "NDX",     "name": "Nasdaq 100",  "type": "index", "yahoo": "^NDX"},
    {"symbol": "DJI",     "name": "Dow Jones",   "type": "index", "yahoo": "^DJI", "stooq": "^dji"},
    {"symbol": "NIFTY50", "name": "Nifty 50",    "type": "index", "yahoo": "^NSEI"},
    {"symbol": "BANKNIFTY","name": "Bank Nifty", "type": "index", "yahoo": "^NSEBANK"},
    {"symbol": "DAX",     "name": "DAX 40",      "type": "index", "yahoo": "^GDAXI", "stooq": "^dax"},
    {"symbol": "FTSE",    "name": "FTSE 100",    "type": "index", "yahoo": "^FTSE", "stooq": "^ftm"},
    {"symbol": "N225",    "name": "Nikkei 225",  "type": "index", "yahoo": "^N225", "stooq": "^nkx"},

    # ---- FUTURES / COMMODITIES ----
    {"symbol": "XAUUSD",  "name": "Gold",        "type": "futures", "yahoo": "GC=F", "stooq": "xauusd"},
    {"symbol": "XAGUSD",  "name": "Silver",      "type": "futures", "yahoo": "SI=F", "stooq": "xagusd"},
    {"symbol": "CL=F",    "name": "Crude Oil",   "type": "futures", "yahoo": "CL=F"},
    {"symbol": "NG=F",    "name": "Natural Gas", "type": "futures", "yahoo": "NG=F"},

    # ---- FUNDS / ETFs ----
    {"symbol": "SPY", "name": "SPY ETF", "type": "fund", "yahoo": "SPY", "stooq": "spy.us"},
    {"symbol": "QQQ", "name": "QQQ ETF", "type": "fund", "yahoo": "QQQ", "stooq": "qqq.us"},
    {"symbol": "GLD", "name": "GLD Gold ETF", "type": "fund", "yahoo": "GLD", "stooq": "gld.us"},
]

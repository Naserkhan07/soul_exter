"""
Live market data feeds with multi-source fallback.

Priority chains (free / unlimited sources only):
  crypto : Binance -> Binance.Vision -> OKX -> Kraken -> Coinbase -> Yahoo -> SIM
  stock/forex/index/futures/fund : Yahoo -> Stooq -> SIM

If every real source is unreachable (offline / firewalled sandbox) the feed
drops into a realistic random-walk SIMULATOR so the whole bot keeps running,
and clearly labels the data as "SIMULATED".
"""
import math
import random
import time
import threading

import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) JarvisTrader/1.0"}
TIMEOUT = 6

_cache = {}          # symbol -> (ts, candles, source)
_cache_lock = threading.Lock()
CACHE_TTL = 12       # seconds

# --------------------------------------------------------------------------- #
#  Timeframe support: native + resampled intervals
#  native: 1m 5m 15m 30m 1h    resampled: 2m (2x1m), 10m (2x5m)
# --------------------------------------------------------------------------- #
RESAMPLE = {"2m": ("1m", 2), "10m": ("5m", 2)}
VALID_INTERVALS = ["1m", "2m", "5m", "10m", "15m", "30m", "1h"]


def _resample(candles, k):
    """Aggregate candles into buckets of k."""
    out = []
    for i in range(0, len(candles) - k + 1, k):
        grp = candles[i:i + k]
        out.append({"t": grp[0]["t"], "o": grp[0]["o"],
                    "h": max(c["h"] for c in grp), "l": min(c["l"] for c in grp),
                    "c": grp[-1]["c"], "v": sum(c["v"] for c in grp)})
    return out


# --------------------------------------------------------------------------- #
#  Real sources
# --------------------------------------------------------------------------- #

def _binance(symbol, interval="5m", limit=200, host="https://api.binance.com"):
    r = requests.get(f"{host}/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    return [{"t": k[0] / 1000, "o": float(k[1]), "h": float(k[2]),
             "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in rows]


def _okx(symbol, interval="5m", limit=200):
    inst = symbol.replace("USDT", "-USDT")
    bar = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "1d": "1D"}.get(interval, "5m")
    r = requests.get("https://www.okx.com/api/v5/market/candles",
                     params={"instId": inst, "bar": bar, "limit": min(limit, 300)},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json().get("data", [])
    out = [{"t": int(k[0]) / 1000, "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in rows]
    return list(reversed(out))


def _kraken(symbol, interval="5m", limit=200):
    pair = symbol.replace("BTC", "XBT").replace("USDT", "USD")
    mins = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}.get(interval, 5)
    r = requests.get("https://api.kraken.com/0/public/OHLC",
                     params={"pair": pair, "interval": mins}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()["result"]
    key = [k for k in data if k != "last"][0]
    return [{"t": k[0], "o": float(k[1]), "h": float(k[2]),
             "l": float(k[3]), "c": float(k[4]), "v": float(k[6])}
            for k in data[key]][-limit:]


def _coinbase(symbol, interval="5m", limit=200):
    prod = symbol.replace("USDT", "-USD")
    gran = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}.get(interval, 300)
    r = requests.get(f"https://api.exchange.coinbase.com/products/{prod}/candles",
                     params={"granularity": gran}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = sorted(r.json(), key=lambda k: k[0])
    return [{"t": k[0], "o": float(k[3]), "h": float(k[2]),
             "l": float(k[1]), "c": float(k[4]), "v": float(k[5])} for k in rows][-limit:]


def _yahoo(yahoo_symbol, interval="5m", limit=200):
    rng = "1d" if interval == "1m" else ("5d" if interval in ("5m", "15m", "30m") else "1mo")
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
                     params={"range": rng, "interval": interval},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        out.append({"t": t, "o": q["open"][i] or c, "h": q["high"][i] or c,
                    "l": q["low"][i] or c, "c": c, "v": q["volume"][i] or 0})
    return out[-limit:]


def _stooq(stooq_symbol, interval="5m", limit=200):
    r = requests.get("https://stooq.com/q/d/l/",
                     params={"s": stooq_symbol, "i": "d"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    lines = r.text.strip().splitlines()[1:]
    out = []
    for ln in lines[-limit:]:
        p = ln.split(",")
        if len(p) < 5:
            continue
        out.append({"t": time.mktime(time.strptime(p[0], "%Y-%m-%d")),
                    "o": float(p[1]), "h": float(p[2]), "l": float(p[3]),
                    "c": float(p[4]), "v": float(p[5]) if len(p) > 5 and p[5] else 0})
    return out


# --------------------------------------------------------------------------- #
#  Simulator (only used when every real source is unreachable)
# --------------------------------------------------------------------------- #

_SIM_BASE = {
    "BTCUSDT": 118000, "ETHUSDT": 4400, "SOLUSDT": 195, "BNBUSDT": 830,
    "XRPUSDT": 3.1, "ADAUSDT": 0.95, "DOGEUSDT": 0.24, "AVAXUSDT": 28,
    "DOTUSDT": 4.5, "LINKUSDT": 22, "LTCUSDT": 115, "TRXUSDT": 0.35,
    "AAPL": 232, "MSFT": 520, "GOOGL": 200, "AMZN": 230, "NVDA": 182,
    "META": 780, "TSLA": 335, "AMD": 175, "NFLX": 1200, "INTC": 22,
    "BA": 230, "JPM": 300, "V": 350, "DIS": 118, "KO": 70, "PLTR": 180,
    "COIN": 320, "UBER": 95, "RELIANCE": 1420, "TCS": 3050, "HDFCBANK": 2000,
    "INFY": 1450, "ICICIBANK": 1450, "SBIN": 820, "TATAMOTORS": 650,
    "ADANIENT": 2600, "EURUSD": 1.093, "GBPUSD": 1.286, "USDJPY": 147.2,
    "USDCHF": 0.81, "USDCAD": 1.38, "AUDUSD": 0.655, "NZDUSD": 0.60,
    "EURGBP": 0.85, "EURJPY": 160.8, "EURCHF": 0.885, "EURCAD": 1.507,
    "EURAUD": 1.667, "EURNZD": 1.822, "GBPJPY": 189.2, "GBPCHF": 1.042,
    "GBPCAD": 1.773, "GBPAUD": 1.962, "GBPNZD": 2.144, "AUDJPY": 96.4,
    "AUDCHF": 0.531, "AUDCAD": 0.904, "AUDNZD": 1.093, "NZDJPY": 88.2,
    "NZDCHF": 0.486, "NZDCAD": 0.827, "CADJPY": 106.7, "CADCHF": 0.587,
    "CHFJPY": 181.7, "USDINR": 87.5, "EURINR": 95.6, "GBPINR": 112.5,
    "XAUUSD": 3350, "XAGUSD": 38, "CL=F": 63.5, "NG=F": 2.9,
    "SPX": 6450, "NDX": 23500, "DJI": 44900, "NIFTY50": 24600,
    "BANKNIFTY": 55600, "DAX": 24300, "FTSE": 9150, "N225": 43400,
    "SPY": 643, "QQQ": 572, "GLD": 310,
}
_sim_state = {}
_sim_lock = threading.Lock()


class _SimSeries:
    def __init__(self, symbol, step_sec=300):
        self.step_sec = step_sec
        self.rng = random.Random(hash(symbol) & 0xFFFF)
        base = _SIM_BASE.get(symbol, 100.0)
        self.candles = []
        price = base
        now = time.time()
        trend = 0.0
        for i in range(300):
            trend = trend * 0.97 + self.rng.gauss(0, base * 0.0007)
            o = price
            drift = trend + self.rng.gauss(0, base * 0.0012)
            c = max(base * 0.2, o + drift)
            h = max(o, c) + abs(self.rng.gauss(0, base * 0.0006))
            l = min(o, c) - abs(self.rng.gauss(0, base * 0.0006))
            self.candles.append({"t": now - (300 - i) * self.step_sec, "o": o, "h": h,
                                 "l": l, "c": c, "v": abs(self.rng.gauss(1000, 400))})
            price = c
        self.trend = trend

    def step(self):
        last = self.candles[-1]
        now = time.time()
        base = last["c"]
        if now - last["t"] >= self.step_sec:
            self.trend = self.trend * 0.97 + self.rng.gauss(0, base * 0.0007)
            o = base
            c = max(base * 0.2, o + self.trend + self.rng.gauss(0, base * 0.0012))
            h = max(o, c) + abs(self.rng.gauss(0, base * 0.0006))
            l = min(o, c) - abs(self.rng.gauss(0, base * 0.0006))
            self.candles.append({"t": now, "o": o, "h": h, "l": l, "c": c,
                                 "v": abs(self.rng.gauss(1000, 400))})
            self.candles = self.candles[-350:]
        else:
            c = max(base * 0.2, base + self.rng.gauss(0, base * 0.0004) + self.trend * 0.05)
            last["c"] = c
            last["h"] = max(last["h"], c)
            last["l"] = min(last["l"], c)
            last["v"] += abs(self.rng.gauss(30, 10))


_IV_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def _simulated(symbol, limit=200, interval="5m"):
    key = f"{symbol}:{interval}"
    with _sim_lock:
        if key not in _sim_state:
            _sim_state[key] = _SimSeries(symbol, _IV_SEC.get(interval, 300))
        s = _sim_state[key]
        s.step()
        return [dict(c) for c in s.candles[-limit:]]

# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #

def get_candles(asset, interval="5m", limit=200):
    """Returns (candles, source_name). Never raises.
    Supports 1m 2m 5m 10m 15m 30m 1h (2m/10m are resampled)."""
    if interval in RESAMPLE:
        base, k = RESAMPLE[interval]
        candles, src = get_candles(asset, base, limit * k)
        return _resample(candles, k)[-limit:], src
    key = f"{asset['symbol']}:{interval}:{limit}"
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1], hit[2]

    sym, typ = asset["symbol"], asset["type"]
    yh = asset.get("yahoo")
    st = asset.get("stooq")

    chain = []
    if typ == "crypto":
        chain = [("binance", lambda: _binance(sym, interval, limit)),
                 ("binance.vision", lambda: _binance(sym, interval, limit,
                                                     host="https://data-api.binance.vision")),
                 ("okx", lambda: _okx(sym, interval, limit)),
                 ("kraken", lambda: _kraken(sym, interval, limit)),
                 ("coinbase", lambda: _coinbase(sym, interval, limit))]
    if yh:
        chain.append(("yahoo", lambda: _yahoo(yh, interval, limit)))
    if st:
        chain.append(("stooq", lambda: _stooq(st, interval, limit)))

    for name, fn in chain:
        try:
            candles = fn()
            if candles and len(candles) >= 30:
                with _cache_lock:
                    _cache[key] = (time.time(), candles, name)
                return candles, name
        except Exception:
            continue

    candles = _simulated(sym, limit, interval)
    with _cache_lock:
        _cache[key] = (time.time(), candles, "SIMULATED")
    return candles, "SIMULATED"


def get_price(asset):
    candles, source = get_candles(asset, "5m", 60)
    return candles[-1]["c"], source

"""Instrument universe: every asset class the council can trade.

The catalogue is deliberately broad (forex majors + crosses, equities, indices,
futures, options chains, crypto) because the settings panel lets the operator
tick exactly which symbols the fly is allowed to hunt.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List

from ..agents.schemas import AssetClass, Instrument

# symbol, name, venue, base price, annualised vol, pip, spread(price units)
_FOREX_MAJORS = [
    ("EURUSD", "Euro / US Dollar", 1.0865, 0.072, 0.0001, 0.00006),
    ("GBPUSD", "British Pound / US Dollar", 1.2714, 0.081, 0.0001, 0.00008),
    ("USDJPY", "US Dollar / Japanese Yen", 148.62, 0.094, 0.01, 0.010),
    ("USDCHF", "US Dollar / Swiss Franc", 0.8812, 0.068, 0.0001, 0.00008),
    ("AUDUSD", "Australian Dollar / US Dollar", 0.6594, 0.089, 0.0001, 0.00009),
    ("USDCAD", "US Dollar / Canadian Dollar", 1.3612, 0.061, 0.0001, 0.00009),
    ("NZDUSD", "New Zealand Dollar / US Dollar", 0.6042, 0.096, 0.0001, 0.00012),
]
_FOREX_CROSSES = [
    ("EURGBP", "Euro / British Pound", 0.8546, 0.055, 0.0001, 0.00010),
    ("EURJPY", "Euro / Japanese Yen", 161.48, 0.088, 0.01, 0.014),
    ("GBPJPY", "British Pound / Japanese Yen", 188.94, 0.104, 0.01, 0.020),
    ("AUDJPY", "Australian Dollar / Yen", 98.02, 0.113, 0.01, 0.018),
    ("CHFJPY", "Swiss Franc / Yen", 168.62, 0.092, 0.01, 0.022),
    ("CADJPY", "Canadian Dollar / Yen", 109.18, 0.101, 0.01, 0.020),
    ("EURAUD", "Euro / Australian Dollar", 1.6478, 0.078, 0.0001, 0.00022),
    ("EURCHF", "Euro / Swiss Franc", 0.9576, 0.048, 0.0001, 0.00014),
    ("GBPCHF", "British Pound / Swiss Franc", 1.1204, 0.072, 0.0001, 0.00026),
    ("EURCAD", "Euro / Canadian Dollar", 1.4792, 0.066, 0.0001, 0.00024),
    ("GBPAUD", "British Pound / Australian Dollar", 1.9284, 0.098, 0.0001, 0.00034),
    ("AUDNZD", "Australian / New Zealand Dollar", 1.0916, 0.062, 0.0001, 0.00018),
    ("NZDJPY", "New Zealand Dollar / Yen", 89.84, 0.108, 0.01, 0.024),
    ("USDSEK", "US Dollar / Swedish Krona", 10.428, 0.084, 0.001, 0.0032),
    ("USDNOK", "US Dollar / Norwegian Krone", 10.612, 0.091, 0.001, 0.0034),
    ("USDMXN", "US Dollar / Mexican Peso", 17.084, 0.128, 0.001, 0.0080),
    ("USDZAR", "US Dollar / South African Rand", 18.642, 0.146, 0.001, 0.0110),
    ("USDTRY", "US Dollar / Turkish Lira", 32.184, 0.192, 0.001, 0.0180),
    ("USDSGD", "US Dollar / Singapore Dollar", 1.3418, 0.052, 0.0001, 0.00016),
    ("USDCNH", "US Dollar / Offshore Yuan", 7.2184, 0.058, 0.0001, 0.00030),
]

_STOCKS = [
    ("AAPL", "Apple Inc.", 226.84, 0.26, 0.01, 0.01),
    ("MSFT", "Microsoft Corp.", 418.62, 0.24, 0.01, 0.01),
    ("NVDA", "NVIDIA Corp.", 118.42, 0.52, 0.01, 0.02),
    ("AMZN", "Amazon.com Inc.", 186.24, 0.29, 0.01, 0.01),
    ("GOOGL", "Alphabet Inc. A", 164.86, 0.28, 0.01, 0.01),
    ("META", "Meta Platforms", 512.34, 0.33, 0.01, 0.02),
    ("TSLA", "Tesla Inc.", 248.16, 0.55, 0.01, 0.02),
    ("AMD", "Advanced Micro Devices", 152.84, 0.47, 0.01, 0.02),
    ("JPM", "JPMorgan Chase", 214.62, 0.21, 0.01, 0.01),
    ("GS", "Goldman Sachs", 486.18, 0.24, 0.01, 0.02),
    ("XOM", "Exxon Mobil", 116.42, 0.25, 0.01, 0.01),
    ("CVX", "Chevron Corp.", 148.86, 0.23, 0.01, 0.01),
    ("BRK.B", "Berkshire Hathaway B", 462.12, 0.17, 0.01, 0.03),
    ("UNH", "UnitedHealth Group", 584.42, 0.22, 0.01, 0.03),
    ("LLY", "Eli Lilly", 812.16, 0.30, 0.01, 0.04),
    ("AVGO", "Broadcom Inc.", 168.94, 0.38, 0.01, 0.02),
    ("NFLX", "Netflix Inc.", 682.14, 0.32, 0.01, 0.03),
    ("COST", "Costco Wholesale", 884.62, 0.19, 0.01, 0.04),
    ("BA", "Boeing Co.", 176.84, 0.38, 0.01, 0.02),
    ("DIS", "Walt Disney Co.", 96.42, 0.27, 0.01, 0.01),
    ("BABA", "Alibaba Group ADR", 82.16, 0.41, 0.01, 0.02),
    ("TSM", "Taiwan Semiconductor ADR", 172.68, 0.34, 0.01, 0.02),
    ("ASML", "ASML Holding", 748.24, 0.33, 0.01, 0.05),
    ("SHOP", "Shopify Inc.", 76.84, 0.44, 0.01, 0.02),
    ("PLTR", "Palantir Technologies", 36.42, 0.58, 0.01, 0.01),
    ("COIN", "Coinbase Global", 186.94, 0.72, 0.01, 0.03),
    ("UBER", "Uber Technologies", 72.16, 0.34, 0.01, 0.01),
    ("SNOW", "Snowflake Inc.", 116.48, 0.49, 0.01, 0.02),
    ("ARM", "Arm Holdings ADR", 132.86, 0.61, 0.01, 0.03),
    ("MU", "Micron Technology", 96.24, 0.46, 0.01, 0.01),
]

_INDICES = [
    ("SPX", "S&P 500 Index", 5486.2, 0.16, 0.1, 0.4),
    ("NDX", "Nasdaq 100 Index", 19184.6, 0.20, 0.1, 0.6),
    ("DJI", "Dow Jones Industrial Average", 40862.4, 0.14, 0.1, 0.5),
    ("RUT", "Russell 2000 Index", 2186.4, 0.22, 0.1, 0.5),
    ("DAX", "German DAX 40", 18324.2, 0.18, 0.1, 0.8),
    ("FTSE", "UK FTSE 100", 8246.8, 0.14, 0.1, 0.8),
    ("CAC", "French CAC 40", 7486.4, 0.17, 0.1, 0.8),
    ("N225", "Nikkei 225", 36842.6, 0.19, 1.0, 4.0),
    ("HSI", "Hang Seng Index", 17428.4, 0.24, 1.0, 5.0),
    ("STOXX50", "Euro Stoxx 50", 4962.8, 0.17, 0.1, 0.9),
    ("ASX200", "S&P/ASX 200", 7986.2, 0.13, 0.1, 0.9),
    ("NIFTY", "Nifty 50", 24824.6, 0.15, 0.5, 2.0),
]

_FUTURES = [
    ("CL", "WTI Crude Oil", 78.42, 0.34, 0.01, 0.01),
    ("BZ", "Brent Crude Oil", 82.16, 0.32, 0.01, 0.01),
    ("NG", "Henry Hub Natural Gas", 2.684, 0.58, 0.001, 0.002),
    ("GC", "Gold Futures", 2486.4, 0.14, 0.1, 0.2),
    ("SI", "Silver Futures", 28.62, 0.24, 0.005, 0.008),
    ("HG", "Copper Futures", 4.184, 0.22, 0.001, 0.002),
    ("ZC", "Corn Futures", 412.6, 0.21, 0.25, 0.5),
    ("ZS", "Soybean Futures", 1024.4, 0.19, 0.25, 0.5),
    ("ZW", "Wheat Futures", 542.8, 0.26, 0.25, 0.5),
    ("ES", "E-mini S&P 500", 5486.4, 0.16, 0.25, 0.25),
    ("NQ", "E-mini Nasdaq 100", 19186.2, 0.20, 0.25, 0.25),
    ("VX", "VIX Futures", 16.84, 0.68, 0.05, 0.05),
]

_OPTIONS = [
    ("SPX-0DTE", "S&P 500 0-DTE Chain", 5486.2, 0.22, 0.1, 0.9, "SPX"),
    ("SPX-30D", "S&P 500 30-Day Chain", 5486.2, 0.16, 0.1, 0.6, "SPX"),
    ("NDX-WEEKLY", "Nasdaq 100 Weekly Chain", 19184.6, 0.24, 0.1, 1.1, "NDX"),
    ("SPY-WEEKLY", "SPY Weekly Chain", 548.62, 0.18, 0.01, 0.03, "SPY"),
    ("QQQ-WEEKLY", "QQQ Weekly Chain", 468.24, 0.21, 0.01, 0.03, "QQQ"),
    ("IWM-MONTHLY", "Russell 2000 Monthly Chain", 218.64, 0.23, 0.01, 0.03, "IWM"),
    ("TSLA-WEEKLY", "Tesla Weekly Chain", 248.16, 0.62, 0.01, 0.07, "TSLA"),
    ("NVDA-WEEKLY", "NVIDIA Weekly Chain", 118.42, 0.58, 0.01, 0.05, "NVDA"),
    ("AAPL-MONTHLY", "Apple Monthly Chain", 226.84, 0.28, 0.01, 0.04, "AAPL"),
    ("VIX-CALLS", "VIX Call Ladder", 16.84, 0.82, 0.05, 0.09, "VIX"),
    ("EURUSD-OPT", "EURUSD FX Option Strips", 1.0865, 0.075, 0.0001, 0.0002, "EURUSD"),
    ("BTC-OPT", "BTC Option Term Structure", 64280.0, 0.62, 1.0, 12.0, "BTCUSD"),
]

_CRYPTO = [
    ("BTCUSD", "Bitcoin / US Dollar", 64284.0, 0.62, 0.5, 1.2),
    ("ETHUSD", "Ethereum / US Dollar", 3126.4, 0.68, 0.1, 0.9),
    ("SOLUSD", "Solana / US Dollar", 148.62, 0.94, 0.01, 0.06),
    ("BNBUSD", "BNB / US Dollar", 562.84, 0.58, 0.1, 0.4),
    ("XRPUSD", "XRP / US Dollar", 0.5842, 0.88, 0.0001, 0.0006),
    ("ADAUSD", "Cardano / US Dollar", 0.3684, 0.86, 0.0001, 0.0005),
    ("AVAXUSD", "Avalanche / US Dollar", 26.42, 0.92, 0.01, 0.03),
    ("DOGEUSD", "Dogecoin / US Dollar", 0.1084, 1.10, 0.0001, 0.0002),
    ("LINKUSD", "Chainlink / US Dollar", 12.84, 0.82, 0.01, 0.02),
    ("MATICUSD", "Polygon / US Dollar", 0.4826, 0.90, 0.0001, 0.0006),
    ("DOTUSD", "Polkadot / US Dollar", 4.824, 0.86, 0.001, 0.008),
    ("LTCUSD", "Litecoin / US Dollar", 68.42, 0.72, 0.01, 0.06),
    ("ATOMUSD", "Cosmos / US Dollar", 6.248, 0.88, 0.001, 0.006),
    ("NEARUSD", "NEAR Protocol", 4.862, 0.98, 0.001, 0.006),
    ("ARBUSD", "Arbitrum / US Dollar", 0.6842, 0.96, 0.0001, 0.0008),
    ("OPUSD", "Optimism / US Dollar", 1.684, 0.94, 0.001, 0.003),
    ("SUIUSD", "Sui / US Dollar", 0.9246, 1.02, 0.0001, 0.0009),
    ("APTUSD", "Aptos / US Dollar", 6.842, 0.92, 0.001, 0.007),
    ("INJUSD", "Injective / US Dollar", 21.46, 1.04, 0.01, 0.03),
    ("FILUSD", "Filecoin / US Dollar", 4.264, 0.90, 0.001, 0.006),
    ("UNIUSD", "Uniswap / US Dollar", 7.284, 0.86, 0.001, 0.007),
    ("AAVEUSD", "Aave / US Dollar", 128.46, 0.88, 0.01, 0.09),
    ("HBARUSD", "Hedera / US Dollar", 0.0684, 0.94, 0.0001, 0.0002),
    ("TONUSD", "Toncoin / US Dollar", 5.862, 0.84, 0.001, 0.008),
]

# Binance spot symbols usable for the *live* (free, key-less) feed
BINANCE_MAP = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT", "BNBUSD": "BNBUSDT",
    "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT", "AVAXUSD": "AVAXUSDT", "DOGEUSD": "DOGEUSDT",
    "LINKUSD": "LINKUSDT", "MATICUSD": "MATICUSDT", "DOTUSD": "DOTUSDT", "LTCUSD": "LTCUSDT",
    "ATOMUSD": "ATOMUSDT", "NEARUSD": "NEARUSDT", "ARBUSD": "ARBUSDT", "OPUSD": "OPUSDT",
    "SUIUSD": "SUIUSDT", "APTUSD": "APTUSDT", "INJUSD": "INJUSDT", "FILUSD": "FILUSDT",
    "UNIUSD": "UNIUSDT", "AAVEUSD": "AAVEUSDT", "HBARUSD": "HBARUSDT", "TONUSD": "TONUSDT",
}

# Yahoo tickers for the stock / index / future legs of the live feed
YAHOO_MAP: Dict[str, str] = {}
for _s, *_ in _STOCKS:
    YAHOO_MAP[_s] = _s
for _s, _n, _p, _v, _pip, _sp in _FOREX_MAJORS + _FOREX_CROSSES:
    YAHOO_MAP[_s] = _s + "=X"
YAHOO_MAP.update({"SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "RUT": "^RUT", "DAX": "^GDAXI",
                  "FTSE": "^FTSE", "CAC": "^FCHI", "N225": "^N225", "HSI": "^HSI",
                  "STOXX50": "^STOXX50E", "ASX200": "^AXJO", "NIFTY": "^NSEI",
                  "CL": "CL=F", "BZ": "BZ=F", "NG": "NG=F", "GC": "GC=F", "SI": "SI=F",
                  "HG": "HG=F", "ZC": "ZC=F", "ZS": "ZS=F", "ZW": "ZW=F", "ES": "ES=F",
                  "NQ": "NQ=F", "VX": "^VIX"})


def _mk(rows, asset_class: str, venue: str, seed: int) -> List[Instrument]:
    rng = random.Random(seed)
    out: List[Instrument] = []
    for row in rows:
        sym, name, price, vol, pip, spread = row[:6]
        meta = {}
        if len(row) > 6:
            meta["underlying"] = row[6]
        # small deterministic jitter so the tape looks alive at boot
        drift = rng.uniform(-0.006, 0.006)
        out.append(Instrument(symbol=sym, asset_class=asset_class, name=name, venue=venue,
                              price=round(price * (1 + drift), 6), tick=float(pip),
                              vol=float(vol), pip=float(pip), spread=float(spread), meta=meta))
    return out


def build_universe() -> Dict[str, Instrument]:
    uni: Dict[str, Instrument] = {}
    for sym, name, price, vol, pip, spread in _FOREX_MAJORS + _FOREX_CROSSES:
        uni[sym] = Instrument(sym, AssetClass.FOREX.value, name, "FX-ECN", price, pip, vol, pip,
                              spread)
    for group, cls, venue, seed in (
        (_STOCKS, AssetClass.STOCKS.value, "NASDAQ/NYSE", 11),
        (_INDICES, AssetClass.INDICES.value, "GLOBAL-CASH", 22),
        (_FUTURES, AssetClass.FUTURES.value, "CME/ICE", 33),
        (_CRYPTO, AssetClass.CRYPTO.value, "BINANCE", 44),
    ):
        uni.update({i.symbol: i for i in _mk(group, cls, venue, seed)})
    for row in _OPTIONS:
        sym, name, price, vol, pip, spread, underlying = row
        uni[sym] = Instrument(sym, AssetClass.OPTIONS.value, name, "OPRA", price, pip, vol, pip,
                              spread, meta=dict(underlying=underlying, chain=True))
    return uni


UNIVERSE: Dict[str, Instrument] = build_universe()


def default_enabled() -> List[str]:
    """A sensible default hunt list — deep but not overwhelming."""
    syms = [s for s, *_ in _FOREX_MAJORS]
    syms += ["EURJPY", "GBPJPY", "AUDJPY", "GBPCHF", "USDMXN"]
    syms += ["AAPL", "NVDA", "MSFT", "TSLA", "META", "AMZN", "AMD", "JPM", "COIN"]
    syms += ["SPX", "NDX", "DAX", "N225"]
    syms += ["CL", "GC", "ES", "NQ", "VX"]
    syms += ["SPX-0DTE", "SPY-WEEKLY", "NVDA-WEEKLY"]
    syms += ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "LINKUSD"]
    return syms


def by_class(cls: str) -> List[Instrument]:
    return [i for i in UNIVERSE.values() if i.asset_class == cls]


def horizon_for(inst: Instrument, atr_pct: float) -> str:
    if inst.asset_class in (AssetClass.CRYPTO.value, AssetClass.OPTIONS.value):
        return "scalp" if atr_pct > 0.02 else "intraday"
    if inst.asset_class == AssetClass.FUTURES.value:
        return "intraday" if atr_pct > 0.01 else "swing"
    return "intraday" if atr_pct > 0.008 else "swing"


def sigma_per_step(inst: Instrument, seconds: float, bars_per_day: float = 288.0) -> float:
    """Per-step sigma for the synthetic tape (business-day scaling)."""
    per_bar = inst.vol / math.sqrt(252.0 * bars_per_day)
    return per_bar * math.sqrt(max(0.05, seconds))


def fx_legs(symbol: str):
    """(base, quote) currency legs of an FX symbol, or ("", "") if not FX."""
    majors = ("EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD",
              "SEK", "NOK", "MXN", "ZAR", "TRY", "SGD", "CNH")
    for cc in sorted(majors, key=len, reverse=True):
        if symbol.startswith(cc) and len(symbol) > len(cc):
            rest = symbol[len(cc):]
            if rest in majors:
                return cc, rest
    return "", ""

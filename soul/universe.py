"""The instrument book: every asset class the desk can be pointed at.

The scanner does not care what a symbol is — it reads candles and features. What
changes between asset classes is *where the candles come from* and *what a normal
bar looks like*:

* **crypto** streams from Binance's public endpoints (no key, no account) and
  falls back to the simulator when the venue is unreachable;
* **forex** is anchored on the keyless ECB/Frankfurter reference table -- one
  plain GET, no key and no account -- and simulated between fixes, so the level
  is real and the intraday motion is honestly ours;
* **indices, metals, stocks, futures, options** have no free keyless intraday
  feed wired in, so on those the desk is explicit: it runs on the simulator, and
  every badge in the UI says so (`market.source_of` follows the data, so a
  "rates" badge only appears when that fetch actually landed).

Anything selected here becomes the scanner's universe, the ticker on the wall,
and the set of desks people can be seated at. The roster is intentionally wider
than it is deep — this is a demonstration desk, not a brokerage — but every class
is wired to a real code path rather than a label.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Instrument:
    symbol: str          # the internal id, e.g. "BTC/USDT" or "EUR/USD"
    name: str            # human label, e.g. "Bitcoin / Tether"
    klass: str           # asset class key
    kind: str            # how bars are produced: venue | rates | sim
    base: float = 1.0    # simulator seed price
    beta: float = 1.0    # simulator beta to the crypto index / risk factor
    venue: Optional[str] = None      # venue symbol when kind == "venue"
    rate: Optional[str] = None       # rate pair when kind == "rates"
    vol_scale: float = 1.0           # how volatile a bar is vs a crypto bar


#: Bar volatility per asset class. A 0.4% bar is ordinary in crypto and a
#: once-a-month event in FX; without this the simulator would hand the council a
#: yen cross that moves 16% in a session and every cabin would rightly refuse it.
VOL_SCALE: Dict[str, float] = {
    "crypto": 1.0, "forex": 0.10, "indices": 0.55, "stocks": 0.85,
    "futures": 0.60, "options": 2.10, "metals": 0.45,
}

#: Every class the desk can be pointed at. `kind` is what the feed honours:
#: "venue" -> Binance public, "rates" -> ECB reference rates, "sim" -> simulator.
CLASSES: Dict[str, Dict[str, object]] = {
    "crypto": {
        "label": "Crypto",
        "source": "Binance public REST (keyless) → simulator fallback",
        "instrument": "spot pairs",
    },
    "forex": {
        "label": "Forex",
        "source": "ECB/Frankfurter reference rates (keyless) -- daily fix, intraday sim",
        "instrument": "spot FX majors, crosses and the EM board",
    },
    "indices": {
        "label": "Indices",
        "source": "simulated (no keyless index feed available)",
        "instrument": "index CFDs",
    },
    "stocks": {
        "label": "Stocks",
        "source": "simulated (no keyless equity feed available)",
        "instrument": "US large-cap equities",
    },
    "futures": {
        "label": "Futures",
        "source": "simulated (no keyless futures feed available)",
        "instrument": "front-month futures",
    },
    "options": {
        "label": "Options",
        "source": "simulated (no keyless options feed available)",
        "instrument": "vanilla calls and puts on the index",
    },
    "metals": {
        "label": "Metals",
        "source": "simulated (no keyless spot-metal feed wired)",
        "instrument": "spot metals",
    },
}

def _ins(symbol: str, name: str, klass: str, kind: str, base: float, beta: float,
         venue: Optional[str] = None, rate: Optional[str] = None) -> Instrument:
    return Instrument(symbol, name, klass, kind, base, beta, venue, rate,
                      VOL_SCALE.get(klass, 1.0))


INSTRUMENTS: List[Instrument] = [
    # ---- crypto ---------------------------------------------------------
    _ins("BTC/USDT", "Bitcoin / Tether", "crypto", "venue", 61000.0, 1.00, "BTC/USDT"),
    _ins("ETH/USDT", "Ether / Tether", "crypto", "venue", 3300.0, 1.05, "ETH/USDT"),
    _ins("SOL/USDT", "Solana / Tether", "crypto", "venue", 150.0, 1.35, "SOL/USDT"),
    _ins("BNB/USDT", "BNB / Tether", "crypto", "venue", 580.0, 1.10, "BNB/USDT"),
    _ins("XRP/USDT", "XRP / Tether", "crypto", "venue", 0.52, 1.20, "XRP/USDT"),
    _ins("ADA/USDT", "Cardano / Tether", "crypto", "venue", 0.45, 1.25, "ADA/USDT"),
    _ins("DOGE/USDT", "Dogecoin / Tether", "crypto", "venue", 0.12, 1.45, "DOGE/USDT"),
    _ins("AVAX/USDT", "Avalanche / Tether", "crypto", "venue", 28.0, 1.40, "AVAX/USDT"),
    _ins("LINK/USDT", "Chainlink / Tether", "crypto", "venue", 14.0, 1.30, "LINK/USDT"),
    _ins("DOT/USDT", "Polkadot / Tether", "crypto", "venue", 6.2, 1.30, "DOT/USDT"),
    _ins("TON/USDT", "Toncoin / Tether", "crypto", "venue", 6.8, 1.35, "TON/USDT"),
    _ins("NEAR/USDT", "NEAR / Tether", "crypto", "venue", 4.6, 1.40, "NEAR/USDT"),
    _ins("APT/USDT", "Aptos / Tether", "crypto", "venue", 8.9, 1.40, "APT/USDT"),
    _ins("ARB/USDT", "Arbitrum / Tether", "crypto", "venue", 1.15, 1.45, "ARB/USDT"),
    _ins("OP/USDT", "Optimism / Tether", "crypto", "venue", 1.75, 1.45, "OP/USDT"),
    _ins("INJ/USDT", "Injective / Tether", "crypto", "venue", 24.0, 1.55, "INJ/USDT"),
    _ins("SUI/USDT", "Sui / Tether", "crypto", "venue", 1.05, 1.50, "SUI/USDT"),
    _ins("TIA/USDT", "Celestia / Tether", "crypto", "venue", 5.6, 1.55, "TIA/USDT"),
    _ins("SEI/USDT", "Sei / Tether", "crypto", "venue", 0.42, 1.55, "SEI/USDT"),
    _ins("FET/USDT", "Artificial Superintelligence / Tether", "crypto", "venue", 1.45, 1.60, "FET/USDT"),
    _ins("RNDR/USDT", "Render / Tether", "crypto", "venue", 6.9, 1.55, "RNDR/USDT"),
    _ins("TAO/USDT", "Bittensor / Tether", "crypto", "venue", 380.0, 1.60, "TAO/USDT"),
    _ins("HYPE/USDT", "Hyperliquid / Tether", "crypto", "venue", 32.0, 1.60, "HYPE/USDT"),
    _ins("AAVE/USDT", "Aave / Tether", "crypto", "venue", 98.0, 1.35, "AAVE/USDT"),
    _ins("UNI/USDT", "Uniswap / Tether", "crypto", "venue", 7.7, 1.40, "UNI/USDT"),
    _ins("LTC/USDT", "Litecoin / Tether", "crypto", "venue", 84.0, 1.15, "LTC/USDT"),
    _ins("ETC/USDT", "Ethereum Classic / Tether", "crypto", "venue", 26.0, 1.25, "ETC/USDT"),
    _ins("XLM/USDT", "Stellar / Tether", "crypto", "venue", 0.11, 1.30, "XLM/USDT"),
    _ins("ALGO/USDT", "Algorand / Tether", "crypto", "venue", 0.16, 1.35, "ALGO/USDT"),
    _ins("HBAR/USDT", "Hedera / Tether", "crypto", "venue", 0.06, 1.35, "HBAR/USDT"),
    _ins("VET/USDT", "VeChain / Tether", "crypto", "venue", 0.024, 1.40, "VET/USDT"),
    _ins("ZEC/USDT", "Zcash / Tether", "crypto", "venue", 28.0, 1.30, "ZEC/USDT"),
    _ins("MATIC/USDT", "Polygon / Tether", "crypto", "venue", 0.55, 1.35, "MATIC/USDT"),
    _ins("FIL/USDT", "Filecoin / Tether", "crypto", "venue", 4.5, 1.45, "FIL/USDT"),
    _ins("ATOM/USDT", "Cosmos / Tether", "crypto", "venue", 8.2, 1.35, "ATOM/USDT"),
    _ins("PAXG/USDT", "PAX Gold / Tether", "crypto", "venue", 2400.0, 0.35, "PAXG/USDT"),

    # ---- forex (ECB reference rates, keyless) ---------------------------
    # `rate` is the pair the reference table can settle, always written
    # BASE-QUOTE: the client fetches the EUR table once and crosses any of
    # these off it. Everything here is a pair the desk can actually price.
    # majors
    _ins("EUR/USD", "Euro / US Dollar", "forex", "rates", 1.08, 0.35, rate="EUR-USD"),
    _ins("GBP/USD", "Pound / US Dollar", "forex", "rates", 1.27, 0.40, rate="GBP-USD"),
    _ins("USD/JPY", "US Dollar / Yen", "forex", "rates", 152.0, 0.45, rate="USD-JPY"),
    _ins("USD/CHF", "US Dollar / Franc", "forex", "rates", 0.88, 0.35, rate="USD-CHF"),
    _ins("AUD/USD", "Aussie / US Dollar", "forex", "rates", 0.66, 0.55, rate="AUD-USD"),
    _ins("USD/CAD", "US Dollar / Loonie", "forex", "rates", 1.36, 0.40, rate="USD-CAD"),
    _ins("NZD/USD", "Kiwi / US Dollar", "forex", "rates", 0.60, 0.55, rate="NZD-USD"),
    # crosses
    _ins("EUR/GBP", "Euro / Pound", "forex", "rates", 0.85, 0.30, rate="EUR-GBP"),
    _ins("EUR/JPY", "Euro / Yen", "forex", "rates", 164.0, 0.40, rate="EUR-JPY"),
    _ins("EUR/CHF", "Euro / Franc", "forex", "rates", 0.95, 0.30, rate="EUR-CHF"),
    _ins("EUR/AUD", "Euro / Aussie", "forex", "rates", 1.64, 0.50, rate="EUR-AUD"),
    _ins("EUR/CAD", "Euro / Loonie", "forex", "rates", 1.47, 0.45, rate="EUR-CAD"),
    _ins("EUR/NOK", "Euro / Krone", "forex", "rates", 11.60, 0.65, rate="EUR-NOK"),
    _ins("EUR/SEK", "Euro / Krona", "forex", "rates", 11.35, 0.60, rate="EUR-SEK"),
    _ins("EUR/PLN", "Euro / Zloty", "forex", "rates", 4.30, 0.70, rate="EUR-PLN"),
    _ins("GBP/JPY", "Pound / Yen", "forex", "rates", 193.0, 0.50, rate="GBP-JPY"),
    _ins("GBP/CHF", "Pound / Franc", "forex", "rates", 1.12, 0.40, rate="GBP-CHF"),
    _ins("AUD/JPY", "Aussie / Yen", "forex", "rates", 100.0, 0.55, rate="AUD-JPY"),
    _ins("AUD/NZD", "Aussie / Kiwi", "forex", "rates", 1.10, 0.35, rate="AUD-NZD"),
    _ins("CAD/JPY", "Loonie / Yen", "forex", "rates", 112.0, 0.50, rate="CAD-JPY"),
    _ins("CHF/JPY", "Franc / Yen", "forex", "rates", 172.0, 0.45, rate="CHF-JPY"),
    _ins("NZD/JPY", "Kiwi / Yen", "forex", "rates", 91.0, 0.55, rate="NZD-JPY"),
    # dollar bloc and the EM board
    _ins("USD/SEK", "US Dollar / Krona", "forex", "rates", 10.50, 0.60, rate="USD-SEK"),
    _ins("USD/NOK", "US Dollar / Krone", "forex", "rates", 10.80, 0.65, rate="USD-NOK"),
    _ins("USD/DKK", "US Dollar / Krone (DK)", "forex", "rates", 6.85, 0.40, rate="USD-DKK"),
    _ins("USD/PLN", "US Dollar / Zloty", "forex", "rates", 3.98, 0.70, rate="USD-PLN"),
    _ins("USD/CZK", "US Dollar / Koruna", "forex", "rates", 23.30, 0.70, rate="USD-CZK"),
    _ins("USD/HUF", "US Dollar / Forint", "forex", "rates", 360.0, 0.75, rate="USD-HUF"),
    _ins("USD/INR", "US Dollar / Rupee", "forex", "rates", 83.50, 0.35, rate="USD-INR"),
    _ins("USD/CNY", "US Dollar / Yuan", "forex", "rates", 7.25, 0.25, rate="USD-CNY"),
    _ins("USD/SGD", "US Dollar / Singapore Dollar", "forex", "rates", 1.35, 0.30, rate="USD-SGD"),
    _ins("USD/HKD", "US Dollar / Hong Kong Dollar", "forex", "rates", 7.81, 0.15, rate="USD-HKD"),
    _ins("USD/KRW", "US Dollar / Won", "forex", "rates", 1340.0, 0.55, rate="USD-KRW"),
    _ins("USD/MXN", "US Dollar / Peso", "forex", "rates", 17.10, 0.80, rate="USD-MXN"),
    _ins("USD/ZAR", "US Dollar / Rand", "forex", "rates", 18.60, 0.90, rate="USD-ZAR"),
    _ins("USD/TRY", "US Dollar / Lira", "forex", "rates", 32.50, 0.95, rate="USD-TRY"),
    _ins("USD/BRL", "US Dollar / Real", "forex", "rates", 5.05, 0.85, rate="USD-BRL"),

    # ---- metals ----------------------------------------------------------
    # No keyless spot-metal feed is wired, so these are simulated and say so.
    _ins("XAU/USD", "Gold / US Dollar", "metals", "sim", 2400.0, 0.30),
    _ins("XAG/USD", "Silver / US Dollar", "metals", "sim", 28.0, 0.45),

    # ---- indices ---------------------------------------------------------
    _ins("SPX500", "S&P 500", "indices", "sim", 5400.0, 0.85),
    _ins("NAS100", "Nasdaq 100", "indices", "sim", 18800.0, 1.05),
    _ins("US30", "Dow Jones 30", "indices", "sim", 39500.0, 0.70),
    _ins("GER40", "DAX 40", "indices", "sim", 18300.0, 0.80),
    _ins("UK100", "FTSE 100", "indices", "sim", 8200.0, 0.65),
    _ins("NIKKEI225", "Nikkei 225", "indices", "sim", 38500.0, 0.75),
    _ins("VIX", "Volatility Index", "indices", "sim", 15.4, -1.90),
    _ins("CAC40", "CAC 40", "indices", "sim", 7600.0, 0.80),
    _ins("HSI", "Hang Seng", "indices", "sim", 17400.0, 0.95),
    _ins("ASX200", "S&P/ASX 200", "indices", "sim", 7900.0, 0.60),

    # ---- stocks ----------------------------------------------------------
    _ins("AAPL", "Apple", "stocks", "sim", 228.0, 0.95),
    _ins("MSFT", "Microsoft", "stocks", "sim", 425.0, 0.95),
    _ins("NVDA", "NVIDIA", "stocks", "sim", 118.0, 1.60),
    _ins("AMZN", "Amazon", "stocks", "sim", 186.0, 1.10),
    _ins("GOOGL", "Alphabet", "stocks", "sim", 168.0, 1.00),
    _ins("META", "Meta Platforms", "stocks", "sim", 505.0, 1.20),
    _ins("TSLA", "Tesla", "stocks", "sim", 245.0, 1.70),
    _ins("AMD", "Advanced Micro Devices", "stocks", "sim", 162.0, 1.55),
    _ins("JPM", "JPMorgan Chase", "stocks", "sim", 214.0, 0.80),
    _ins("XOM", "Exxon Mobil", "stocks", "sim", 118.0, 0.55),
    _ins("NFLX", "Netflix", "stocks", "sim", 690.0, 1.25),
    _ins("AVGO", "Broadcom", "stocks", "sim", 172.0, 1.35),
    _ins("ORCL", "Oracle", "stocks", "sim", 168.0, 1.05),
    _ins("CRM", "Salesforce", "stocks", "sim", 265.0, 1.10),
    _ins("COST", "Costco", "stocks", "sim", 890.0, 0.60),
    _ins("KO", "Coca-Cola", "stocks", "sim", 71.0, 0.45),
    _ins("DIS", "Walt Disney", "stocks", "sim", 95.0, 1.10),
    _ins("BA", "Boeing", "stocks", "sim", 152.0, 1.25),
    _ins("PFE", "Pfizer", "stocks", "sim", 29.0, 0.75),
    _ins("INTC", "Intel", "stocks", "sim", 21.0, 1.40),

    # ---- futures ---------------------------------------------------------
    _ins("ES1!", "E-mini S&P 500 (front)", "futures", "sim", 5405.0, 0.85),
    _ins("NQ1!", "E-mini Nasdaq (front)", "futures", "sim", 18850.0, 1.05),
    _ins("CL1!", "WTI Crude (front)", "futures", "sim", 78.0, 0.60),
    _ins("NG1!", "Natural Gas (front)", "futures", "sim", 2.6, 0.90),
    _ins("GC1!", "Gold (front)", "futures", "sim", 2410.0, 0.30),
    _ins("SI1!", "Silver (front)", "futures", "sim", 28.2, 0.45),
    _ins("ZB1!", "30Y Treasury Bond (front)", "futures", "sim", 121.0, -0.25),
    _ins("ZN1!", "10Y Treasury Note (front)", "futures", "sim", 114.5, -0.20),
    _ins("BZ1!", "Brent Crude (front)", "futures", "sim", 82.0, 0.65),
    _ins("HG1!", "Copper (front)", "futures", "sim", 4.35, 0.85),
    _ins("6E1!", "Euro FX (front)", "futures", "sim", 1.085, 0.35),

    # ---- options (vanilla, on the index) --------------------------------
    _ins("SPX-C5400", "S&P 500 call 5400 (30d)", "options", "sim", 62.0, 1.20),
    _ins("SPX-P5200", "S&P 500 put 5200 (30d)", "options", "sim", 38.0, -1.30),
    _ins("NVDA-C120", "NVIDIA call 120 (30d)", "options", "sim", 5.4, 1.80),
    _ins("TSLA-P240", "Tesla put 240 (30d)", "options", "sim", 7.9, -1.60),
    _ins("SPX-P5400", "S&P 500 put 5400 (30d)", "options", "sim", 54.0, -1.25),
    _ins("AAPL-C240", "Apple call 240 (30d)", "options", "sim", 6.2, 1.55),
    _ins("NVDA-P110", "NVIDIA put 110 (30d)", "options", "sim", 4.1, -1.70),
    _ins("QQQ-C480", "Nasdaq 100 ETF call 480 (30d)", "options", "sim", 9.3, 1.40),
]

BY_SYMBOL: Dict[str, Instrument] = {i.symbol: i for i in INSTRUMENTS}

#: What the desk trades out of the box: liquid crypto majors and high-beta alts.
DEFAULT_SELECTION: List[str] = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "TON/USDT", "NEAR/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "INJ/USDT", "SUI/USDT", "TIA/USDT", "SEI/USDT", "FET/USDT",
    "RNDR/USDT", "TAO/USDT", "HYPE/USDT", "AAVE/USDT", "UNI/USDT", "LTC/USDT",
    "ETC/USDT", "XLM/USDT", "ALGO/USDT", "HBAR/USDT", "VET/USDT", "ZEC/USDT",
    "MATIC/USDT", "FIL/USDT", "ATOM/USDT", "PAXG/USDT", "DOGE/USDT", "DOT/USDT",
]


def catalogue(source_of=None) -> Dict[str, object]:
    """Everything the settings panel needs to draw the instrument book.

    `source_of` (usually `MarketFeed.source_of`) turns each instrument's declared
    kind into the source it is *actually* running on right now, so a panel can
    never promise a feed the desk is not reading.
    """
    classes = []
    for key, meta in CLASSES.items():
        members = [i for i in INSTRUMENTS if i.klass == key]
        classes.append({
            "key": key,
            "label": meta["label"],
            "source": meta["source"],
            "instrument": meta["instrument"],
            "count": len(members),
            "symbols": [
                {"symbol": i.symbol, "name": i.name, "kind": i.kind,
                 "live": (source_of(i.symbol) if source_of else i.kind),
                 "venue": i.venue, "rate": i.rate}
                for i in sorted(members, key=lambda x: x.symbol)
            ],
        })
    return {
        "classes": classes,
        "default": list(DEFAULT_SELECTION),
        "total": len(INSTRUMENTS),
    }


def resolve(symbols: List[str]) -> List[str]:
    """Keep only symbols this desk knows, in catalogue order."""
    known = set(BY_SYMBOL)
    ordered = [i.symbol for i in INSTRUMENTS if i.symbol in set(symbols) & known]
    return ordered or list(DEFAULT_SELECTION)


def instrument(symbol: str) -> Instrument:
    return BY_SYMBOL.get(symbol, Instrument(symbol, symbol, "crypto", "sim"))


def classes_of(symbols: List[str]) -> List[str]:
    seen: List[str] = []
    for s in symbols:
        k = instrument(s).klass
        if k not in seen:
            seen.append(k)
    return seen

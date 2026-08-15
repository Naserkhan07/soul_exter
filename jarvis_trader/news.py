"""
Open-source news scraping + lightweight financial sentiment.

Sources (all free / RSS / public JSON) - full list requested:
  - Yahoo Finance RSS          - CNBC RSS (Markets+Finance) - MarketWatch RSS
  - Investing.com RSS          - Nasdaq RSS                 - Bloomberg (via Google News RSS)
  - NSE India news (via Google News + Economic Times NSE feed)
  - BSE / Sensex news (via Google News + Business Standard) - Koyfin (via Google News)
  - StockAnalysis.com (via Google News)                     - Moneycontrol RSS
  - LiveMint Markets RSS       - CoinDesk / CoinTelegraph RSS
  - ForexFactory calendar (ff JSON mirror)                  - Economic Times markets RSS
  - Google News RSS aggregate market query

Sites with no public RSS (Bloomberg, Koyfin, StockAnalysis, NSE, BSE) are
scraped through Google News RSS `site:` / topic queries - free and unlimited.

Every headline is scored with a finance-tuned keyword sentiment model
(-1..+1). Per-asset relevance is matched by symbol/name keywords.
"""
import re
import time
import threading

import requests

try:
    import feedparser
except ImportError:
    feedparser = None

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) JarvisTrader/1.0"}
TIMEOUT = 8


def _gnews(q):
    """Google News RSS query URL (free scrape route for sites without RSS)."""
    return ("https://news.google.com/rss/search?q=" + q.replace(" ", "+") +
            "+when:1d&hl=en-US&gl=US&ceid=US:en")


FEEDS = [
    ("Yahoo Finance",   "https://finance.yahoo.com/news/rssindex"),
    ("CNBC Markets",    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("CNBC Finance",    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
    ("MarketWatch",     "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Investing.com",   "https://www.investing.com/rss/news.rss"),
    ("Nasdaq",          "https://www.nasdaq.com/feed/rssoutbound?category=Markets"),
    ("Bloomberg",       _gnews("site:bloomberg.com markets")),
    ("NSE India",       _gnews("NSE nifty india stock market")),
    ("NSE-ET Feed",     "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("BSE Sensex",      _gnews("BSE sensex india shares")),
    ("Koyfin",          _gnews("site:koyfin.com OR koyfin markets")),
    ("StockAnalysis",   _gnews("site:stockanalysis.com OR stock analysis earnings")),
    ("Moneycontrol",    "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("LiveMint",        "https://www.livemint.com/rss/markets"),
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",   "https://cointelegraph.com/rss"),
    ("EconomicTimes",   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("GoogleNews Mkts", _gnews("markets")),
]

FF_CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

BULLISH = {
    "surge": 3, "soar": 3, "rally": 3, "jump": 2, "gain": 2, "rise": 2, "climb": 2,
    "record high": 3, "all-time high": 3, "beat": 2, "beats": 2, "upgrade": 2,
    "bullish": 3, "buy": 1, "strong": 1, "growth": 1, "profit": 1, "outperform": 2,
    "rebound": 2, "recover": 2, "boom": 2, "optimis": 2, "breakout": 2, "top estimates": 3,
    "rate cut": 2, "stimulus": 2, "dovish": 2, "approval": 1, "adoption": 2, "etf inflow": 3,
}
BEARISH = {
    "plunge": -3, "crash": -4, "tumble": -3, "sink": -3, "slump": -3, "fall": -2,
    "drop": -2, "decline": -2, "slide": -2, "miss": -2, "misses": -2, "downgrade": -2,
    "bearish": -3, "sell-off": -3, "selloff": -3, "fear": -2, "panic": -3, "recession": -3,
    "inflation": -1, "lawsuit": -2, "probe": -1, "fraud": -3, "hack": -3, "bankrupt": -4,
    "layoff": -2, "warning": -2, "weak": -1, "loss": -1, "rate hike": -2, "hawkish": -2,
    "tariff": -1, "sanction": -1, "default": -3, "liquidation": -3, "etf outflow": -3,
}

ASSET_KEYWORDS = {
    "BTCUSDT": ["bitcoin", "btc", "crypto"],
    "ETHUSDT": ["ethereum", "eth ", "crypto"],
    "SOLUSDT": ["solana", "sol ", "crypto"],
    "AAPL": ["apple", "aapl", "iphone"],
    "TSLA": ["tesla", "tsla", "musk"],
    "NVDA": ["nvidia", "nvda", "ai chip"],
    "RELIANCE": ["reliance", "ambani", "nse", "sensex", "nifty"],
    "EURUSD": ["euro", "ecb", "eur/usd", "dollar", "fed "],
    "GBPUSD": ["pound", "sterling", "boe", "gbp"],
    "USDJPY": ["yen", "boj", "japan", "usd/jpy"],
    "XAUUSD": ["gold", "bullion", "xau"],
    "SPX": ["s&p", "sp500", "s&p 500", "wall street", "stocks"],
    "NIFTY50": ["nifty", "sensex", "indian market", "nse", "rbi"],
    "NDX": ["nasdaq", "tech stocks"],
    "CL=F": ["oil", "crude", "opec", "wti", "brent"],
    "SPY": ["s&p", "spy etf", "wall street", "stocks"],
}


def sentiment_score(text):
    t = text.lower()
    s = 0.0
    for w, v in BULLISH.items():
        if w in t:
            s += v
    for w, v in BEARISH.items():
        if w in t:
            s += v
    return max(-1.0, min(1.0, s / 6.0))


def _apply_finbert(items):
    """Upgrade keyword sentiment with FinBERT (HF finance model) when
    available. Falls back silently to keyword scores."""
    try:
        from . import hf_models
        if not hf_models.finbert_available():
            return items
        titles = [it["title"] for it in items]
        scores = hf_models.finbert_sentiment(titles)
        if scores:
            for it, s in zip(items, scores):
                # blend: FinBERT dominates (it reads sentences), keywords
                # keep a say (they catch finance slang FinBERT may miss)
                it["sentiment"] = round(0.75 * s + 0.25 * it["sentiment"], 3)
                it["scored_by"] = "finbert"
    except Exception:
        pass
    return items


class NewsEngine:
    def __init__(self):
        self.headlines = []          # [{title, source, link, ts, sentiment}]
        self.calendar = []           # forexfactory events
        self.last_fetch = 0
        self.lock = threading.RLock()   # re-entrant: nested reads can't deadlock
        self.sources_ok = []
        self.sources_fail = []

    # ---------------------------------------------------------------- #
    def _fetch_feed(self, name, url):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            items = []
            if feedparser:
                fp = feedparser.parse(r.content)
                for e in fp.entries[:25]:
                    title = getattr(e, "title", "").strip()
                    if not title:
                        continue
                    # Google News appends " - Publisher"; strip it for clean text
                    if "news.google.com" in url and " - " in title:
                        title = title.rsplit(" - ", 1)[0].strip()
                    items.append({
                        "title": title,
                        "source": name,
                        "link": getattr(e, "link", ""),
                        "ts": time.time(),
                        "sentiment": round(sentiment_score(title), 3),
                    })
            else:
                for m in re.finditer(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                                     r.text)[1:26]:
                    title = m.group(1).strip()
                    items.append({"title": title, "source": name, "link": "",
                                  "ts": time.time(),
                                  "sentiment": round(sentiment_score(title), 3)})
            return items
        except Exception:
            return None

    def _fetch_calendar(self):
        try:
            r = requests.get(FF_CALENDAR, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            evts = r.json()
            out = []
            for e in evts:
                out.append({"title": e.get("title"), "country": e.get("country"),
                            "impact": e.get("impact"), "date": e.get("date"),
                            "forecast": e.get("forecast"), "previous": e.get("previous")})
            return out
        except Exception:
            return None

    # ---------------------------------------------------------------- #
    def refresh(self, force=False):
        with self.lock:
            if not force and time.time() - self.last_fetch < 180:
                return
            self.last_fetch = time.time()

        # fetch all sources in parallel so 19 feeds take ~1 timeout, not 19
        all_items, ok, fail = [], [], []
        results = {}

        def worker(name, url):
            results[name] = self._fetch_feed(name, url)

        threads = [threading.Thread(target=worker, args=(n, u), daemon=True)
                   for n, u in FEEDS]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=TIMEOUT + 4)
        for name, _ in FEEDS:
            items = results.get(name)
            if items:
                all_items.extend(items)
                ok.append(name)
            else:
                fail.append(name)

        cal = self._fetch_calendar()
        # dedupe + FinBERT scoring OUTSIDE the lock (model inference is slow)
        scored = None
        if all_items:
            seen = set()
            dedup = []
            for it in all_items:
                k = it["title"][:80].lower()
                if k in seen:
                    continue
                seen.add(k)
                dedup.append(it)
            scored = _apply_finbert(dedup[:400])
        with self.lock:
            if scored is not None:
                self.headlines = scored
            if cal is not None:
                self.calendar = cal
                ok.append("ForexFactory-Calendar")
            else:
                fail.append("ForexFactory-Calendar")
            self.sources_ok, self.sources_fail = ok, fail

    # ---------------------------------------------------------------- #
    def asset_news(self, symbol, limit=8):
        kws = ASSET_KEYWORDS.get(symbol, [symbol.lower()])
        with self.lock:
            rel = [h for h in self.headlines
                   if any(k in h["title"].lower() for k in kws)]
            general = [h for h in self.headlines if h not in rel]
        return (rel + general)[:limit], len(rel)

    def asset_sentiment(self, symbol):
        """Returns (score -100..100, n_relevant, sample_titles)."""
        rel, n_rel = self.asset_news(symbol, limit=12)
        if not rel:
            return 0.0, 0, []
        weights = []
        for i, h in enumerate(rel):
            w = 2.0 if n_rel and i < n_rel else 0.5   # relevant headlines weigh 4x general
            weights.append((h["sentiment"], w))
        num = sum(s * w for s, w in weights)
        den = sum(w for _, w in weights)
        score = 100 * num / den if den else 0
        titles = [h["title"] for h in rel[:5]]
        return round(max(-100, min(100, score * 2)), 1), n_rel, titles

    def high_impact_soon(self, currency=None):
        out = []
        with self.lock:
            for e in self.calendar:
                if (e.get("impact") or "").lower() == "high":
                    if currency and e.get("country") != currency:
                        continue
                    out.append(e)
        return out[:10]


ENGINE = NewsEngine()

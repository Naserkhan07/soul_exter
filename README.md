# J.A.R.V.I.S TRADER

AI-powered multi-market trading bot: **live tracking of crypto, stocks, forex, futures, indices and funds**, auto trade placement with **auto TP / SL / breakeven / ATR trailing**, open-source **news scraping + sentiment**, technical **indicators + strategies**, and an **AI Council** (Jarvis ML brain + Gemini + Groq) that votes on every asset. Jarvis **auto-trains itself** — first on a built-in trading knowledge base + historical candles, then continuously on every closed trade.

## Quick start

```bash
pip install -r requirements.txt
python run.py
# open http://localhost:8000
```

API keys live in `.env` (Gemini + Groq already filled in; add Alpha Vantage / Twelve Data / Polygon keys for extra data sources).

## How it works

```
                        ┌──────────────────────────┐
   Live data feeds ───► │        AI COUNCIL        │
   (Binance, Yahoo,     │  ─ Indicators  (vote)    │
    Stooq, OKX, Kraken, │  ─ Strategies  (vote)    │      Auto-trader
    Coinbase, TwelveData│  ─ News sent.  (vote)    │ ───► entry + TP + SL
    AlphaVantage...)    │  ─ JARVIS ML   (vote)    │      breakeven @1R
                        │  ─ Gemini      (vote)    │      ATR trailing
   News scraping ─────► │  ─ Groq        (vote)    │            │
   (Yahoo, CNBC,        └──────────────────────────┘            ▼
    MarketWatch,                 ▲                       closed trades feed
    Investing.com,               └────── self-training ── back into JARVIS
    Nasdaq, CoinDesk,
    ForexFactory cal,
    EconomicTimes...)
```

- **Ask the Council**: pick any asset in the dashboard and press *ASK THE COUNCIL* — it asks Gemini, Groq and Jarvis in detail "will this go up or down", collects a −100..+100 score from **every** member (indicators, strategies, news, Jarvis, Gemini, Groq) and shows the weighted verdict + trade plan.
- **Auto-trade**: when confidence ≥ threshold it places a paper trade with ATR-based TP (2R) and SL (1.5×ATR), moves SL to breakeven at +1R and trails with ATR after +1.5R.
- **Jarvis auto-training**:
  1. Boots with a built-in knowledge base (market structure, indicators, strategies, risk management, market movement causes) encoded as model priors and injected into every LLM prompt.
  2. Bootstrap-trains on historical candles of the whole watchlist ("did price rise N bars later?").
  3. Learns online from every closed trade — its brain is persisted in `data_store/jarvis_brain.json`.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | dashboard |
| `GET /api/market` | live quotes, all assets |
| `POST /api/analyze/{symbol}` | full AI-council analysis |
| `GET /api/news` | scraped headlines + high-impact economic calendar |
| `GET /api/status` | balance, equity, positions, Jarvis stats |
| `POST /api/settings` | auto_trade / min_confidence / risk_pct |
| `GET /mt5/commands` | MT5 EA polls this for live orders |
| `POST /webhook/tradingview` | TradingView alerts push here |

## Going live

- **MT5 (forex)**: compile `mt5_bridge/JarvisBridge.mq5` in MetaEditor on the Windows machine where MT5 runs with *your* login — the EA polls the bot for signals and places real orders with TP/SL. Set `EnableLive=true` only when ready. Your MT5 password never touches the bot.
- **TradingView**: point your alert webhooks at `/webhook/tradingview`, or read signals from `/mt5/commands` with any executor.

## ⚠️ Notes

- If real market APIs are unreachable (e.g. sandboxed network) feeds fall back to a clearly-labeled **SIMULATED** random walk so everything still runs — run locally for true live data.
- Paper trading by default. Live trading is real financial risk — nothing here is financial advice.

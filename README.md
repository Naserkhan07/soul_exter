# J.A.R.V.I.S TRADER

AI-powered multi-market trading bot: **live tracking of crypto, stocks, forex, futures, indices and funds**, auto trade placement with **auto TP / SL / breakeven / ATR trailing**, open-source **news scraping + sentiment**, technical **indicators + strategies**, and an **AI Council** (Jarvis ML brain + Gemini + Groq) that votes on every asset. Jarvis **auto-trains itself** — first on a built-in trading knowledge base + historical candles, then continuously on every closed trade.

## Quick start

```bash
pip install -r requirements.txt
python run.py
# open http://localhost:8000
```

API keys live in `.env` (Gemini + Groq only — all market data comes from free, unlimited sources: Binance, OKX, Kraken, Coinbase, Yahoo Finance, Stooq).

## How it works

```
                        ┌──────────────────────────┐
   Live data feeds ───► │        AI COUNCIL        │
   (Binance, Yahoo,     │  ─ Indicators  (vote)    │
    Stooq, OKX, Kraken, │  ─ Strategies  (vote)    │      Auto-trader
    Coinbase - all free │  ─ Patterns    (vote)    │ ───► entry + TP + SL
    unlimited sources)  │  ─ News sent.  (vote)    │      breakeven @1R
                        │  ─ JARVIS ML   (vote)    │
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
- **Signals → click to place**: every setup the bot finds (confidence ≥ threshold) is published in the **Scanned Trade Signals** panel with side, entry, TP, SL, R:R and the top reasons. Nothing is placed until **you click PLACE** (signals stay clickable for `SIGNAL_TTL_SEC`, default 15 min, and execute at the live price with drift-adjusted TP/SL). Flip `AUTO_TRADE=true` in `.env` (or the dashboard toggle) and the bot places them itself.
- **Trade management**: ATR-based TP/SL at order time, SL→breakeven at +1R, ATR trailing after +1.5R, and a **timeout exit** (`MAX_TRADE_HOLD_SEC`, default 4h) if neither TP nor SL is hit. When a valid A-B-C-D projection agrees with the verdict, the **D level is used as the take-profit target**.
- **Trade journal**: every closed trade is written to `data_store/trade_journal.json` and shown in the dashboard's journal table — outcome (WIN/LOSS), entry & exit price, TP, SL, PnL, R-multiple, hold time, **why it closed** (TP hit / SL hit / breakeven stop / timeout / manual) and **why it was entered** (member votes + reasons at entry). Click any row to expand the full story.
- **Live pattern recognition** (`patterns.py`) — a dedicated council member scans every asset's live chart for **~50 candlestick + chart patterns**:
  - *Candlestick*: Hammer, Inverted Hammer, Hanging Man, Shooting Star, Doji / Gravestone / Dragonfly, Bullish & Bearish Engulfing, Piercing Line, Dark Cloud Cover, Morning/Evening Star (+ Doji Star variants), Three White Soldiers, Three Black Crows, Harami & Harami Cross, Inside Bars, Tweezer Top/Bottom, Bullish/Bearish Kicker, Rising/Falling Windows (gaps), Upside/Downside Tasuki Gap, Side-by-Side White Lines, Rising/Falling Three Methods, Separating Lines.
  - *Chart*: Double & Triple Top/Bottom, Head & Shoulders + Inverse, Rising/Falling Wedge, Ascending/Descending/Symmetrical Triangle, Bullish/Bearish Flag & Pennant, Rectangles, Cup & Handle, Rounding Bottom, Broadening Formation, Diamond Top/Bottom.
  - Each hit carries direction, strength (−100..+100), recency, and a note; the aggregate becomes the **PATTERNS vote** in the council, the detected list is shown in the dashboard, and every detected structure is described to Gemini & Groq in their prompts.
- **Strategies tracked live** on every asset: Trend Following (EMA stack + ADX), Mean Reversion (RSI + Bollinger), Momentum Breakout (Donchian + volume), MACD Cross, VWAP Pullback, and the **A-B-C → D price projection**:
  - swing detector finds pivots A (start swing), B (major swing), C (pullback);
  - projects `D = (B × C) ÷ A` as a reaction/target level (Gann/Fibonacci style);
  - the level alone is *not* an automatic signal — it votes toward D as a magnet while price travels, goes neutral ("wait & watch") when price reaches D, and the council + confirmation decide the trade.
- **Jarvis auto-training** (3 layers):
  1. Boots with a built-in knowledge base (market structure, indicators, strategies incl. A-B-C-D, risk management, market movement causes) encoded as model priors and injected into every LLM prompt.
  2. Bootstrap-trains on historical candles of the whole watchlist across **multiple timeframes (5m + 15m) and horizons** ("did price rise N bars later?").
  3. **Live-lesson loop**: every council prediction is registered and re-checked against the real market ~30 min later — Jarvis trains on what actually happened, even when no trade was placed. Closed trades feed back too. Brain persisted in `data_store/jarvis_brain.json`.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | dashboard |
| `GET /api/market` | live quotes, all assets |
| `POST /api/analyze/{symbol}` | full AI-council analysis |
| `GET /api/news` | scraped headlines + high-impact economic calendar |
| `GET /api/signals` | every trade setup scanned from the live market (click-to-place) |
| `POST /api/place/{symbol}` | place a scanned signal — used by the PLACE button |
| `GET /api/journal` | closed-trade journal: entry/TP/SL/exit, why it closed, stats |
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

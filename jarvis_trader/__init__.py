"""
JARVIS TRADER - AI-powered multi-market trading bot.

Modules:
  config      - environment / settings
  feeds       - live market data (crypto, stocks, forex, futures, indices, funds)
  news        - open-source news scraping + sentiment
  indicators  - technical indicators (RSI, MACD, EMA, BB, ATR, ADX, Stoch, VWAP...)
  strategies  - rule-based strategies producing directional scores
  knowledge   - Jarvis's built-in trading knowledge base
  jarvis      - Jarvis ML brain (online self-training on trade outcomes)
  council     - AI council (Jarvis + Gemini + Groq + indicators + strategies + news)
  trader      - execution engine: auto entries, auto TP/SL, trailing, paper broker
  server      - FastAPI dashboard + REST API + TradingView/MT5 bridge endpoints
"""
__version__ = "1.0.0"

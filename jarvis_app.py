"""
J.A.R.V.I.S - Streamlit control center.

This IS Jarvis: you watch him analyze, track live markets, find trades,
and you operate everything from here (place trades, close positions,
change settings, read his journal and live activity narration).

The trading engine runs inside this process - no separate server needed.
Launch:  streamlit run jarvis_app.py     (or just: python run.py)
"""
import time
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="J.A.R.V.I.S TRADER", page_icon="🤖",
                   layout="wide", initial_sidebar_state="expanded")

# ------------------------------------------------------------------ #
#  Boot the engine ONCE (Streamlit reruns the script on every action)
# ------------------------------------------------------------------ #
@st.cache_resource
def boot_engine():
    from jarvis_trader import trader
    trader.ENGINE.start()
    return trader.ENGINE

ENGINE = boot_engine()

from jarvis_trader import config, council, news, jarvis, indicators  # noqa: E402

# ------------------------------------------------------------------ #
#  Styling - JARVIS holo look
# ------------------------------------------------------------------ #
st.markdown("""
<style>
.stApp {background: radial-gradient(ellipse at top, #0b1526 0%, #06090f 60%);} 
h1,h2,h3 {color:#37c8f5 !important; letter-spacing:1px;}
[data-testid="stMetricValue"] {color:#d7e3f4;}
[data-testid="stSidebar"] {background:#0a111f;}
.block-container {padding-top:1.2rem;}
div[data-testid="stExpander"] {background:#0c1220; border:1px solid #1c2a44; border-radius:10px;}
.up {color:#22d37e;} .down {color:#ff4d67;}
.jarvis-say {background:#0b2d46; border-left:3px solid #37c8f5; padding:8px 14px;
  border-radius:6px; color:#bfe6f7; font-size:15px; margin-bottom:10px;}
.act-track{color:#5f7290}.act-analyze{color:#37c8f5}.act-signal{color:#f5b83d}
.act-trade{color:#22d37e}.act-jarvis{color:#a78bfa}.act-news{color:#e8853d}.act-skip{color:#e05555}
.small {color:#5f7290; font-size:12px;}
</style>
""", unsafe_allow_html=True)


def fmt(x, d=5):
    if x is None:
        return "--"
    return f"{x:,.{d}g}" if abs(x) >= 1 else f"{x:.6g}"


def jarvis_speaks():
    """Jarvis narrates his current state like the real one."""
    s = ENGINE.status()
    j = s["jarvis"]
    open_markets = sum(1 for m in ENGINE.market.values() if m.get("market_open"))
    if j["bootstrapping"]:
        return "Good day. I am training myself on historical market data before we begin…"
    parts = [f"All systems online. Tracking {len(config.WATCHLIST)} assets, "
             f"{open_markets} markets currently open."]
    if s["signals_waiting"]:
        parts.append(f"I have {s['signals_waiting']} trade setup"
                     f"{'s' if s['signals_waiting'] > 1 else ''} awaiting your authorization.")
    if s["open_positions"]:
        pnl = sum(p['pnl'] for p in s['open_positions'])
        parts.append(f"Managing {len(s['open_positions'])} open position"
                     f"{'s' if len(s['open_positions']) > 1 else ''} "
                     f"({'+' if pnl >= 0 else ''}{pnl:.2f} unrealized).")
    parts.append(f"My brain holds {j['samples_trained']} training samples"
                 + (f" with {j['accuracy']}% live accuracy." if j.get("accuracy") is not None
                    else "; live accuracy pending first outcomes."))
    return " ".join(parts)


# ================================================================== #
#  SIDEBAR - Jarvis controls
# ================================================================== #
with st.sidebar:
    st.markdown("## 🤖 J.A.R.V.I.S")
    st.caption("Just A Rather Very Intelligent System — Trading Division")
    s = ENGINE.status()

    st.metric("Balance", f"${s['balance']:,.2f}")
    delta = round(s["equity"] - s["balance"], 2)
    st.metric("Equity", f"${s['equity']:,.2f}", delta=f"{delta:+,.2f}")

    st.divider()
    st.markdown("### ⚙️ Controls")
    auto = st.toggle("Auto-trade (Jarvis places by himself)", value=s["auto_trade"])
    if auto != s["auto_trade"]:
        ENGINE.auto_trade = auto
        ENGINE.log(f"Settings updated: auto_trade={auto}")
    min_conf = st.slider("Min confidence to signal %", 0, 100, int(s["min_confidence"]), 5)
    if min_conf != s["min_confidence"]:
        ENGINE.min_conf = float(min_conf)
    risk = st.slider("Risk per trade %", 0.1, 5.0, float(s["risk_pct"]), 0.1)
    if risk != s["risk_pct"]:
        ENGINE.risk_pct = float(risk)

    st.divider()
    st.markdown("### 🧠 Jarvis brain")
    j = s["jarvis"]
    st.write(f"Samples trained: **{j['samples_trained']}**")
    st.write(f"Live lessons: **{j.get('live_lessons', 0)}** "
             f"(+{j.get('pending_predictions', 0)} pending)")
    st.write(f"Trade feedbacks: **{j['live_feedback']}**")
    st.write(f"Live accuracy: **{j['accuracy'] if j['accuracy'] is not None else '—'}%**"
             if j['accuracy'] is not None else "Live accuracy: **—**")
    llm = s.get("llm_status", {})
    st.caption(f"Gemini: {llm.get('gemini', '?')} · Groq: {llm.get('groq', '?')}")

    st.divider()
    auto_refresh = st.toggle("Live auto-refresh", value=True)
    if st.button("🔄 Refresh now", use_container_width=True):
        st.rerun()

# ================================================================== #
#  HEADER - Jarvis speaks
# ================================================================== #
st.markdown("# J.A.R.V.I.S <span style='color:#f5b83d'>TRADER</span>",
            unsafe_allow_html=True)
st.markdown(f"<div class='jarvis-say'>🎙️ “{jarvis_speaks()}”</div>",
            unsafe_allow_html=True)

tab_live, tab_signals, tab_council, tab_positions, tab_journal, tab_activity, tab_news = \
    st.tabs(["📡 Live Markets", "⚡ Trade Signals", "🧠 AI Council",
             "📈 Positions", "📕 Journal", "🤖 Jarvis Activity", "📰 News"])

# ================================================================== #
#  TAB: LIVE MARKETS
# ================================================================== #
with tab_live:
    market = list(ENGINE.market.values())
    if not market:
        st.info("Jarvis is connecting to the market feeds… give him a few seconds.")
    else:
        sim = any(m["source"] == "SIMULATED" for m in market)
        if sim:
            st.warning("⚠️ Some feeds are SIMULATED (market APIs unreachable from this "
                       "network). On your PC with internet, live data connects automatically.")
        cols = st.columns(4)
        analysis = dict(ENGINE.last_analysis)
        for i, m in enumerate(sorted(market, key=lambda x: (x["type"], x["symbol"]))):
            with cols[i % 4]:
                a = analysis.get(m["symbol"])
                v = a["verdict"] if a else None
                arrow = "🟢" if m["tick"] == "up" else "🔴"
                open_badge = "" if m.get("market_open") else " · ⛔CLOSED"
                st.metric(
                    f"{arrow} {m['name']} ({m['type']}){open_badge}",
                    fmt(m["price"]),
                    delta=f"{m['change_pct']:+.2f}%",
                )
                if v:
                    color = "up" if v["direction"] == "UP" else "down"
                    st.markdown(
                        f"<span class='{color}'>▸ {v['direction']} "
                        f"{v['confidence']:.0f}%</span> "
                        f"<span class='small'>src: {m['source']}</span>",
                        unsafe_allow_html=True)
                else:
                    st.markdown(f"<span class='small'>analyzing… · src: {m['source']}"
                                f"</span>", unsafe_allow_html=True)

# ================================================================== #
#  TAB: TRADE SIGNALS (click to place)
# ================================================================== #
with tab_signals:
    sig_data = ENGINE.get_signals()
    sigs = sig_data["signals"]
    st.markdown(f"**Jarvis scanned {sig_data['total_scanned']} setups so far.** "
                "Every setup he finds appears here — **you click PLACE to authorize it.**")
    waiting = [x for x in sigs if x["status"] == "waiting"]
    if not sigs:
        st.info("Jarvis is scanning the live market… signals appear when confidence ≥ "
                f"{int(ENGINE.min_conf)}%.")
    for sig in sigs:
        col = "🟩" if sig["side"] == "BUY" else "🟥"
        exp = max(0, int(sig["expires"] - time.time()))
        stat = {"waiting": f"⏳ {exp//60}m{exp%60:02d}s left",
                "placed": "✅ PLACED", "expired": "▪ expired"}[sig["status"]]
        with st.expander(f"{col} **{sig['side']} {sig['symbol']}** · conf "
                         f"{sig['confidence']:.0f}% · {stat}",
                         expanded=(sig["status"] == "waiting")):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Entry", fmt(sig["entry"]))
            c2.metric("Take Profit", fmt(sig["tp"]))
            c3.metric("Stop Loss", fmt(sig["sl"]))
            c4.metric("R:R", sig.get("rr") or "--")
            st.caption(f"TP source: {sig.get('tp_source', 'ATR x2R')}")
            for r in sig.get("reasons", []):
                st.markdown(f"- {r}")
            if sig["status"] == "waiting":
                if st.button(f"▶ PLACE {sig['side']} {sig['symbol']}",
                             key=f"place_{sig['id']}", type="primary"):
                    res = ENGINE.place_trade(sig["symbol"], source="manual click")
                    if res.get("ok"):
                        st.success(f"Placed! Entry {fmt(res['entry'])} · "
                                   f"TP {fmt(res['tp'])} · SL {fmt(res['sl'])}")
                    else:
                        st.error(res.get("error"))
                    time.sleep(0.8)
                    st.rerun()

# ================================================================== #
#  TAB: AI COUNCIL (ask in detail)
# ================================================================== #
with tab_council:
    syms = [a["symbol"] for a in config.WATCHLIST]
    pick = st.selectbox("Select market asset", syms,
                        format_func=lambda s: next(
                            f"{a['name']} ({s})" for a in config.WATCHLIST
                            if a["symbol"] == s))
    if st.button("🧠 ASK THE COUNCIL — will it go UP or DOWN?", type="primary"):
        asset = next(a for a in config.WATCHLIST if a["symbol"] == pick)
        with st.spinner("Jarvis is consulting Gemini, Groq, indicators, strategies, "
                        "patterns and news…"):
            verdict = council.analyze(asset, use_llms=True)
            ENGINE.last_analysis[pick] = verdict
    a = ENGINE.last_analysis.get(pick)
    if a:
        v = a["verdict"]
        color = "#22d37e" if v["direction"] == "UP" else "#ff4d67"
        st.markdown(f"## Verdict: <span style='color:{color}'>{v['direction']} "
                    f"{v['score']:+.1f}</span> · confidence {v['confidence']}%",
                    unsafe_allow_html=True)
        st.caption(f"price {fmt(a['price'])} · data source {a['data_source']} · "
                   f"analyzed in {a.get('elapsed_sec', '?')}s")
        names = {"jarvis": "JARVIS ML", "gemini": "GEMINI", "groq": "GROQ",
                 "indicators": "INDICATORS", "strategies": "STRATEGIES",
                 "patterns": "PATTERNS", "news": "NEWS"}
        for k in ("jarvis", "gemini", "groq", "indicators", "strategies",
                  "patterns", "news"):
            m = a["members"].get(k)
            if not m:
                continue
            cols = st.columns([1, 3, 1])
            cols[0].markdown(f"**{names[k]}**")
            if m["score"] is None:
                err = (m.get("detail") or {}).get("error", "no vote")
                cols[1].progress(0.5, text="no vote")
                cols[2].caption(str(err)[:40])
            else:
                sc = m["score"]
                cols[1].progress(min(1.0, 0.5 + sc / 200),
                                 text=f"{'bullish' if sc >= 0 else 'bearish'}")
                cols[2].markdown(f"<span class='{'up' if sc >= 0 else 'down'}'>"
                                 f"**{sc:+.0f}**</span>", unsafe_allow_html=True)
        det = a["members"].get("gemini", {}).get("detail", {})
        if det.get("reason"):
            st.info(f"**Gemini:** {det['reason']}")
        det = a["members"].get("groq", {}).get("detail", {})
        if det.get("reason"):
            st.info(f"**Groq:** {det['reason']}")
        pats = (a["members"].get("patterns", {}).get("detail") or {}).get("found", [])
        if pats:
            with st.expander(f"📐 {len(pats)} live patterns detected"):
                for p in pats:
                    icon = "▲" if p["score"] > 0 else ("▼" if p["score"] < 0 else "▶")
                    st.markdown(f"{icon} **{p['name']}** ({p['dir']}, {p['score']:+.0f}) "
                                f"— {p['bars_ago']} bars ago {('· ' + p['note']) if p.get('note') else ''}")
        if a.get("abcd"):
            ab = a["abcd"]
            st.markdown(f"**A-B-C→D projection** ({ab['direction']}): "
                        f"A={fmt(ab['A'])} B={fmt(ab['B'])} C={fmt(ab['C'])} → "
                        f"**D = (B×C)÷A = {fmt(ab['D'])}**")
        p = a["plan"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entry", fmt(p["entry"]))
        c2.metric("Take Profit", fmt(p["tp"]))
        c3.metric("Stop Loss", fmt(p["sl"]))
        c4.metric("R:R", p["rr"])
        st.caption(f"TP from: {p.get('tp_source', 'ATR x2R')}")
    else:
        st.info("Pick an asset and ask the council — Jarvis will collect scores from "
                "every AI model, indicator, strategy, pattern and news source.")

    with st.expander("📖 What every indicator & strategy means (reference)"):
        for key, info in indicators.INDICATOR_INFO.items():
            st.markdown(f"**{info['name']}** — {info['what']}  \n"
                        f"*Scoring:* {info['how_scored']}  \n*Detail:* {info['detail']}")
        st.divider()
        for name, desc in indicators.STRATEGY_INFO.items():
            st.markdown(f"**{name}** — {desc}")

# ================================================================== #
#  TAB: POSITIONS
# ================================================================== #
with tab_positions:
    s = ENGINE.status()
    pos = s["open_positions"]
    if not pos:
        st.info("No open positions. Authorize a signal in ⚡ Trade Signals.")
    for p in pos:
        col = "🟩" if p["side"] == "BUY" else "🟥"
        pnl_c = "up" if p["pnl"] >= 0 else "down"
        with st.expander(f"{col} {p['side']} {p['symbol']} · "
                         f"PnL {p['pnl']:+.2f}", expanded=True):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Entry", fmt(p["entry"]))
            c2.metric("TP", fmt(p["tp"]))
            c3.metric("SL", fmt(p["sl"]) + (" (BE)" if p.get("be_moved") else ""))
            c4.metric("Qty", fmt(p["qty"]))
            c5.metric("PnL", f"{p['pnl']:+.2f}")
            held = int(time.time() - p["opened"])
            st.caption(f"held {held//3600}h {held%3600//60}m · "
                       f"placed by {p['meta'].get('placed_by', 'auto')} · "
                       f"conf at entry {p['meta'].get('confidence')}%")
            if st.button(f"✖ Close {p['symbol']} now", key=f"close_{p['id']}"):
                ENGINE.manual_close(p["id"])
                st.rerun()

# ================================================================== #
#  TAB: JOURNAL
# ================================================================== #
with tab_journal:
    jd = ENGINE.get_journal()
    stats = jd["stats"]
    if stats["total"]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Closed trades", stats["total"])
        c2.metric("Win rate", f"{stats['win_rate']}%")
        c3.metric("Wins / Losses", f"{stats['wins']} / {stats['losses']}")
        c4.metric("Total PnL", f"{stats['total_pnl']:+.2f}")
        st.caption("Close reasons: " + " · ".join(
            f"{k}: {v}" for k, v in stats["by_reason"].items()))
        for t in jd["journal"]:
            icon = "✅" if t["outcome"] == "WIN" else ("❌" if t["outcome"] == "LOSS" else "➖")
            with st.expander(
                    f"{icon} {t['symbol']} {t['side']} · {t['outcome']} "
                    f"{t['pnl']:+.2f} ({t['r_multiple']:+}R) · {t['close_reason']} · "
                    f"held {t['held_human']}"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entry", fmt(t["entry_price"]))
                c2.metric("Exit", fmt(t["exit_price"]))
                c3.metric("TP", fmt(t["tp"]))
                c4.metric("SL", fmt(t["initial_sl"]))
                st.markdown(f"**Why it closed:** {t['close_explanation']}")
                if t.get("sl_moved_to_breakeven"):
                    st.markdown("🛡️ Stop had been moved to breakeven before close.")
                st.markdown(f"**Why it was entered** (conf {t['confidence_at_entry']}%, "
                            f"council {t['council_score_at_entry']}):")
                for r in t.get("why_entered", []):
                    st.markdown(f"- {r}")
                if t.get("member_votes_at_entry"):
                    st.caption("Votes at entry: " + " · ".join(
                        f"{k}: {v:+.0f}" if v is not None else f"{k}: --"
                        for k, v in t["member_votes_at_entry"].items()))
                st.caption(f"opened {datetime.fromtimestamp(t['opened_at']):%H:%M:%S} · "
                           f"closed {datetime.fromtimestamp(t['closed_at']):%H:%M:%S} · "
                           f"placed by {t['placed_by']}")
    else:
        st.info("Closed trades appear here with the full story: entry, TP, SL, exit, "
                "PnL, R-multiple, hold time and exactly WHY each trade closed.")

# ================================================================== #
#  TAB: JARVIS ACTIVITY (what is he doing right now)
# ================================================================== #
with tab_activity:
    act = ENGINE.get_activity()
    c = act["counters"]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Price ticks", c["price_ticks"])
    c2.metric("Council runs", c["council_runs"])
    c3.metric("AI model calls", c["llm_calls"])
    c4.metric("Patterns seen", c["patterns_seen"])
    c5.metric("News scrapes", c["news_refreshes"])
    c6.metric("Closed-mkt skips", c["skipped_closed"])
    colA, colB = st.columns([2, 1])
    with colA:
        st.markdown("#### 🎬 Live narration — everything Jarvis is doing")
        lines = []
        for a in act["activity"][:60]:
            ts = datetime.fromtimestamp(a["ts"]).strftime("%H:%M:%S")
            lines.append(f"<div class='act-{a['kind']}'>[{ts}] "
                         f"{a['kind'].upper()}: {a['msg']}</div>")
        st.markdown("<div style='font-family:monospace;font-size:12px;"
                    "background:#0c1220;border:1px solid #1c2a44;border-radius:8px;"
                    "padding:10px;max-height:420px;overflow-y:auto'>"
                    + "".join(lines) + "</div>", unsafe_allow_html=True)
    with colB:
        st.markdown("#### 🕐 Market timings")
        for sym, m in act["markets"].items():
            dot = "🟢" if m["open"] else "🔴"
            st.markdown(f"{dot} **{sym}** — {m['venue']}  \n"
                        f"<span class='small'>{m['session']}</span>",
                        unsafe_allow_html=True)

# ================================================================== #
#  TAB: NEWS
# ================================================================== #
with tab_news:
    with news.ENGINE.lock:
        heads = list(news.ENGINE.headlines[:40])
        ok = list(news.ENGINE.sources_ok)
        fail = list(news.ENGINE.sources_fail)
        cal = news.ENGINE.high_impact_soon()
    st.markdown(f"**{len(heads)} headlines** from {len(ok)} sources "
                f"({len(fail)} unreachable)")
    if fail and not ok:
        st.warning("All news sources unreachable from this network — on your PC "
                   "they connect automatically. Sources: Yahoo, CNBC, Bloomberg, NSE, "
                   "BSE, Investing.com, Nasdaq, MarketWatch, Koyfin, StockAnalysis, "
                   "Moneycontrol, LiveMint, CoinDesk, CoinTelegraph, EconomicTimes, "
                   "ForexFactory…")
    if cal:
        st.markdown("#### ⚠️ High-impact economic events this week")
        for e in cal[:6]:
            st.markdown(f"- **{e['title']}** ({e['country']}) — {e['date']}")
    for h in heads:
        dot = "🟢" if h["sentiment"] > 0.05 else ("🔴" if h["sentiment"] < -0.05 else "⚪")
        st.markdown(f"{dot} {h['title']}  \n<span class='small'>{h['source']}</span>",
                    unsafe_allow_html=True)

# ------------------------------------------------------------------ #
#  auto refresh
# ------------------------------------------------------------------ #
if auto_refresh:
    time.sleep(5)
    st.rerun()

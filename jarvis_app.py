"""
J.A.R.V.I.S - heavy trading terminal (Streamlit).

Everything on ONE screen, no sidebar:
  top command bar - balance / equity / controls / jarvis brain
  SIGNAL DECK     - one-click PLACE buttons, front and center
  live market grid, open positions, AI council, activity feed,
  trade journal, news - all visible like a professional trading floor.

Launch: python run.py   (opens at :8501)
"""
import time
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="JARVIS TERMINAL", page_icon="📟",
                   layout="wide", initial_sidebar_state="collapsed")


@st.cache_resource
def boot_engine():
    from jarvis_trader import trader
    trader.ENGINE.start()
    return trader.ENGINE

ENGINE = boot_engine()

from jarvis_trader import config, council, news, indicators  # noqa: E402

# ================================================================== #
#  HEAVY TERMINAL THEME
# ================================================================== #
st.markdown("""
<style>
/* kill sidebar + padding: full trading floor */
[data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none;}
.block-container {padding:0.6rem 1.1rem 2rem 1.1rem; max-width:100% !important;}
header[data-testid="stHeader"] {display:none;}

.stApp {background:
  linear-gradient(rgba(6,10,16,.97), rgba(6,10,16,.97)),
  repeating-linear-gradient(0deg, transparent, transparent 39px, #0d1626 40px),
  repeating-linear-gradient(90deg, transparent, transparent 39px, #0d1626 40px);
  background-color:#05080d;}

h1,h2,h3,h4 {font-family:'Segoe UI',monospace; letter-spacing:1px;}

/* terminal panels */
.tpanel {background:#080d16; border:1px solid #16233c; border-radius:4px;
  padding:8px 12px; margin-bottom:8px;}
.tpanel .hd {color:#3fa9db; font-size:10px; letter-spacing:2.5px; font-weight:700;
  text-transform:uppercase; border-bottom:1px solid #16233c; padding-bottom:4px;
  margin-bottom:6px; display:flex; justify-content:space-between;}

/* top bar */
.topbar {background:linear-gradient(90deg,#081422,#0a0f1a); border:1px solid #1b3252;
  border-radius:4px; padding:8px 16px; display:flex; gap:26px; align-items:center;
  flex-wrap:wrap; margin-bottom:8px;}
.topbar .brand {font-size:20px; font-weight:800; color:#37c8f5; letter-spacing:3px;}
.topbar .brand span {color:#f5b83d;}
.kpi {display:flex; flex-direction:column;}
.kpi .v {font-size:17px; font-weight:700; color:#e8f1fc; font-family:monospace;}
.kpi .l {font-size:9px; color:#51637f; letter-spacing:1.5px; text-transform:uppercase;}
.kpi .v.pos {color:#20e397;} .kpi .v.neg {color:#ff4d67;}

.jsay {background:#07131f; border:1px solid #14293f; border-left:3px solid #37c8f5;
  padding:5px 12px; border-radius:3px; color:#9fd3ec; font-size:12.5px;
  font-family:monospace; margin-bottom:8px;}

/* ticker cells */
.tick {background:#0a1020; border:1px solid #16233c; border-radius:3px;
  padding:6px 9px; margin-bottom:6px; font-family:monospace;}
.tick .sym {font-size:12px; font-weight:700; color:#cfe1f5;}
.tick .px {font-size:16px; font-weight:800;}
.tick .up {color:#20e397;} .tick .down {color:#ff4d67;}
.tick .meta {font-size:9.5px; color:#51637f;}
.badge {font-size:8.5px; padding:1px 5px; border-radius:2px; font-weight:700;
  letter-spacing:.5px;}
.badge.closed {background:#2b0f16; color:#ff4d67; border:1px solid #571f2b;}
.badge.buy {background:#06281c; color:#20e397; border:1px solid #14563a;}
.badge.sell {background:#2b0f16; color:#ff4d67; border:1px solid #571f2b;}

/* signal cards - the click-to-trade deck */
.sig {background:linear-gradient(180deg,#0b1424,#080d16); border:1px solid #23405f;
  border-radius:4px; padding:10px 12px; font-family:monospace; margin-bottom:4px;}
.sig.buy {border-left:4px solid #20e397;} .sig.sell {border-left:4px solid #ff4d67;}
.sig .head {font-size:15px; font-weight:800;}
.sig .lvl {font-size:11.5px; color:#8ba3c4;}
.sig .lvl b {color:#e8f1fc;}
.sig .why {font-size:10px; color:#51637f; margin-top:3px;}

/* buttons: heavy terminal style */
div.stButton > button {font-family:monospace; font-weight:800; letter-spacing:1px;
  border-radius:3px; border:1px solid #23405f; background:#0d1930; color:#cfe1f5;
  padding:0.35rem 0.6rem;}
div.stButton > button:hover {border-color:#37c8f5; color:#37c8f5;}
div.stButton > button[kind="primary"] {background:#08351f; border:1px solid #20e397;
  color:#20e397; font-size:15px;}
div.stButton > button[kind="primary"]:hover {background:#20e397; color:#04140b;}

/* activity feed */
.feed {font-family:monospace; font-size:10.5px; background:#05080d;
  border:1px solid #16233c; border-radius:3px; padding:8px;
  max-height:250px; overflow-y:auto; line-height:1.55;}
.f-track{color:#51637f}.f-analyze{color:#37c8f5}.f-signal{color:#f5b83d}
.f-trade{color:#20e397}.f-jarvis{color:#a78bfa}.f-news{color:#e8853d}.f-skip{color:#b33e4e}

/* tables */
.jrow {font-family:monospace; font-size:11px; border-bottom:1px solid #101a2c;
  padding:4px 0;}
.small {color:#51637f; font-size:10px; font-family:monospace;}
hr {border-color:#16233c !important; margin:6px 0 !important;}
[data-testid="stMetric"] {background:#0a1020; border:1px solid #16233c;
  border-radius:3px; padding:6px 10px;}
[data-testid="stMetricValue"] {font-family:monospace; font-size:1.15rem !important;}
[data-testid="stMetricLabel"] {font-size:.65rem !important; color:#51637f !important;
  letter-spacing:1px; text-transform:uppercase;}
div[data-testid="stExpander"] {background:#080d16; border:1px solid #16233c;
  border-radius:4px;}
</style>
""", unsafe_allow_html=True)


def fmt(x, d=6):
    if x is None:
        return "--"
    return f"{x:,.2f}" if abs(x) >= 1000 else f"{x:.{d}g}"


S = ENGINE.status()
ACT = ENGINE.get_activity()
SIGD = ENGINE.get_signals()
JRN = ENGINE.get_journal()

# ================================================================== #
#  TOP COMMAND BAR
# ================================================================== #
j = S["jarvis"]
eq_delta = S["equity"] - S["balance"]
open_markets = sum(1 for m in ACT["markets"].values() if m["open"])
llm = S.get("llm_status", {})
st.markdown(f"""
<div class="topbar">
  <div class="brand">J.A.R.V.I.S <span>TERMINAL</span></div>
  <div class="kpi"><div class="v">${S['balance']:,.2f}</div><div class="l">Balance</div></div>
  <div class="kpi"><div class="v {'pos' if eq_delta>=0 else 'neg'}">${S['equity']:,.2f}</div><div class="l">Equity</div></div>
  <div class="kpi"><div class="v {'pos' if eq_delta>=0 else 'neg'}">{eq_delta:+,.2f}</div><div class="l">Open PnL</div></div>
  <div class="kpi"><div class="v">{len(S['open_positions'])}</div><div class="l">Positions</div></div>
  <div class="kpi"><div class="v" style="color:#f5b83d">{S['signals_waiting']}</div><div class="l">Signals ready</div></div>
  <div class="kpi"><div class="v">{S['signals_scanned']}</div><div class="l">Scanned</div></div>
  <div class="kpi"><div class="v" style="color:#a78bfa">{j['samples_trained']}</div><div class="l">Jarvis samples</div></div>
  <div class="kpi"><div class="v" style="color:#a78bfa">{str(j['accuracy'])+'%' if j['accuracy'] is not None else '—'}</div><div class="l">Live accuracy</div></div>
  <div class="kpi"><div class="v">{open_markets}/{len(config.WATCHLIST)}</div><div class="l">Markets open</div></div>
  <div class="kpi"><div class="v" style="font-size:11px">{llm.get('gemini','?')} / {llm.get('groq','?')}</div><div class="l">Gemini / Groq</div></div>
</div>
""", unsafe_allow_html=True)

# jarvis one-liner + controls row
say_parts = []
if j["bootstrapping"]:
    say_parts.append("Training my brain on historical data…")
if S["signals_waiting"]:
    say_parts.append(f"{S['signals_waiting']} setup(s) armed - one click places the trade.")
if S["open_positions"]:
    say_parts.append(f"Managing {len(S['open_positions'])} live position(s).")
if not say_parts:
    say_parts.append("Scanning all markets for the next setup…")
st.markdown(f"<div class='jsay'>JARVIS ▸ {' '.join(say_parts)}</div>",
            unsafe_allow_html=True)

cc0, cc1, cc2, cc3, cc4, cc5 = st.columns([1.7, 1, 1.4, 1.4, 0.9, 0.9])
with cc0:
    from jarvis_trader import feeds as _feeds
    tf = st.radio("TIMEFRAME", _feeds.VALID_INTERVALS, horizontal=True,
                  index=_feeds.VALID_INTERVALS.index(S.get("interval", "5m")))
    if tf != S.get("interval"):
        ENGINE.set_interval(tf)
        st.rerun()
with cc1:
    auto = st.toggle("AUTO-TRADE", value=S["auto_trade"],
                     help="ON = Jarvis places trades himself. OFF = you click.")
    if auto != S["auto_trade"]:
        ENGINE.auto_trade = auto
        ENGINE.log(f"Settings updated: auto_trade={auto}")
with cc2:
    mc = st.slider("MIN CONFIDENCE %", 0, 100, int(S["min_confidence"]), 5,
                   label_visibility="visible")
    if mc != S["min_confidence"]:
        ENGINE.min_conf = float(mc)
with cc3:
    rk = st.slider("RISK / TRADE %", 0.1, 5.0, float(S["risk_pct"]), 0.1)
    if rk != S["risk_pct"]:
        ENGINE.risk_pct = float(rk)
with cc4:
    live = st.toggle("LIVE REFRESH", value=True)
with cc5:
    if st.button("⟳ REFRESH", use_container_width=True):
        st.rerun()

# ================================================================== #
#  FINAL TRADE SETUP - the ONE best trade from all scores
# ================================================================== #
fs = S.get("final_setup")
if fs:
    fcol = "#20e397" if fs["side"] == "BUY" else "#ff4d67"
    grade_col = "#f5b83d" if fs["grade"] == "READY" else "#51637f"
    members_txt = " · ".join(
        f"{k} {v:+.0f}" if v is not None else f"{k} --"
        for k, v in (fs.get("members") or {}).items())
    reasons_txt = "".join(f"<div class='why'>▸ {r[:105]}</div>"
                          for r in (fs.get("reasons") or [])[:3])
    fs_c1, fs_c2 = st.columns([4.2, 1])
    with fs_c1:
        st.markdown(f"""
<div class="sig {'buy' if fs['side']=='BUY' else 'sell'}" style="border-width:2px">
  <div class="head">
    <span style="color:{grade_col};font-size:10px;letter-spacing:2px">🎯 FINAL TRADE SETUP [{fs['interval']}] · {fs['grade']}</span><br>
    <span style="color:{fcol};font-size:22px">{fs['side']} {fs['symbol']}</span>
    <span style="font-size:12px;color:#8ba3c4"> {fs['name']} · confidence {fs['confidence']:.0f}% · score {fs['score']:+.1f}</span>
  </div>
  <div class="lvl" style="font-size:13px">ENTRY <b>{fmt(fs['entry'])}</b> &nbsp;·&nbsp;
    TP <b style="color:#20e397">{fmt(fs['tp'])}</b> &nbsp;·&nbsp;
    SL <b style="color:#ff4d67">{fmt(fs['sl'])}</b> &nbsp;·&nbsp; R:R <b>{fs.get('rr','--')}</b>
    &nbsp;·&nbsp; <span style="color:#51637f">{fs.get('tp_source','')}</span></div>
  {reasons_txt}
  <div class="why" style="margin-top:4px">scores ▸ {members_txt}</div>
</div>""", unsafe_allow_html=True)
    with fs_c2:
        if fs["grade"] == "READY":
            st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
            if st.button(f"▶ PLACE\n{fs['side']} {fs['symbol']}", key="place_final",
                         type="primary", use_container_width=True):
                res = ENGINE.place_trade(fs["symbol"], source="final setup click")
                if res.get("ok"):
                    st.toast(f"✅ {fs['side']} {fs['symbol']} PLACED", icon="🎯")
                else:
                    st.toast(f"❌ {res.get('error')}", icon="⚠️")
                time.sleep(0.5)
                st.rerun()
        else:
            st.markdown("<div class='small' style='margin-top:30px'>below confidence "
                        "threshold — watching</div>", unsafe_allow_html=True)

# ================================================================== #
#  SIGNAL DECK - one-click trading, front and center
# ================================================================== #
sigs = SIGD["signals"]
waiting = [x for x in sigs if x["status"] == "waiting"]
st.markdown(f"<div class='tpanel'><div class='hd'><span>⚡ SIGNAL DECK — CLICK = TRADE PLACED"
            f"</span><span>{len(waiting)} armed · {SIGD['total_scanned']} scanned</span></div>"
            "</div>", unsafe_allow_html=True)

if not sigs:
    st.markdown("<div class='small'>Jarvis is hunting… setups appear here the moment "
                "he finds them in the live market.</div>", unsafe_allow_html=True)
else:
    sig_cols = st.columns(3)
    shown = [x for x in sigs if x["status"] == "waiting"][:6] or sigs[:3]
    for i, sig in enumerate(shown):
        cls = "buy" if sig["side"] == "BUY" else "sell"
        colr = "#20e397" if sig["side"] == "BUY" else "#ff4d67"
        exp = max(0, int(sig["expires"] - time.time()))
        with sig_cols[i % 3]:
            reasons = "".join(f"<div class='why'>▸ {r[:78]}</div>"
                              for r in (sig.get("reasons") or [])[:2])
            status_txt = (f"⏳ {exp//60}m{exp%60:02d}s" if sig["status"] == "waiting"
                          else "✔ PLACED" if sig["status"] == "placed" else "· expired")
            st.markdown(f"""
<div class="sig {cls}">
  <div class="head" style="color:{colr}">{sig['side']} {sig['symbol']}
    <span style="float:right;font-size:10px;color:#8ba3c4">{status_txt} · conf {sig['confidence']:.0f}%</span></div>
  <div class="lvl">ENTRY <b>{fmt(sig['entry'])}</b> &nbsp;·&nbsp; TP <b style="color:#20e397">{fmt(sig['tp'])}</b>
   &nbsp;·&nbsp; SL <b style="color:#ff4d67">{fmt(sig['sl'])}</b> &nbsp;·&nbsp; R:R <b>{sig.get('rr','--')}</b></div>
  {reasons}
</div>""", unsafe_allow_html=True)
            if sig["status"] == "waiting":
                if st.button(f"▶ PLACE {sig['side']} {sig['symbol']}",
                             key=f"pl_{sig['id']}", type="primary",
                             use_container_width=True):
                    res = ENGINE.place_trade(sig["symbol"], source="manual click")
                    if res.get("ok"):
                        st.toast(f"✅ {sig['side']} {sig['symbol']} PLACED @ "
                                 f"{fmt(res['entry'])}", icon="⚡")
                    else:
                        st.toast(f"❌ {res.get('error')}", icon="⚠️")
                    time.sleep(0.5)
                    st.rerun()

st.markdown("<hr>", unsafe_allow_html=True)

# ================================================================== #
#  MAIN FLOOR: markets | positions+council | activity
# ================================================================== #
colL, colM, colR = st.columns([1.15, 1.5, 1.15])

# ---------- LEFT: live market grid ----------
with colL:
    mkts = list(ENGINE.market.values())
    n_open = sum(1 for m in mkts if m.get("market_open"))
    st.markdown("<div class='tpanel'><div class='hd'><span>📡 LIVE MARKETS "
                f"[{S.get('interval','5m')}]</span>"
                f"<span>{n_open} open / {len(mkts)} total</span></div></div>",
                unsafe_allow_html=True)
    analysis = dict(ENGINE.last_analysis)
    # open markets first, then closed; grouped by type
    ordered = sorted(mkts, key=lambda x: (not x.get("market_open"),
                                          x["type"], x["symbol"]))
    rows = ""
    for m in ordered:
        a = analysis.get(m["symbol"])
        v = a["verdict"] if a else None
        dirn = ""
        if v and m.get("market_open"):
            dirn = (f"<span class='badge {'buy' if v['direction']=='UP' else 'sell'}'>"
                    f"{v['direction']} {v['confidence']:.0f}</span>")
        closed = "" if m.get("market_open") else "<span class='badge closed'>CLOSED</span>"
        chg_cls = "up" if m["change_pct"] >= 0 else "down"
        px = fmt(m["price"]) if m.get("price") is not None else "--"
        rows += f"""
<div class="tick">
  <span class="sym">{m['symbol']}</span> {closed} {dirn}
  <span style="float:right" class="px {chg_cls}">{px}</span><br>
  <span class="meta">{m['name']} · {m['type']} · {m['source']}</span>
  <span style="float:right" class="meta {chg_cls}">{m['change_pct']:+.2f}%</span>
</div>"""
    st.markdown(f"<div style='max-height:640px;overflow-y:auto'>{rows}</div>",
                unsafe_allow_html=True)

# ---------- MIDDLE: positions + AI council ----------
with colM:
    st.markdown("<div class='tpanel'><div class='hd'><span>📈 OPEN POSITIONS</span>"
                f"<span>{len(S['open_positions'])}</span></div></div>",
                unsafe_allow_html=True)
    if not S["open_positions"]:
        st.markdown("<div class='small'>flat — no exposure</div>",
                    unsafe_allow_html=True)
    for p in S["open_positions"]:
        colr = "#20e397" if p["side"] == "BUY" else "#ff4d67"
        pnl_c = "up" if p["pnl"] >= 0 else "down"
        held = int(time.time() - p["opened"])
        pc1, pc2 = st.columns([4, 1])
        with pc1:
            st.markdown(f"""
<div class="tick">
  <span class="sym" style="color:{colr}">{p['side']} {p['symbol']}</span>
  <span style="float:right" class="px {pnl_c}">{p['pnl']:+,.2f}</span><br>
  <span class="meta">in {fmt(p['entry'])} · TP {fmt(p['tp'])} · SL {fmt(p['sl'])}
  {'· BE🛡' if p.get('be_moved') else ''} · {held//60}m · qty {fmt(p['qty'])}</span>
</div>""", unsafe_allow_html=True)
        with pc2:
            if st.button("✖", key=f"cl_{p['id']}", help=f"close {p['symbol']} now",
                         use_container_width=True):
                ENGINE.manual_close(p["id"])
                st.rerun()

    st.markdown("<div class='tpanel'><div class='hd'><span>🧠 AI COUNCIL — ASK UP OR DOWN"
                "</span></div></div>", unsafe_allow_html=True)
    qc1, qc2 = st.columns([2.2, 1])
    with qc1:
        pick = st.selectbox("asset", [a["symbol"] for a in config.WATCHLIST],
                            label_visibility="collapsed")
    with qc2:
        ask = st.button("ASK COUNCIL", use_container_width=True)
    if ask:
        asset = next(a for a in config.WATCHLIST if a["symbol"] == pick)
        with st.spinner(f"Consulting Jarvis + Gemini + Groq + engines on "
                        f"{S.get('interval','5m')} candles…"):
            verdict = council.analyze(asset, use_llms=True,
                                      interval=S.get("interval", "5m"))
            ENGINE.last_analysis[pick] = verdict
    a = ENGINE.last_analysis.get(pick)
    if a:
        v = a["verdict"]
        colr = "#20e397" if v["direction"] == "UP" else "#ff4d67"
        st.markdown(f"<div style='font-family:monospace;font-size:18px;font-weight:800;"
                    f"color:{colr}'>{pick} ▸ {v['direction']} {v['score']:+.1f} "
                    f"<span style='font-size:11px;color:#8ba3c4'>conf {v['confidence']}%"
                    f" · {fmt(a['price'])} · {a['data_source']}</span></div>",
                    unsafe_allow_html=True)
        names = {"jarvis": "JARVIS", "gemini": "GEMINI", "groq": "GROQ",
                 "indicators": "INDIC", "strategies": "STRAT",
                 "patterns": "PATTRN", "news": "NEWS"}
        bar_html = ""
        for k, nm in names.items():
            m = a["members"].get(k)
            if not m:
                continue
            sc = m["score"]
            if sc is None:
                bar_html += (f"<div style='display:flex;gap:6px;align-items:center;"
                             f"font-family:monospace;font-size:10.5px;margin:2px 0'>"
                             f"<span style='width:52px;color:#51637f'>{nm}</span>"
                             f"<span style='color:#51637f'>no vote</span></div>")
                continue
            w = abs(sc) / 2
            colb = "#20e397" if sc >= 0 else "#ff4d67"
            left = 50 if sc >= 0 else 50 - w
            bar_html += (f"<div style='display:flex;gap:6px;align-items:center;"
                         f"font-family:monospace;font-size:10.5px;margin:2px 0'>"
                         f"<span style='width:52px;color:#8ba3c4'>{nm}</span>"
                         f"<span style='flex:1;background:#0d1626;height:9px;"
                         f"border-radius:2px;position:relative;overflow:hidden'>"
                         f"<span style='position:absolute;left:{left}%;width:{w}%;top:0;"
                         f"bottom:0;background:{colb}'></span>"
                         f"<span style='position:absolute;left:50%;width:1px;top:0;"
                         f"bottom:0;background:#23405f'></span></span>"
                         f"<span style='width:36px;text-align:right;color:{colb};"
                         f"font-weight:700'>{sc:+.0f}</span></div>")
        st.markdown(bar_html, unsafe_allow_html=True)
        for k in ("gemini", "groq"):
            det = (a["members"].get(k) or {}).get("detail") or {}
            if det.get("reason"):
                st.markdown(f"<div class='small'>▸ {k.upper()}: {det['reason'][:130]}"
                            "</div>", unsafe_allow_html=True)
        p = a["plan"]
        st.markdown(f"<div class='small' style='margin-top:4px'>PLAN ▸ entry "
                    f"<b style='color:#e8f1fc'>{fmt(p['entry'])}</b> · TP "
                    f"<b style='color:#20e397'>{fmt(p['tp'])}</b> · SL "
                    f"<b style='color:#ff4d67'>{fmt(p['sl'])}</b> · R:R {p['rr']} · "
                    f"{p.get('tp_source','')}</div>", unsafe_allow_html=True)
        pats = (a["members"].get("patterns", {}).get("detail") or {}).get("found", [])
        if pats:
            ptxt = " · ".join(f"{'▲' if x['score']>0 else '▼' if x['score']<0 else '▶'}"
                              f"{x['name']}" for x in pats[:5])
            st.markdown(f"<div class='small'>PATTERNS ▸ {ptxt}</div>",
                        unsafe_allow_html=True)
        if a.get("abcd"):
            ab = a["abcd"]
            st.markdown(f"<div class='small'>ABCD ▸ {ab['direction']} · A {fmt(ab['A'])} "
                        f"B {fmt(ab['B'])} C {fmt(ab['C'])} → D=(B×C)÷A = "
                        f"<b style='color:#f5b83d'>{fmt(ab['D'])}</b></div>",
                        unsafe_allow_html=True)

# ---------- RIGHT: jarvis activity + market hours + news ----------
with colR:
    c = ACT["counters"]
    st.markdown(f"<div class='tpanel'><div class='hd'><span>🤖 JARVIS LIVE ACTIVITY</span>"
                f"<span>{c['price_ticks']} ticks · {c['council_runs']} scans · "
                f"{c['llm_calls']} AI calls</span></div></div>", unsafe_allow_html=True)
    feed = ""
    for aev in ACT["activity"][:45]:
        ts = datetime.fromtimestamp(aev["ts"]).strftime("%H:%M:%S")
        feed += (f"<div class='f-{aev['kind']}'>[{ts}] {aev['kind'].upper()} ▸ "
                 f"{aev['msg']}</div>")
    st.markdown(f"<div class='feed'>{feed or 'booting…'}</div>", unsafe_allow_html=True)

    st.markdown("<div class='tpanel' style='margin-top:8px'><div class='hd'>"
                "<span>🕐 MARKET SESSIONS</span></div></div>", unsafe_allow_html=True)
    mrows = ""
    for sym, m in ACT["markets"].items():
        dot = "🟢" if m["open"] else "🔴"
        mrows += (f"<div style='font-family:monospace;font-size:10px;padding:1.5px 0;"
                  f"color:#8ba3c4'>{dot} <b style='color:#cfe1f5'>{sym}</b> "
                  f"· {m['venue']} <span style='float:right;color:#51637f'>"
                  f"{m['session']}</span></div>")
    st.markdown(f"<div class='feed' style='max-height:160px'>{mrows}</div>",
                unsafe_allow_html=True)

    with news.ENGINE.lock:
        heads = list(news.ENGINE.headlines[:12])
        n_ok = len(news.ENGINE.sources_ok)
    st.markdown(f"<div class='tpanel' style='margin-top:8px'><div class='hd'>"
                f"<span>📰 NEWS WIRE</span><span>{n_ok} sources live</span></div></div>",
                unsafe_allow_html=True)
    nrows = ""
    for h in heads:
        dot = ("🟢" if h["sentiment"] > 0.05 else
               "🔴" if h["sentiment"] < -0.05 else "⚪")
        nrows += (f"<div style='font-size:10px;padding:2px 0;color:#8ba3c4'>{dot} "
                  f"{h['title'][:90]}<span style='color:#51637f'> — {h['source']}"
                  f"</span></div>")
    if not nrows:
        nrows = ("<span class='small'>news sources unreachable on this network "
                 "- they connect automatically on your PC</span>")
    st.markdown(f"<div class='feed' style='max-height:180px'>{nrows}</div>",
                unsafe_allow_html=True)

# ================================================================== #
#  TRADE JOURNAL - full width
# ================================================================== #
stats = JRN["stats"]
hdr = (f"{stats['total']} closed · {stats['wins']}W/{stats['losses']}L "
       f"({stats['win_rate']}%) · PnL {stats['total_pnl']:+,.2f}"
       if stats["total"] else "no closed trades yet")
st.markdown(f"<div class='tpanel' style='margin-top:8px'><div class='hd'>"
            f"<span>📕 TRADE JOURNAL — WHY EVERY TRADE CLOSED</span>"
            f"<span>{hdr}</span></div></div>", unsafe_allow_html=True)
if stats["total"]:
    for t in JRN["journal"][:12]:
        icon = "✅" if t["outcome"] == "WIN" else ("❌" if t["outcome"] == "LOSS" else "➖")
        rr = f"{t['r_multiple']:+}R" if t["r_multiple"] is not None else "--"
        with st.expander(
                f"{icon} {t['symbol']} {t['side']} · {t['outcome']} {t['pnl']:+,.2f} "
                f"({rr}) · {t['close_reason']} · held {t['held_human']} · "
                f"by {t['placed_by']}"):
            jc1, jc2, jc3, jc4, jc5 = st.columns(5)
            jc1.metric("ENTRY", fmt(t["entry_price"]))
            jc2.metric("EXIT", fmt(t["exit_price"]))
            jc3.metric("TP", fmt(t["tp"]))
            jc4.metric("SL", fmt(t["initial_sl"]))
            jc5.metric("PNL", f"{t['pnl']:+,.2f}")
            st.markdown(f"**Why closed:** {t['close_explanation']}"
                        + (" · 🛡 stop was at breakeven"
                           if t.get("sl_moved_to_breakeven") else ""))
            st.markdown(f"**Why entered** (conf {t['confidence_at_entry']}%):")
            for r in t.get("why_entered", []):
                st.markdown(f"- {r}")
            if t.get("member_votes_at_entry"):
                st.markdown("<div class='small'>votes ▸ " + " · ".join(
                    f"{k} {v:+.0f}" if v is not None else f"{k} --"
                    for k, v in t["member_votes_at_entry"].items()) + "</div>",
                    unsafe_allow_html=True)

# reference (collapsed, out of the way)
with st.expander("📖 INDICATOR & STRATEGY REFERENCE"):
    rc1, rc2 = st.columns(2)
    with rc1:
        for key, info in indicators.INDICATOR_INFO.items():
            st.markdown(f"**{info['name']}** — {info['what']}  \n"
                        f"<span class='small'>scoring: {info['how_scored']}</span>",
                        unsafe_allow_html=True)
    with rc2:
        for name, desc in indicators.STRATEGY_INFO.items():
            st.markdown(f"**{name}** — {desc}")

if live:
    time.sleep(5)
    st.rerun()

"""
FastAPI server: dashboard UI + REST API + MT5/TradingView bridge.

Endpoints:
  GET  /                     dashboard UI
  GET  /api/market           live quotes for the whole watchlist
  GET  /api/status           engine + broker + jarvis status
  GET  /api/analysis         latest council verdicts for all assets
  POST /api/analyze/{symbol} force a full AI-council analysis (asks Gemini+Groq+Jarvis)
  GET  /api/news             latest scraped headlines + economic calendar
  GET  /api/logs             engine logs
  POST /api/close/{pid}      manually close a paper position
  POST /api/settings         update auto_trade / min_confidence / risk
  GET  /mt5/commands         MT5 EA polls this to receive live orders
  POST /webhook/tradingview  TradingView alerts can push signals here
"""
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import config, council, news, trader

app = FastAPI(title="Jarvis Trader")
ENGINE = trader.ENGINE


@app.on_event("startup")
def _startup():
    ENGINE.start()


@app.get("/api/market")
def api_market():
    with ENGINE.lock:
        return {"market": list(ENGINE.market.values()), "ts": time.time()}


@app.get("/api/status")
def api_status():
    return ENGINE.status()


@app.get("/api/analysis")
def api_analysis():
    with ENGINE.lock:
        return {"analysis": ENGINE.last_analysis}


@app.post("/api/analyze/{symbol}")
def api_analyze(symbol: str):
    asset = next((a for a in config.WATCHLIST if a["symbol"] == symbol), None)
    if not asset:
        return JSONResponse({"error": "unknown symbol"}, status_code=404)
    verdict = council.analyze(asset, use_llms=True)
    with ENGINE.lock:
        ENGINE.last_analysis[symbol] = verdict
    return verdict


@app.get("/api/news")
def api_news():
    # refresh in the background; serve whatever we have instantly
    import threading as _t
    _t.Thread(target=news.ENGINE.refresh, daemon=True).start()
    with news.ENGINE.lock:
        return {"headlines": news.ENGINE.headlines[:60],
                "calendar_high_impact": news.ENGINE.high_impact_soon(),
                "sources_ok": news.ENGINE.sources_ok,
                "sources_fail": news.ENGINE.sources_fail}


@app.get("/api/signals")
def api_signals():
    """Every trade setup the bot scanned from the live market - click to place."""
    return ENGINE.get_signals()


@app.post("/api/place/{symbol}")
def api_place(symbol: str):
    """YOU clicked a signal -> place the trade with its TP/SL."""
    res = ENGINE.place_trade(symbol, source="manual click")
    code = 200 if res.get("ok") else 400
    return JSONResponse(res, status_code=code)


@app.get("/api/journal")
def api_journal():
    """Closed-trade journal: entry, TP, SL, exit, why it closed, stats."""
    return ENGINE.get_journal()


@app.get("/api/logs")
def api_logs():
    with ENGINE.lock:
        return {"logs": ENGINE.logs[-120:][::-1]}


@app.post("/api/close/{pid}")
def api_close(pid: str):
    ok = ENGINE.manual_close(pid)
    return {"closed": bool(ok)}


@app.post("/api/settings")
async def api_settings(req: Request):
    body = await req.json()
    if "auto_trade" in body:
        ENGINE.auto_trade = bool(body["auto_trade"])
    if "min_confidence" in body:
        ENGINE.min_conf = float(body["min_confidence"])
    if "risk_pct" in body:
        ENGINE.risk_pct = float(body["risk_pct"])
    ENGINE.log(f"Settings updated: auto_trade={ENGINE.auto_trade} "
               f"min_conf={ENGINE.min_conf} risk={ENGINE.risk_pct}%")
    return {"ok": True}


# ------------------------------------------------------------------ #
#  External executor bridges
# ------------------------------------------------------------------ #

@app.get("/mt5/commands")
def mt5_commands():
    """Your MT5 Expert Advisor polls this endpoint; each command is delivered once."""
    return {"commands": ENGINE.pending_commands()}


@app.post("/webhook/tradingview")
async def tradingview_webhook(req: Request):
    """Point TradingView alerts here. Body example:
    {"symbol":"BTCUSDT","side":"BUY","note":"strategy X fired"}"""
    try:
        body = await req.json()
    except Exception:
        body = {"raw": (await req.body()).decode()[:400]}
    ENGINE.log(f"TradingView webhook: {json.dumps(body)[:200]}")
    return {"ok": True}


# ------------------------------------------------------------------ #
#  Dashboard
# ------------------------------------------------------------------ #

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>JARVIS TRADER</title>
<style>
:root{
  --bg:#06090f; --panel:#0c1220; --panel2:#101a2e; --border:#1c2a44;
  --txt:#d7e3f4; --dim:#5f7290; --green:#22d37e; --red:#ff4d67;
  --cyan:#37c8f5; --gold:#f5b83d; --purple:#a78bfa;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:13px/1.45 'Segoe UI',system-ui,sans-serif;padding:14px}
h1{font-size:19px;letter-spacing:2px;color:var(--cyan)}
h1 span{color:var(--gold)}
.sub{color:var(--dim);font-size:11px;margin-top:2px}
.grid{display:grid;grid-template-columns:1.15fr 1.5fr 1fr;gap:12px;margin-top:12px}
@media(max-width:1100px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px;overflow:hidden}
.panel h2{font-size:11px;letter-spacing:1.5px;color:var(--dim);text-transform:uppercase;margin-bottom:8px;
  display:flex;justify-content:space-between;align-items:center}
table{width:100%;border-collapse:collapse}
td,th{padding:4px 6px;text-align:left;font-size:12px;border-bottom:1px solid #131e33}
th{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:1px}
.up{color:var(--green)} .down{color:var(--red)}
.tag{font-size:9px;padding:1px 6px;border-radius:8px;border:1px solid var(--border);color:var(--dim)}
.row{cursor:pointer} .row:hover{background:var(--panel2)}
.row.sel{background:#12203a}
.bar-wrap{background:#111c30;border-radius:4px;height:8px;position:relative;overflow:hidden}
.bar{position:absolute;top:0;bottom:0}
.member{display:flex;align-items:center;gap:8px;margin:5px 0}
.member .nm{width:86px;font-size:11px;color:var(--dim)}
.member .sc{width:44px;text-align:right;font-weight:600;font-size:12px}
.big{font-size:26px;font-weight:700}
.btn{background:var(--panel2);border:1px solid var(--border);color:var(--txt);border-radius:6px;
  padding:5px 12px;font-size:11px;cursor:pointer}
.btn:hover{border-color:var(--cyan)}
.btn.primary{background:#0b2d46;border-color:var(--cyan);color:var(--cyan)}
.pill{display:inline-block;padding:2px 10px;border-radius:12px;font-weight:700;font-size:12px}
.pill.UP{background:#0a2e1f;color:var(--green);border:1px solid #14563a}
.pill.DOWN{background:#331119;color:var(--red);border:1px solid #5d2130}
.news-item{padding:5px 0;border-bottom:1px solid #131e33;font-size:11.5px}
.news-item .src{color:var(--dim);font-size:10px}
.log{font:10.5px/1.5 monospace;color:#8aa2c5;max-height:180px;overflow-y:auto;white-space:pre-wrap}
.stat{display:inline-block;margin-right:16px}
.stat .v{font-size:16px;font-weight:700}.stat .l{font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:1px}
.flex{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input[type=number]{background:var(--panel2);border:1px solid var(--border);color:var(--txt);
  border-radius:5px;padding:4px 6px;width:64px;font-size:12px}
.switch{cursor:pointer;user-select:none}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px}
.plan td{font-size:11.5px}
.reason{font-size:10.5px;color:var(--dim);font-style:italic;margin-top:2px}
.scroll{max-height:320px;overflow-y:auto}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:#22304d;border-radius:4px}
.sim-warn{background:#3a2a08;border:1px solid #6b5216;color:var(--gold);padding:6px 10px;
  border-radius:8px;font-size:11px;margin-top:8px;display:none}
</style>
</head>
<body>
<div class="flex" style="justify-content:space-between">
  <div>
    <h1>J.A.R.V.I.S <span>TRADER</span></h1>
    <div class="sub">AI Council: Jarvis ML &bull; Gemini &bull; Groq &bull; Indicators &bull; Strategies &bull; News &mdash; auto trades with TP/SL</div>
  </div>
  <div class="panel" style="padding:8px 14px">
    <span class="stat"><div class="v" id="balance">--</div><div class="l">Balance</div></span>
    <span class="stat"><div class="v" id="equity">--</div><div class="l">Equity</div></span>
    <span class="stat"><div class="v" id="jarvisAcc">--</div><div class="l">Jarvis Acc.</div></span>
    <span class="stat"><div class="v" id="jarvisN">--</div><div class="l">Samples</div></span>
  </div>
</div>
<div class="sim-warn" id="simWarn">&#9888; Some feeds are SIMULATED (real market APIs unreachable from this sandbox). Run locally for true live data.</div>

<div class="grid">
  <!-- LEFT: watchlist -->
  <div class="panel">
    <h2>Live Markets <span class="tag" id="mktCount">--</span></h2>
    <div class="scroll">
    <table id="mktTable">
      <thead><tr><th>Asset</th><th>Type</th><th>Price</th><th>Chg%</th><th>Verdict</th><th>Live Pattern</th></tr></thead>
      <tbody></tbody>
    </table>
    </div>
    <h2 style="margin-top:12px">Settings</h2>
    <div class="flex">
      <label class="switch"><input type="checkbox" id="autoTrade"/> Auto-trade</label>
      <label>Min conf <input type="number" id="minConf" step="5" min="0" max="100"/></label>
      <label>Risk % <input type="number" id="riskPct" step="0.5" min="0.1" max="5"/></label>
      <button class="btn" onclick="saveSettings()">Save</button>
    </div>
    <h2 style="margin-top:12px">Engine Log</h2>
    <div class="log" id="log"></div>
  </div>

  <!-- MIDDLE: council -->
  <div class="panel">
    <h2>AI Council &mdash; <span id="selName" style="color:var(--cyan)">select an asset</span>
      <button class="btn primary" onclick="askCouncil()" id="askBtn">ASK THE COUNCIL</button></h2>
    <div id="councilBody"><div class="sub">Click an asset on the left, then press ASK THE COUNCIL to query Jarvis + Gemini + Groq + indicators + strategies + news in detail.</div></div>
  </div>

  <!-- RIGHT: signals + positions + news -->
  <div class="panel">
    <h2>&#9889; Scanned Trade Signals <span class="tag" id="sigCount">--</span></h2>
    <div class="sub" style="margin-bottom:6px">Every setup the bot found in the live market. <b style="color:var(--gold)">Click PLACE to take the trade.</b></div>
    <div id="signals" class="scroll" style="max-height:270px"></div>
    <h2 style="margin-top:10px">Open Positions <span class="tag" id="posCount">0</span></h2>
    <div id="positions" class="scroll" style="max-height:180px"></div>
    <h2 style="margin-top:10px">Live News <span class="tag" id="newsCount">--</span></h2>
    <div id="newsList" class="scroll" style="max-height:170px"></div>
  </div>
</div>

<!-- TRADE JOURNAL: full-width bottom panel -->
<div class="panel" style="margin-top:12px">
  <h2>&#128218; Trade Journal - why every trade closed <span class="tag" id="jrnStats">--</span></h2>
  <div id="journal"></div>
</div>

<script>
let selected=null, analysis={};
const $=id=>document.getElementById(id);
const fmt=(x,d)=>x==null?'--':Number(x).toLocaleString(undefined,{maximumFractionDigits:d??5});

async function jget(u){const r=await fetch(u);return r.json();}
async function jpost(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null});return r.json();}

function memberBar(name,score,detail){
  if(score===null||score===undefined){
    return `<div class="member"><div class="nm">${name}</div><div style="color:var(--dim);font-size:10px">no vote ${detail&&detail.error?('('+detail.error.slice(0,42)+')'):''}</div></div>`;
  }
  const pct=Math.min(100,Math.abs(score));
  const col=score>=0?'var(--green)':'var(--red)';
  const left=score>=0?'50%':(50-pct/2)+'%';
  return `<div class="member"><div class="nm">${name}</div>
    <div class="bar-wrap" style="flex:1"><div class="bar" style="left:${left};width:${pct/2}%;background:${col}"></div>
    <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#2a3c5e"></div></div>
    <div class="sc" style="color:${col}">${score>0?'+':''}${Math.round(score)}</div></div>`;
}

function renderCouncil(a){
  if(!a){$('councilBody').innerHTML='<div class="sub">No analysis yet.</div>';return;}
  const v=a.verdict;
  const col=v.direction==='UP'?'var(--green)':'var(--red)';
  const m=a.members||{};
  const names={indicators:'INDICATORS',strategies:'STRATEGIES',patterns:'PATTERNS',news:'NEWS',jarvis:'JARVIS ML',gemini:'GEMINI',groq:'GROQ'};
  let bars='';
  for(const k of ['jarvis','gemini','groq','indicators','strategies','patterns','news']){
    if(m[k])bars+=memberBar(names[k],m[k].score,m[k].detail);
  }
  let patHtml='';
  if(m.patterns&&m.patterns.detail&&m.patterns.detail.found&&m.patterns.detail.found.length){
    const pf=m.patterns.detail.found;
    patHtml=`<h2 style="margin-top:10px">Patterns Detected Live <span class="tag">${m.patterns.detail.bullish}&#9650; / ${m.patterns.detail.bearish}&#9660;</span></h2>
      <div class="scroll" style="max-height:130px">`+pf.map(p=>{
        const pc=p.score>0?'var(--green)':p.score<0?'var(--red)':'var(--dim)';
        return `<div style="padding:3px 0;border-bottom:1px solid #131e33;font-size:11px">
          <span style="color:${pc};font-weight:600">${p.score>0?'&#9650;':p.score<0?'&#9660;':'&#9654;'} ${p.name}</span>
          <span class="sub">${p.bars_ago?p.bars_ago+' bars ago':'now'}${p.note?' - '+p.note:''}</span>
          <span style="float:right;color:${pc}">${p.score>0?'+':''}${Math.round(p.score)}</span></div>`;
      }).join('')+'</div>';
  }
  let reasons='';
  if(m.gemini&&m.gemini.detail&&m.gemini.detail.reason)reasons+=`<div class="reason">Gemini: ${m.gemini.detail.reason}</div>`;
  if(m.groq&&m.groq.detail&&m.groq.detail.reason)reasons+=`<div class="reason">Groq: ${m.groq.detail.reason}</div>`;
  if(m.news&&m.news.detail&&m.news.detail.titles&&m.news.detail.titles.length)
    reasons+=`<div class="reason">News: ${m.news.detail.titles[0]}</div>`;
  const p=a.plan||{};
  let abcdHtml='';
  if(a.abcd){
    const ab=a.abcd;
    const acol=ab.direction==='bullish'?'var(--green)':'var(--red)';
    abcdHtml=`<h2 style="margin-top:10px">A-B-C &rarr; D Projection <span class="tag" style="color:${acol}">${ab.direction}</span></h2>
      <table class="plan"><tr><th>A</th><th>B</th><th>C</th><th>D = (B&times;C)&divide;A</th></tr>
      <tr><td>${fmt(ab.A)}</td><td>${fmt(ab.B)}</td><td>${fmt(ab.C)}</td>
      <td style="color:${acol};font-weight:700">${fmt(ab.D)}</td></tr></table>
      <div class="sub" style="margin-top:3px">projected reaction/target level from live swing structure - needs price-action confirmation</div>`;
  }
  $('councilBody').innerHTML=`
    <div class="flex" style="justify-content:space-between;margin-bottom:8px">
      <div><span class="pill ${v.direction}">${v.direction}</span>
        <span class="big" style="color:${col};margin-left:8px">${v.score>0?'+':''}${v.score}</span>
        <span class="sub">confidence ${v.confidence}%</span></div>
      <div class="sub">price ${fmt(a.price)} &bull; src: ${a.data_source} &bull; ${a.elapsed_sec}s</div>
    </div>
    ${bars}${reasons}${patHtml}${abcdHtml}
    <h2 style="margin-top:10px">Auto Trade Plan</h2>
    <table class="plan"><tr><th>Entry</th><th>Take Profit</th><th>Stop Loss</th><th>R:R</th></tr>
    <tr><td>${fmt(p.entry)}</td><td class="up">${fmt(p.tp)}</td><td class="down">${fmt(p.sl)}</td><td>${p.rr}:1</td></tr></table>
    <div class="sub" style="margin-top:3px">TP from: ${p.tp_source||'ATR x2R'}</div>
    <div class="sub" style="margin-top:6px">Jarvis: ${m.jarvis?.detail?.samples_trained??'--'} samples trained,
      ${m.jarvis?.detail?.live_feedback??0} live feedbacks${m.jarvis?.detail?.accuracy?(', accuracy '+m.jarvis.detail.accuracy+'%'):''}</div>`;
}

async function askCouncil(){
  if(!selected)return alert('Select an asset first');
  $('askBtn').textContent='ASKING ALL MODELS...';$('askBtn').disabled=true;
  try{const a=await jpost('/api/analyze/'+selected);analysis[selected]=a;renderCouncil(a);}
  catch(e){alert('analysis failed: '+e)}
  $('askBtn').textContent='ASK THE COUNCIL';$('askBtn').disabled=false;
}

function selectAsset(sym,name){
  selected=sym;$('selName').textContent=name+' ('+sym+')';
  renderCouncil(analysis[sym]);
  document.querySelectorAll('.row').forEach(r=>r.classList.toggle('sel',r.dataset.sym===sym));
}

async function refreshMarket(){
  const d=await jget('/api/market');
  const rows=d.market.sort((a,b)=>a.type.localeCompare(b.type)||a.symbol.localeCompare(b.symbol));
  $('mktCount').textContent=rows.length+' assets';
  let sim=false;
  $('mktTable').querySelector('tbody').innerHTML=rows.map(m=>{
    if(m.source==='SIMULATED')sim=true;
    const a=analysis[m.symbol];const v=a?a.verdict:null;
    let pat='<span class="sub">--</span>';
    const pf=a&&a.members&&a.members.patterns&&a.members.patterns.detail&&a.members.patterns.detail.found;
    if(pf&&pf.length){
      const p=pf[0];const pc=p.score>0?'var(--green)':p.score<0?'var(--red)':'var(--dim)';
      pat=`<span style="color:${pc};font-size:10px">${p.score>0?'&#9650;':p.score<0?'&#9660;':'&#9654;'} ${p.name}</span>`;
    }
    return `<tr class="row ${m.symbol===selected?'sel':''}" data-sym="${m.symbol}" onclick="selectAsset('${m.symbol}','${m.name}')">
      <td><span class="dot" style="background:${m.tick==='up'?'var(--green)':'var(--red)'}"></span>${m.name}</td>
      <td><span class="tag">${m.type}</span></td>
      <td>${fmt(m.price)}</td>
      <td class="${m.change_pct>=0?'up':'down'}">${m.change_pct>=0?'+':''}${m.change_pct}%</td>
      <td>${v?`<span class="pill ${v.direction}" style="font-size:10px">${v.direction} ${Math.round(v.confidence)}</span>`:'<span class="sub">--</span>'}</td>
      <td>${pat}</td></tr>`;
  }).join('');
  $('simWarn').style.display=sim?'block':'none';
}

async function refreshAnalysis(){
  const d=await jget('/api/analysis');
  analysis=d.analysis||{};
  if(selected&&analysis[selected])renderCouncil(analysis[selected]);
}

async function refreshStatus(){
  const s=await jget('/api/status');
  $('balance').textContent='$'+fmt(s.balance,2);
  $('equity').textContent='$'+fmt(s.equity,2);
  $('equity').style.color=s.equity>=s.balance?'var(--green)':'var(--red)';
  $('jarvisAcc').textContent=s.jarvis.accuracy!=null?s.jarvis.accuracy+'%':(s.jarvis.bootstrapping?'training...':'--');
  $('jarvisN').textContent=s.jarvis.samples_trained+(s.jarvis.pending_predictions?(' (+'+s.jarvis.pending_predictions+' live)'):'');
  if(document.activeElement.tagName!=='INPUT'){
    $('autoTrade').checked=s.auto_trade;$('minConf').value=s.min_confidence;$('riskPct').value=s.risk_pct;
  }
  $('posCount').textContent=s.open_positions.length;
  $('positions').innerHTML=s.open_positions.length?s.open_positions.map(p=>`
    <div style="padding:5px 0;border-bottom:1px solid #131e33">
      <b class="${p.side==='BUY'?'up':'down'}">${p.side}</b> ${p.symbol}
      <span class="sub">@ ${fmt(p.entry)}</span>
      <span style="float:right" class="${p.pnl>=0?'up':'down'}">${p.pnl>=0?'+':''}${fmt(p.pnl,2)}</span><br>
      <span class="sub">TP ${fmt(p.tp)} &bull; SL ${fmt(p.sl)}${p.be_moved?' (BE)':''}</span>
      <button class="btn" style="float:right;padding:1px 7px;font-size:9px" onclick="closePos('${p.id}')">close</button>
    </div>`).join(''):'<div class="sub">no open positions</div>';
}

async function refreshSignals(){
  const d=await jget('/api/signals');
  const waiting=d.signals.filter(s=>s.status==='waiting');
  $('sigCount').textContent=waiting.length+' waiting / '+d.total_scanned+' scanned total';
  $('signals').innerHTML=d.signals.length?d.signals.map(s=>{
    const col=s.side==='BUY'?'var(--green)':'var(--red)';
    const secs=Math.max(0,Math.round(s.expires-Date.now()/1000));
    const stat=s.status==='waiting'
      ?`<button class="btn primary" style="font-weight:700" onclick="placeTrade('${s.symbol}',this)">&#9658; PLACE</button>
        <span class="sub">${Math.floor(secs/60)}m${secs%60}s left</span>`
      :s.status==='placed'
      ?'<span class="tag" style="color:var(--green);border-color:var(--green)">PLACED</span>'
      :'<span class="tag">EXPIRED</span>';
    const why=(s.reasons||[]).slice(0,2).map(r=>`<div class="reason">&bull; ${r}</div>`).join('');
    return `<div style="padding:6px 0;border-bottom:1px solid #131e33;${s.status!=='waiting'?'opacity:.55':''}">
      <b style="color:${col}">${s.side}</b> <b>${s.symbol}</b>
      <span class="tag">${s.type}</span>
      <span class="sub">conf ${Math.round(s.confidence)}%</span>
      <span style="float:right">${stat}</span><br>
      <span class="sub">Entry ${fmt(s.entry)} &bull; <span class="up">TP ${fmt(s.tp)}</span> &bull;
      <span class="down">SL ${fmt(s.sl)}</span> &bull; R:R ${s.rr??'--'}</span>
      ${why}</div>`;
  }).join(''):'<div class="sub">scanning live market... signals appear here when confidence &ge; threshold</div>';
}

async function placeTrade(sym,btn){
  btn.textContent='PLACING...';btn.disabled=true;
  const r=await fetch('/api/place/'+sym,{method:'POST'});
  const d=await r.json();
  if(d.ok){btn.textContent='&#10003; PLACED';}
  else{alert('Could not place: '+d.error);btn.textContent='&#9658; PLACE';btn.disabled=false;}
  refreshSignals();refreshStatus();
}

async function refreshJournal(){
  const d=await jget('/api/journal');
  const st=d.stats;
  $('jrnStats').textContent=st.total?`${st.total} trades &bull; ${st.wins}W/${st.losses}L (${st.win_rate}%) &bull; PnL ${st.total_pnl>=0?'+':''}${st.total_pnl}`:'no closed trades yet';
  $('jrnStats').innerHTML=$('jrnStats').textContent;
  $('journal').innerHTML=d.journal.length?`
    <table><thead><tr><th>Closed</th><th>Symbol</th><th>Side</th><th>Outcome</th><th>Entry</th>
    <th>Exit</th><th>TP</th><th>SL</th><th>PnL</th><th>R</th><th>Held</th><th>Why it closed</th><th>Placed by</th></tr></thead>
    <tbody>`+d.journal.map(j=>{
      const oc=j.outcome==='WIN'?'up':j.outcome==='LOSS'?'down':'';
      const rc=j.close_reason==='TP hit'?'up':(j.close_reason==='SL hit'?'down':'');
      return `<tr class="row" onclick="toggleJrn('${j.id}')">
        <td class="sub">${new Date(j.closed_at*1000).toLocaleTimeString()}</td>
        <td><b>${j.symbol}</b></td>
        <td class="${j.side==='BUY'?'up':'down'}">${j.side}</td>
        <td class="${oc}" style="font-weight:700">${j.outcome}</td>
        <td>${fmt(j.entry_price)}</td><td>${fmt(j.exit_price)}</td>
        <td class="up">${fmt(j.tp)}</td><td class="down">${fmt(j.initial_sl)}</td>
        <td class="${j.pnl>=0?'up':'down'}">${j.pnl>=0?'+':''}${fmt(j.pnl,2)}</td>
        <td>${j.r_multiple!=null?(j.r_multiple>=0?'+':'')+j.r_multiple+'R':'--'}</td>
        <td class="sub">${j.held_human}</td>
        <td class="${rc}">${j.close_reason}${j.sl_moved_to_breakeven?' <span class="tag">BE</span>':''}</td>
        <td class="sub">${j.placed_by}</td></tr>
      <tr id="jrn-${j.id}" style="display:none"><td colspan="13" style="background:var(--panel2)">
        <div style="padding:6px 10px">
          <div class="sub" style="margin-bottom:4px"><b style="color:var(--cyan)">Close explanation:</b> ${j.close_explanation}</div>
          <div class="sub"><b style="color:var(--cyan)">Why it was entered</b> (conf ${j.confidence_at_entry}%, council score ${j.council_score_at_entry}):</div>
          ${(j.why_entered||[]).map(r=>`<div class="reason">&bull; ${r}</div>`).join('')||'<div class="sub">-</div>'}
          <div class="sub" style="margin-top:4px"><b style="color:var(--cyan)">Votes at entry:</b> ${j.member_votes_at_entry?Object.entries(j.member_votes_at_entry).map(([k,v])=>`${k}: ${v==null?'--':(v>0?'+':'')+Math.round(v)}`).join(' &bull; '):'-'}</div>
        </div></td></tr>`;
    }).join('')+'</tbody></table>'
    :'<div class="sub">Closed trades will appear here with the full story: entry, TP, SL, exit price, PnL, R-multiple, hold time, and exactly WHY the trade closed (TP hit / SL hit / breakeven stop / timeout / manual).</div>';
}
function toggleJrn(id){const r=document.getElementById('jrn-'+id);if(r)r.style.display=r.style.display==='none'?'':'none';}

async function refreshNews(){
  try{
    const d=await jget('/api/news');
    $('newsCount').textContent=d.headlines.length+' from '+d.sources_ok.length+' sources';
    $('newsList').innerHTML=d.headlines.slice(0,25).map(h=>{
      const c=h.sentiment>0.05?'var(--green)':h.sentiment<-0.05?'var(--red)':'var(--dim)';
      return `<div class="news-item"><span style="color:${c}">&#9679;</span> ${h.title}
        <div class="src">${h.source}</div></div>`;}).join('')||'<div class="sub">no headlines (sources unreachable)</div>';
  }catch(e){}
}

async function refreshLogs(){
  const d=await jget('/api/logs');
  $('log').textContent=d.logs.map(l=>new Date(l.ts*1000).toLocaleTimeString()+' '+l.msg).join('\n');
}

async function saveSettings(){
  await jpost('/api/settings',{auto_trade:$('autoTrade').checked,
    min_confidence:parseFloat($('minConf').value),risk_pct:parseFloat($('riskPct').value)});
}
async function closePos(id){await jpost('/api/close/'+id);refreshStatus();}

refreshMarket();refreshStatus();refreshNews();refreshLogs();refreshAnalysis();refreshSignals();refreshJournal();
setInterval(refreshMarket,4000);
setInterval(refreshStatus,4000);
setInterval(refreshAnalysis,9000);
setInterval(refreshSignals,5000);
setInterval(refreshJournal,8000);
setInterval(refreshLogs,6000);
setInterval(refreshNews,60000);
</script>
</body>
</html>
"""

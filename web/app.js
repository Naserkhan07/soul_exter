/* =============================================================================
   SOUL EXTER — floor controller
   Wires the /ws event stream into the 3D floor, the HUD and the transcript.
   Falls back to SSE (/api/stream) and then to polling (/api/state) so the
   floor still runs behind proxies that dislike websockets.
   ========================================================================== */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const money = (v) => (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const shortModel = (m) => (m || "mock").replace(/^.*\//, "");
  const pct = (v) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";

  const state = {
    cfg: null, registry: {}, cabins: [], ceo: null,
    desk: {}, market: {}, council: {},
    equity_curve: [], trades: new Map(), sockets: null, mode: "ws",
    lastTick: 0, seen: new Set(),
  };

  const floor = new window.SoulFloor($("floor"));
  window.floor = floor;

  // ── connection ─────────────────────────────────────────────────────────
  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    let ws;
    try { ws = new WebSocket(`${proto}//${location.host}/ws`); } catch (e) { return fallbackSSE(); }
    let opened = false;
    const guard = setTimeout(() => { if (!opened) { try { ws.close(); } catch (e) {} fallbackSSE(); } }, 3500);

    ws.onopen = () => { opened = true; clearTimeout(guard); state.mode = "ws"; badge("badge-scan", "scan: idle"); };
    ws.onmessage = (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      handle(msg);
    };
    ws.onclose = () => { if (opened) { setTimeout(connect, 1500); } };
    ws.onerror = () => { if (!opened) { clearTimeout(guard); try { ws.close(); } catch (e) {} fallbackSSE(); } };
  }

  function fallbackSSE() {
    if (state.mode === "sse") return;
    state.mode = "sse";
    try {
      const es = new EventSource("/api/stream");
      es.onmessage = (ev) => { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } handle(m); };
      es.onerror = () => { es.close(); setTimeout(poll, 800); };
    } catch (e) { poll(); }
  }

  async function poll() {
    if (state.mode !== "poll") { state.mode = "poll"; }
    try {
      const r = await fetch("/api/state");
      const s = await r.json();
      applyState(s);
    } catch (e) { /* keep trying */ }
    setTimeout(poll, 1800);
  }

  // ── event handling ─────────────────────────────────────────────────────
  function handle(msg) {
    const t = msg.type, p = msg.payload || {};
    if (t === "trader_walks" || t === "cabin_verdict") floor.cabinThinking(p.to || p.cabin);
    switch (t) {
      case "hello":
        applyState(p.state);
        (p.recent || []).forEach((e) => { if (e.type !== "hello") handle(e); });
        boot(false);
        break;
      case "ping": break;

      case "tick":
        floor.setBoard(p.board);
        state.lastTick = Date.now();
        updatePrices(p.board);
        if (p.equity != null) updateEquity(p.equity);
        break;

      case "scan":
        badge("badge-scan", `scan: #${p.scan_index} · ${p.count} found`);
        if (p.count) feed("scan", `scanner returned ${p.count} candidate${p.count > 1 ? "s" : ""}`, (p.symbols || []).join(" "), "");
        break;

      case "trader_spawned":
        floor.spawn(p.trade);
        state.trades.set(p.trade.id, { brief: p.trade, verdicts: [], ceo: null });
        feed("spawn", `<span class="sym">${p.trade.symbol.replace("/USDT", "")}</span> ${p.trade.side} · ${p.trade.strategy} · ${p.trade.rr.toFixed(2)}R walking to the cabins`, "", "mid");
        break;

      case "trader_walks":
        if (p.to) floor.moveTo(p.trade_id, p.to);
        if (p.to && p.to !== "CEO") cabinCard(p.to, { status: "thinking" });
        if (p.to === "CEO") cabinCard("CEO", { status: "thinking" });
        break;

      case "cabin_verdict": {
        floor.cabinVote(p.cabin, p);
        cabinCard(p.cabin, p);
        const tr = state.trades.get(p.trade_id);
        if (tr) tr.verdicts.push(p);
        const tally = `${p.approvals}/${p.approvals + p.rejections + (p.remaining || 0)}`;
        feed("verdict",
          `<span class="sym">${p.symbol.replace("/USDT", "")}</span> ${p.label}`,
          `<span class="tag ${p.verdict === "APPROVE" ? "ok" : "bad"}">${p.verdict} ${Math.round(p.confidence)}%</span>`,
          p.verdict === "APPROVE" ? "ok" : "bad", p.reason);
        break;
      }

      case "council_done":
        feed("council",
          `<span class="sym">${p.symbol.replace("/USDT", "")}</span> council ${p.approvals}–${p.rejections}`,
          p.route === "ESCALATED" ? `<span class="tag mid">to CEO</span>` : `<span class="tag ${p.route === "FINALIZED" ? "ok" : "bad"}">${p.route}</span>`, "");
        break;

      case "escalated":
        cabinCard("CEO", { status: "thinking" });
        feed("ceo", `<span class="sym">${p.symbol.replace("/USDT", "")}</span> split council — walking up to the CEO`, `<span class="tag mid">${p.approvals}–${p.rejections}</span>`, "mid");
        break;

      case "ceo_verdict":
        floor.cabinVote("CEO", p);
        cabinCard("CEO", p);
        feed("ceo", `CEO on <span class="sym">${p.symbol.replace("/USDT", "")}</span>: ${p.reason}`, `<span class="tag ${p.verdict === "APPROVE" ? "ok" : "bad"}">${p.verdict} ${Math.round(p.confidence)}%</span>`, p.verdict === "APPROVE" ? "ok" : "bad");
        break;

      case "entry_door":
        floor.endTrade(p.trade_id, "entry", p.decision, { text: "ENTRY", color: "#35d07f" });
        feed("door", `<span class="sym">${p.symbol.replace("/USDT", "")}</span> through the <b>entry door</b>`, `<span class="tag ok">${p.approvals}/5 ✓</span>`, "ok");
        break;

      case "exit_door":
        floor.endTrade(p.trade_id, "exit", p.decision, { text: "EXIT", color: "#ff5c62" });
        feed("door", `<span class="sym">${p.symbol.replace("/USDT", "")}</span> out the <b>exit door</b> — ${p.reason}`, `<span class="tag bad">${p.rejections}/5 ✗</span>`, "bad");
        break;

      case "council_result": {
        const tr = state.trades.get(p.trade.trade_id || p.trade.id) || {};
        tr.result = p;
        if (state.openDrawer === (p.trade.id)) renderDrawer(p);
        break;
      }

      case "position_opened":
        feed("fill", `desk filled <span class="sym">${p.symbol.replace("/USDT", "")}</span> ${p.side} · size ${money(p.size)} @ ${fmt(p.entry)}`,
          `<span class="tag ok">x${(p.size_multiplier || 1).toFixed(2)}</span>`, "ok");
        break;

      case "position_closed": {
        const win = p.pnl >= 0;
        floor.floatAtSeat(p.trade_id, `${win ? "+" : "-"}$${Math.abs(p.pnl).toFixed(2)}`, win ? "#35d07f" : "#ff5c62");
        feed("close", `closed <span class="sym">${p.symbol.replace("/USDT", "")}</span> (${p.exit_reason}) ${money(p.pnl)}`, `<span class="tag ${win ? "ok" : "bad"}">${pct((p.pnl / p.size) * 100)}</span>`, win ? "ok" : "bad");
        break;
      }

      case "order_blocked":
        feed("block", `<span class="sym">${p.symbol.replace("/USDT", "")}</span> approved but not filled: ${p.reason}`, `<span class="tag mid">blocked</span>`, "mid");
        break;

      case "market_shock":
        feed("shock", "operator injected volatility into the tape", "", "mid");
        break;

      case "error":
        feed("err", p.message || "engine error", `<span class="tag bad">error</span>`, "bad");
        break;
    }
  }

  const fmt = (v) => (v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : v >= 1 ? v.toFixed(4) : v.toFixed(5));

  // ── HUD ───────────────────────────────────────────────────────────────
  function badge(id, text) { const el = $(id); if (el) el.textContent = text; }

  function applyState(s) {
    if (!s) return;
    state.desk = s.desk || {};
    state.market = s.market || {};
    state.council = s.council || {};
    state.equity_curve = s.equity_curve || [];
    if (s.registry) { state.registry = s.registry; state.cabins = s.cabins || []; state.ceo = s.ceo; buildRoster(); }

    const e = s.engine || {};
    badge("badge-brains", `brains: ${e.llm_mode === "mock" ? "mock (no GPU)" : "local open-weights"} · ${e.model_profile}`);
    badge("badge-feed", `feed: ${(s.market && s.market.mode) === "live" ? "binance live" : "simulator"} · ${e.timeframe}`);
    $("badge-paused").classList.toggle("hidden", !e.paused);
    $("mkt-mode").textContent = (s.market && s.market.mode) || "…";
    $("mkt-tf").textContent = e.timeframe || "…";
    $("desk-count").textContent = e.desks || 0;
    if (!state.fixedScan) {
      $("rng-scan").value = Math.round(e.scan_seconds || 25);
      $("lbl-scan").textContent = Math.round(e.scan_seconds || 25);
      $("rng-score").value = (e.min_score != null ? e.min_score : 0.28);
      $("lbl-score").textContent = (e.min_score != null ? e.min_score : 0.28).toFixed(2);
      state.fixedScan = true;
    }
    if (s.market && s.market.board) { floor.setBoard(s.market.board); updatePrices(s.market.board); }
    updateDesk(s.desk, s.positions);
    updateEquity();
    const c = s.council || {};
    $("t-approved").textContent = c.finalized || 0;
    $("t-rejected").textContent = c.rejected || 0;
    $("t-escalated").textContent = c.escalated || 0;
    if (s.positions) renderPositions(s.positions);
    if (s.closed) state.closed = s.closed;
  }

  function updatePrices(board) {
    if (!board) return;
    board.forEach((b) => { state.market["p_" + b.symbol] = b; });
  }

  function updateDesk(d, positions) {
    if (!d) return;
    $("st-open").textContent = `${d.open_positions}/${d.max_positions}`;
    $("st-realised").textContent = money(d.realised_pnl || 0);
    $("st-openpnl").textContent = money(d.open_pnl || 0);
    $("st-winrate").textContent = d.closed ? Math.round((d.win_rate || 0) * 100) + "%" : "—";
    $("st-closed").textContent = d.closed || 0;
    $("st-risk").textContent = (d.planned_risk_pct || 0).toFixed(2) + "%";
    const rp = $("return-pct");
    rp.textContent = pct(d.return_pct || 0);
    rp.classList.toggle("neg", (d.return_pct || 0) < 0);
    updateEquity(d.equity);
  }

  function updateEquity(v) {
    if (v != null) state.lastEquity = v;
    const eq = state.lastEquity != null ? state.lastEquity : (state.desk.equity || 0);
    $("equity").textContent = money(eq);
    drawSpark();
  }

  function drawSpark() {
    const cv = $("spark");
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = cv.clientWidth, h = 54;
    cv.width = w * dpr; cv.height = h * dpr;
    const c = cv.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    const curve = state.equity_curve || [];
    const start = (state.desk && state.desk.starting_cash) || 15000;
    c.strokeStyle = "rgba(255,255,255,.10)";
    c.setLineDash([3, 4]);
    c.beginPath(); c.moveTo(0, h * 0.5); c.lineTo(w, h * 0.5); c.stroke();
    c.setLineDash([]);
    if (curve.length < 2) {
      c.fillStyle = "rgba(140,160,180,.5)";
      c.font = "10px ui-sans-serif,system-ui";
      c.fillText("waiting for the first fills…", 4, h / 2 - 6);
      return;
    }
    const vals = curve.map((p) => p.equity);
    let lo = Math.min(...vals, start), hi = Math.max(...vals, start);
    if (hi - lo < start * 0.0006) { hi += start * 0.0004; lo -= start * 0.0004; }
    const x = (i) => (i / (curve.length - 1)) * w;
    const y = (v) => h - 6 - ((v - lo) / (hi - lo)) * (h - 12);
    const up = vals[vals.length - 1] >= vals[0];
    const col = up ? "#35d07f" : "#ff5c62";
    const g = c.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, hexA(col, 0.35));
    g.addColorStop(1, hexA(col, 0.02));
    c.beginPath();
    c.moveTo(0, y(vals[0]));
    vals.forEach((v, i) => c.lineTo(x(i), y(v)));
    c.lineTo(w, h); c.lineTo(0, h); c.closePath();
    c.fillStyle = g; c.fill();
    c.beginPath();
    vals.forEach((v, i) => (i ? c.lineTo(x(i), y(v)) : c.moveTo(x(i), y(v))));
    c.strokeStyle = col; c.lineWidth = 1.6; c.stroke();
  }

  function renderPositions(positions) {
    const el = $("positions");
    if (!positions || !positions.length) { el.innerHTML = '<p class="mini" style="margin:0">no open positions</p>'; return; }
    el.innerHTML = positions.map((p) => {
      const up = p.pnl >= 0;
      return `<div class="pos ${p.side === "LONG" ? "long" : "short"}" data-trade="${p.trade_id}">
        <span class="sym">${p.symbol.replace("/USDT", "")} ${p.side === "LONG" ? "▲" : "▼"}</span>
        <span class="${up ? "up" : "down"}">${up ? "+" : ""}${p.pnl.toFixed(2)} (${p.pnl_pct.toFixed(2)}%)</span>
      </div>`;
    }).join("");
    el.querySelectorAll(".pos").forEach((n) => n.addEventListener("click", () => openDrawer(n.dataset.trade)));
  }

  function buildRoster() {
    const list = $("roster-list");
    const order = [...state.cabins, state.ceo].filter(Boolean);
    list.innerHTML = order.map((c) => `
      <div class="cabin-card ${c.is_ceo ? "ceo" : ""}" data-key="${c.key}">
        <div class="avatar" style="color:${color(c.key)}">${c.is_ceo ? "★" : c.key[0]}</div>
        <div class="meta">
          <div class="name"><span>${c.label}</span><span class="pill" data-role="pill">idle</span></div>
          <div class="model">${shortModel(c.model)} · ${c.backend}</div>
          <div class="bar"><i data-role="bar" style="background:${color(c.key)}"></i></div>
          <div class="reason" data-role="reason"></div>
        </div>
      </div>`).join("");
  }

  function color(key) { return (window.SoulLayout.CABIN_COLORS[key]) || "#5ad2ff"; }

  function cabinCard(key, v) {
    const card = document.querySelector(`.cabin-card[data-key="${key}"]`);
    if (!card) return;
    const pill = card.querySelector('[data-role="pill"]');
    const bar = card.querySelector('[data-role="bar"]');
    const reason = card.querySelector('[data-role="reason"]');
    if (v.status === "thinking") {
      card.className = "cabin-card thinking" + (key === "CEO" ? " ceo" : "");
      pill.textContent = "thinking";
      pill.className = "pill";
      bar.style.width = "18%";
      bar.style.opacity = ".5";
      return;
    }
    const ok = v.verdict === "APPROVE";
    card.className = "cabin-card " + (ok ? "approve" : "reject") + (key === "CEO" ? " ceo" : "");
    pill.textContent = `${v.verdict} ${Math.round(v.confidence)}%`;
    pill.className = "pill " + (ok ? "ok" : "bad");
    bar.style.width = Math.max(4, Math.min(100, v.confidence)) + "%";
    bar.style.opacity = "1";
    bar.style.background = ok ? "#35d07f" : "#ff5c62";
    reason.textContent = v.reason || "";
    clearTimeout(card._t);
    card._t = setTimeout(() => card.classList.remove("expanded"), 9000);
    card.classList.add("expanded");
  }

  const feedList = $("feed-list");
  let feedCount = 0;
  function feed(kind, msg, tag, cls, detail) {
    feedCount++;
    $("feed-count").textContent = feedCount + " events";
    const li = document.createElement("li");
    const t = new Date().toLocaleTimeString("en-GB", { hour12: false });
    li.innerHTML = `<span class="t">${t}</span><span class="msg">${msg}</span>${tag || ""}`;
    if (detail) { li.title = detail; li.querySelector(".msg").title = detail; }
    feedList.prepend(li);
    while (feedList.children.length > 60) feedList.removeChild(feedList.lastChild);
  }

  // ── transcript drawer ─────────────────────────────────────────────────
  async function openDrawer(tradeId) {
    if (!tradeId) return;
    state.openDrawer = tradeId;
    $("drawer").classList.remove("hidden");
    $("drawer-body").innerHTML = '<p class="mini">loading transcript…</p>';
    try {
      const r = await fetch(`/api/trades/${tradeId}`);
      if (!r.ok) throw new Error("not found");
      renderDrawer(await r.json());
    } catch (e) {
      $("drawer-body").innerHTML = '<p class="mini">no transcript yet — the council is still deliberating.</p>';
    }
  }
  $("drawer-close").onclick = () => { $("drawer").classList.add("hidden"); state.openDrawer = null; };

  function renderDrawer(d) {
    const t = d.trade || {};
    const vs = d.verdicts || [];
    const ceo = d.ceo;
    const ok = (d.decision === "ENTER") || (ceo && ceo.verdict === "APPROVE");
    const head = `
      <h3>${t.symbol || ""} <span style="color:${(t.side === "LONG" ? "#35d07f" : "#ff5c62")}">${t.side || ""}</span></h3>
      <p class="sub">${t.strategy || ""} · ${t.timeframe || ""} · id ${t.id || d.trade_id || ""}</p>
      <div class="kv">
        <span>entry</span><b>${fmt(t.entry || 0)}</b>
        <span>stop</span><b>${fmt(t.stop || 0)} (${(t.risk_pct || 0).toFixed(2)}%)</b>
        <span>target</span><b>${fmt(t.target || 0)} (${(t.target_pct || 0).toFixed(2)}%)</b>
        <span>R:R</span><b>${(t.rr || 0).toFixed(2)}</b>
        <span>scanner score</span><b>${(t.score || 0).toFixed(2)}</b>
        <span>council</span><b>${d.approvals || 0}/5 approve → ${d.route || "?"}</b>
        <span>outcome</span><b style="color:${ok ? "#35d07f" : "#ff5c62"}">${ok ? "ENTRY DOOR — traded" : "EXIT DOOR — rejected"}</b>
      </div>`;
    const cards = vs.map((v) => `
      <div class="verdict ${v.verdict.toLowerCase()}">
        <div class="vhead"><span>${labelFor(v.cabin)} — ${v.verdict}</span><span>${Math.round(v.confidence)}%</span></div>
        <div class="vmeta">${shortModel(v.model)} · ${v.latency_ms}ms</div>
        <div class="conf-track"><i style="width:${Math.max(3, v.confidence)}%;background:${v.verdict === "APPROVE" ? "#35d07f" : "#ff5c62"}"></i></div>
        <p>${v.reason || ""}</p>
        ${(v.risk_flags && v.risk_flags.length) ? `<div class="flags">${v.risk_flags.map((f) => `<span class="flag">${f}</span>`).join("")}</div>` : ""}
      </div>`).join("");
    const ceoCard = ceo ? `
      <div class="verdict ${ceo.verdict.toLowerCase()}" style="border-color:#ffd166">
        <div class="vhead"><span>CEO — ${ceo.verdict}</span><span>${Math.round(ceo.confidence)}%</span></div>
        <div class="vmeta">${shortModel(ceo.model)} · final word</div>
        <p>${ceo.reason || ""}</p>
      </div>` : "";
    $("drawer-body").innerHTML = head + `<h4 style="margin:14px 0 8px;font-size:11px;letter-spacing:.14em;color:#8798ab">CABIN TRANSCRIPT</h4>` + (cards || '<p class="mini">council still voting…</p>') + ceoCard;
  }
  function labelFor(key) {
    const c = state.registry[key];
    return (c && c.label) || key;
  }

  floor.onPick = (hit) => { if (hit.kind === "trade") openDrawer(hit.id); };

  // ── controls ──────────────────────────────────────────────────────────
  async function post(url, body) {
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      return await r.json();
    } catch (e) { return null; }
  }

  $("btn-scan").onclick = () => { post("/api/scan"); feed("ctl", "operator forced a scan", "", ""); };
  $("btn-seed").onclick = () => { post("/api/demo/seed", { count: 3 }); feed("ctl", "operator queued 3 trades", "", ""); };
  $("btn-shock").onclick = () => post("/api/demo/shock");
  $("btn-flat").onclick = () => { post("/api/desk/close-all"); feed("ctl", "operator flattened the book", "", ""); };
  $("btn-pause").onclick = async (e) => {
    const r = await post("/api/control", { paused: !(state.council && state.paused) });
    const paused = r ? r.paused : false;
    state.paused = paused;
    e.target.textContent = paused ? "Resume" : "Pause";
    $("badge-paused").classList.toggle("hidden", !paused);
  };

  let scanTimer, scoreTimer;
  $("rng-scan").oninput = (e) => {
    const v = +e.target.value;
    $("lbl-scan").textContent = v;
    clearTimeout(scanTimer);
    scanTimer = setTimeout(() => post("/api/control", { scan_seconds: v }), 350);
  };
  $("rng-score").oninput = (e) => {
    const v = +e.target.value;
    $("lbl-score").textContent = v.toFixed(2);
    clearTimeout(scoreTimer);
    scoreTimer = setTimeout(() => post("/api/control", { min_score: v }), 350);
  };

  window.addEventListener("resize", () => { floor.resize(); drawSpark(); });

  // ── boot ──────────────────────────────────────────────────────────────
  function boot(on, text) {
    const el = $("boot");
    if (text) $("boot-text").textContent = text;
    el.classList.toggle("gone", !on);
  }

  (async function init() {
    boot(true, "Waking the floor…");
    try {
      const r = await fetch("/api/state");
      const s = await r.json();
      applyState(s);
      if (s.engine && s.engine.llm_mode === "mock") {
        boot(true, "No GPU detected — running mock brains. On Kaggle: SOUL_MOCK_LLM=0");
        setTimeout(() => boot(false), 2600);
      } else {
        boot(true, "Loading open-weight models into the cabins… (first run downloads weights)");
      }
    } catch (e) { boot(true, "Waiting for the engine…"); }
    connect();
  })();
})();

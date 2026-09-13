/* =============================================================================
   SOUL EXTER — isometric trading floor renderer (canvas 2D)
   -----------------------------------------------------------------------------
   Everything here is presentation. It only reacts to engine events:
       trader_spawned -> a trader stands up from a desk and walks to cabin 1
       trader_walks   -> the trader moves to the next cabin / CEO / door
       cabin_verdict  -> the cabin lights up and shows its vote
       entry_door / exit_door -> the trader walks to a door and leaves
   ========================================================================== */
(function () {
  "use strict";

  // ── projection ─────────────────────────────────────────────────────────
  const TILE = 40;        // world unit -> stage pixels (x/y)
  const ZUNIT = 22;       // world unit -> stage pixels (height)
  const ISO_X = 0.866;    // cos(30)
  const ISO_Y = 0.5;      // sin(30)

  const COL = {
    floorA: "#0a1017", floorB: "#0c141d", grid: "rgba(120,170,220,.055)",
    slabTop: "#c3cfdc", slabFront: "#95a3b3", slabSide: "#6f7d8c",
    monitor: "#111a24", monitorGlow: "#1d3348",
    glass: "rgba(150,205,255,.13)", glassTop: "rgba(180,225,255,.22)",
    ok: "#35d07f", bad: "#ff5c62", mid: "#ffc857", accent: "#5ad2ff",
    text: "#e8eef6", muted: "#7c8ea1",
  };

  const CABIN_COLORS = {
    QUANT: "#5ad2ff", RISK: "#ff7b72", NEWS: "#ffc857",
    MACRO: "#a78bfa", COMPLIANCE: "#34d399", CEO: "#ffd166",
  };
  const BODIES = ["#8b6bff", "#3aa0ff", "#ff8a3d", "#25c2a0", "#e35d8a", "#6156d6", "#ffd166", "#4fd1c5"];
  const HEADS = ["#f2c9a0", "#d9a173", "#a9714b", "#6f452b", "#f7dcc4", "#8d5a3b"];

  function rnd(seed) {                       // tiny deterministic PRNG
    let s = seed % 2147483647; if (s <= 0) s += 2147483646;
    return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  }
  function hash(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return Math.abs(h);
  }
  const lerp = (a, b, t) => a + (b - a) * t;

  // ── scene layout ───────────────────────────────────────────────────────
  const ROWS = 8, COLS = 8;
  const CABIN_ORDER = ["QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE"];
  const CABIN_LABEL = {
    QUANT: "QUANT", RISK: "RISK", NEWS: "NEWS", MACRO: "MACRO",
    COMPLIANCE: "COMPLIANCE", CEO: "CEO · HEAD OF DESK",
  };

  function buildLayout() {
    // Desk rows run left-to-right along +x. Row spacing is wide enough in y
    // that the iso projection keeps every row readable instead of collapsing
    // into one another.
    const ROW_GAP = 1.42, COL_GAP = 0.92, X0 = 0.4, Y0 = 0.6;
    const rows = [];
    const seats = [];
    for (let r = 0; r < ROWS; r++) {
      const y = Y0 + r * ROW_GAP;
      const xoff = (r % 2) * 0.2;
      const slab = { y, xoff, cx: X0 + xoff + (COLS - 1) * COL_GAP / 2, w: (COLS - 1) * COL_GAP + 0.9, d: 0.62 };
      rows.push(slab);
      for (let c = 0; c < COLS; c++) {
        seats.push({ x: X0 + c * COL_GAP + xoff, y, row: r, col: c });
      }
    }
    // Cabins climb the back wall: each one further right and further back, so
    // in iso they read as an ascending row of glass rooms over the floor.
    const cabins = {};
    CABIN_ORDER.forEach((key, i) => {
      cabins[key] = {
        key, x: 1.55 + i * 1.30, y: -1.15 - i * 1.22, z: 2.30 + i * 0.38,
        w: 1.45, d: 1.25, h: 1.0, color: CABIN_COLORS[key],
      };
    });
    cabins.CEO = { key: "CEO", x: 8.05, y: -7.6, z: 4.55, w: 2.0, d: 1.6, h: 1.2, color: CABIN_COLORS.CEO };
    const doors = {
      entry: { x: 8.75, y: 12.3, z: 0, color: COL.ok, label: "ENTRY" },
      exit: { x: -0.9, y: 12.3, z: 0, color: COL.bad, label: "EXIT" },
    };
    return { seats, rows, cabins, doors, bounds: { x0: -1.4, x1: 9.9, y0: -3.2, y1: Y0 + (ROWS - 1) * ROW_GAP + 1.0 } };
  }

  /** Extreme points of the scene, used to frame the whole floor on resize. */
  function layoutBounds(L) {
    const pts = [];
    const push = (x, y, z) => pts.push([x, y, z]);
    // floor corners
    push(-1.6, -1.4, 0); push(9.9, -1.4, 0); push(9.9, 9.2, 0); push(-1.6, 9.2, 0);
    Object.values(L.cabins).forEach((c) => {
      push(c.x - c.w / 2, c.y + c.d / 2, 0);
      push(c.x + c.w / 2, c.y - c.d / 2, c.z + c.h + 0.5);
    });
    Object.values(L.doors).forEach((d) => push(d.x, d.y, 0.9));
    return pts;
  }

  // ── the floor ──────────────────────────────────────────────────────────
  class Floor {
    constructor(canvas) {
      this.cv = canvas;
      this.ctx = canvas.getContext("2d");
      this.layout = buildLayout();
      this.cam = { x: 0, y: 0, zoom: 1, tx: 0, ty: 0, tzoom: 1 };
      this.walkers = new Map();     // trade_id -> walker
      this.floats = [];             // rising money text
      this.cabinState = {};         // key -> {status, verdict, conf, reason, until}
      this.board = [];              // [{symbol, base, price, change_pct}]
      this.prices = new Map();
      this.active = new Map();      // seat index -> trade_id
      this.tradeChips = new Map();  // trade_id -> {seat, symbol, side, until}
      this.selected = null;
      this.onPick = null;
      this.hover = null;
      this._t = 0;
      this._last = performance.now();
      this._drag = null;
      this._bind();
      this.resize();
      requestAnimationFrame(this._frame.bind(this));
    }

    // ── camera / input ───────────────────────────────────────────────────
    _bind() {
      const cv = this.cv;
      cv.addEventListener("wheel", (e) => {
        e.preventDefault();
        const k = Math.exp(-e.deltaY * 0.0012);
        this.cam.tzoom = Math.min(3.2, Math.max(0.42, this.cam.tzoom * k));
      }, { passive: false });

      cv.addEventListener("pointerdown", (e) => {
        this._drag = { x: e.clientX, y: e.clientY, cx: this.cam.tx, cy: this.cam.ty, moved: 0 };
        cv.setPointerCapture(e.pointerId);
      });
      cv.addEventListener("pointermove", (e) => {
        const r = cv.getBoundingClientRect();
        const mx = e.clientX - r.left, my = e.clientY - r.top;
        if (this._drag) {
          const dx = e.clientX - this._drag.x, dy = e.clientY - this._drag.y;
          this._drag.moved += Math.abs(dx) + Math.abs(dy);
          this.cam.tx = this._drag.cx + dx;
          this.cam.ty = this._drag.cy + dy;
        } else {
          this.hover = this._pick(mx, my);
          cv.style.cursor = this.hover ? "pointer" : "grab";
        }
      });
      const up = (e) => {
        if (this._drag && this._drag.moved < 5) {
          const r = cv.getBoundingClientRect();
          const hit = this._pick(e.clientX - r.left, e.clientY - r.top);
          if (hit && this.onPick) this.onPick(hit);
          if (!hit) this.selected = null;
        }
        this._drag = null;
      };
      cv.addEventListener("pointerup", up);
      cv.addEventListener("pointercancel", () => { this._drag = null; });
    }

    resize() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = this.cv.clientWidth, h = this.cv.clientHeight;
      this.cv.width = Math.round(w * dpr);
      this.cv.height = Math.round(h * dpr);
      this.dpr = dpr;
      this.w = w; this.h = h;
      this.fitCamera();
    }

    /** Frame the whole layout, leaving room for the HUD panels. */
    fitCamera() {
      const pts = layoutBounds(this.layout);
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      const saveX = this.cam.x, saveY = this.cam.y, saveZ = this.cam.zoom;
      this.cam.x = 0; this.cam.y = 0; this.cam.zoom = 1;
      pts.forEach(([x, y, z]) => {
        const [sx, sy] = this.p(x, y, z);
        minX = Math.min(minX, sx); maxX = Math.max(maxX, sx);
        minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);
      });
      this.cam.x = saveX; this.cam.y = saveY; this.cam.zoom = saveZ;

      // panels occupy the left 250px / right 290px on wide screens
      const padL = this.w > 1180 ? 258 : 12;
      const padR = this.w > 1180 ? 300 : 12;
      const padT = 62, padB = this.w > 1180 ? 214 : 56;
      const availW = Math.max(120, this.w - padL - padR);
      const availH = Math.max(120, this.h - padT - padB);
      const spanW = Math.max(1, maxX - minX);
      const spanH = Math.max(1, maxY - minY);
      const zoom = Math.max(0.30, Math.min(2.3, Math.min(availW / spanW, availH / spanH) * 0.99));
      this.cam.zoom = this.cam.tzoom = zoom;
      // centre the (scaled) layout inside the free area
      const cx = padL + availW / 2 - ((minX + maxX) / 2) * zoom;
      const cy = padT + availH / 2 - ((minY + maxY) / 2) * zoom;
      this.cam.x = this.cam.tx = cx;
      this.cam.y = this.cam.ty = cy;
    }

    // ── projection helpers ───────────────────────────────────────────────
    p(x, y, z) {
      return [this.cam.x + (x - y) * ISO_X * TILE, this.cam.y + (x + y) * ISO_Y * TILE - (z || 0) * ZUNIT];
    }
    worldFromScreen(sx, sy) {
      const nx = (sx - this.cam.x) / (ISO_X * TILE);
      const ny = (sy - this.cam.y) / (ISO_Y * TILE);
      return { x: (nx + ny) / 2, y: (ny - nx) / 2 };
    }

    // ── drawing primitives ───────────────────────────────────────────────
    _quad(pts, fill, stroke, lw) {
      const c = this.ctx;
      c.beginPath();
      c.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) c.lineTo(pts[i][0], pts[i][1]);
      c.closePath();
      if (fill) { c.fillStyle = fill; c.fill(); }
      if (stroke) { c.strokeStyle = stroke; c.lineWidth = lw || 1; c.stroke(); }
    }

    /** Isometric box: base centre (cx,cy) at height z, size w x d, height h. */
    box(cx, cy, z, w, d, h, top, front, side, edge) {
      const x0 = cx - w / 2, x1 = cx + w / 2, y0 = cy - d / 2, y1 = cy + d / 2;
      const A = this.p(x0, y1, z), B = this.p(x1, y1, z), C = this.p(x1, y0, z), D = this.p(x0, y0, z);
      const A2 = this.p(x0, y1, z + h), B2 = this.p(x1, y1, z + h), C2 = this.p(x1, y0, z + h), D2 = this.p(x0, y0, z + h);
      // right face (+x)
      this._quad([B, C, C2, B2], side, edge);
      // front face (+y)
      this._quad([A, B, B2, A2], front, edge);
      // top
      this._quad([A2, B2, C2, D2], top, edge);
      return { A, B, C, D, A2, B2, C2, D2 };
    }

    /** The three visible quads of an iso box, so callers can interleave content. */
    boxFaces(cx, cy, z, w, d, h) {
      const x0 = cx - w / 2, x1 = cx + w / 2, y0 = cy - d / 2, y1 = cy + d / 2;
      const A = this.p(x0, y1, z), B = this.p(x1, y1, z), C = this.p(x1, y0, z), D = this.p(x0, y0, z);
      const A2 = this.p(x0, y1, z + h), B2 = this.p(x1, y1, z + h), C2 = this.p(x1, y0, z + h), D2 = this.p(x0, y0, z + h);
      return {
        right: [B, C, C2, B2],     // +x face
        front: [A, B, B2, A2],     // +y face (facing the viewer)
        top: [A2, B2, C2, D2],
        corners: { A, B, C, D, A2, B2, C2, D2 },
      };
    }

    text(str, sx, sy, { size = 11, color = COL.text, weight = 600, align = "center", mono = false, alpha = 1, shadow = true } = {}) {
      const c = this.ctx;
      c.save();
      c.globalAlpha = alpha;
      c.font = `${weight} ${size}px ${mono ? "ui-monospace,SFMono-Regular,Menlo,monospace" : "ui-sans-serif,system-ui,-apple-system,Segoe UI,Inter,sans-serif"}`;
      c.textAlign = align;
      c.textBaseline = "middle";
      if (shadow) { c.shadowColor = "rgba(0,0,0,.75)"; c.shadowBlur = 4; }
      c.fillStyle = color;
      c.fillText(str, sx, sy);
      c.restore();
    }

    chip(sx, sy, text, bg, fg, { pad = 6, size = 10.5, radius = 5, border = null, alpha = 1 } = {}) {
      const c = this.ctx;
      c.save();
      c.globalAlpha = alpha;
      c.font = `700 ${size}px ui-sans-serif,system-ui,-apple-system,Segoe UI,Inter,sans-serif`;
      const w = c.measureText(text).width + pad * 2;
      const h = size + 8;
      c.beginPath();
      const r = radius, x = sx - w / 2, y = sy - h / 2;
      c.moveTo(x + r, y); c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r);
      c.lineTo(x + w, y + h - r); c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r);
      c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y);
      c.closePath();
      c.fillStyle = bg; c.fill();
      if (border) { c.strokeStyle = border; c.lineWidth = 1; c.stroke(); }
      c.fillStyle = fg; c.textAlign = "center"; c.textBaseline = "middle";
      c.fillText(text, sx, sy + 0.5);
      c.restore();
      return { w, h };
    }

    /** Little person. scale ~1 = standing height ~26px. */
    avatar(sx, sy, palette, { sitting = false, scale = 1, walking = false, phase = 0, alpha = 1 } = {}) {
      const c = this.ctx;
      c.save();
      c.globalAlpha = alpha;
      const s = scale;
      const bodyH = (sitting ? 9 : 15) * s;
      const headR = 4.4 * s;
      // shadow
      c.beginPath();
      c.ellipse(sx, sy + 1, 8 * s, 3.2 * s, 0, 0, Math.PI * 2);
      c.fillStyle = "rgba(0,0,0,.35)"; c.fill();
      // legs
      if (!sitting) {
        const sw = walking ? Math.sin(phase) * 4 * s : 0;
        c.strokeStyle = "#2b3644"; c.lineWidth = 3 * s; c.lineCap = "round";
        c.beginPath(); c.moveTo(sx, sy - bodyH * 0.45); c.lineTo(sx + 2.6 * s + sw, sy);
        c.moveTo(sx, sy - bodyH * 0.45); c.lineTo(sx - 2.6 * s - sw, sy);
        c.stroke();
      }
      // torso
      const bg = c.createLinearGradient(sx - 6 * s, sy - bodyH, sx + 6 * s, sy);
      bg.addColorStop(0, palette.body);
      bg.addColorStop(1, palette.bodyDark);
      c.fillStyle = bg;
      this._roundRect(sx - 5.4 * s, sy - bodyH - 2 * s, 10.8 * s, bodyH + 3 * s, 3.4 * s);
      c.fill();
      // arms
      c.strokeStyle = palette.bodyDark; c.lineWidth = 2.6 * s;
      c.beginPath();
      c.moveTo(sx - 4.6 * s, sy - bodyH + 1 * s);
      c.lineTo(sx - 7 * s, sy - (walking ? bodyH * 0.35 : bodyH * 0.3));
      c.moveTo(sx + 4.6 * s, sy - bodyH + 1 * s);
      c.lineTo(sx + 7 * s, sy - (walking ? bodyH * 0.35 : bodyH * 0.3));
      c.stroke();
      // head
      c.beginPath();
      c.arc(sx, sy - bodyH - headR * 0.55, headR, 0, Math.PI * 2);
      c.fillStyle = palette.skin; c.fill();
      // hair
      c.beginPath();
      c.arc(sx, sy - bodyH - headR * 0.75, headR * 0.98, Math.PI * 1.03, Math.PI * 1.97);
      c.fillStyle = palette.hair; c.fill();
      c.restore();
    }

    _roundRect(x, y, w, h, r) {
      const c = this.ctx;
      c.beginPath();
      c.moveTo(x + r, y);
      c.arcTo(x + w, y, x + w, y + h, r);
      c.arcTo(x + w, y + h, x, y + h, r);
      c.arcTo(x, y + h, x, y, r);
      c.arcTo(x, y, x + w, y, r);
      c.closePath();
    }

    paletteFor(seedStr) {
      const r = rnd(hash(seedStr) + 7);
      const body = BODIES[Math.floor(r() * BODIES.length)];
      return {
        body,
        bodyDark: shade(body, -0.32),
        skin: HEADS[Math.floor(r() * HEADS.length)],
        hair: ["#2b2118", "#4a3524", "#151517", "#6b4a2a", "#8a6a4a"][Math.floor(r() * 5)],
      };
    }

    // ── public API ───────────────────────────────────────────────────────
    setBoard(board) {
      this.board = board || [];
      board.forEach((b) => this.prices.set(b.symbol, b));
    }

    symbolForSeat(i) {
      if (!this.board.length) return "—";
      return this.board[i % this.board.length].base;
    }

    spawn(trade) {
      const seat = this.layout.seats[(trade.desk && trade.desk.index) % this.layout.seats.length] || this.layout.seats[0];
      const w = {
        id: trade.id, trade, seat,
        pos: { x: seat.x, y: seat.y, z: 0 },
        path: [], speed: 2.35, phase: 0,
        state: "seated", target: null, inside: null,
        palette: this.paletteFor(trade.id),
        trail: 0, done: false, alpha: 1, fade: 0,
      };
      this.walkers.set(trade.id, w);
      this.active.set(trade.desk ? trade.desk.index : 0, trade.id);
      this.tradeChips.set(trade.id, {
        seat, symbol: trade.symbol, side: trade.side, until: this._t + 999,
        entry: trade.entry, score: trade.score, strategy: trade.strategy, desk: trade.desk,
      });
      this.float({ x: seat.x, y: seat.y, z: 1.2 }, `${trade.symbol.replace("/USDT", "")} ${trade.side === "LONG" ? "▲" : "▼"}`,
        trade.side === "LONG" ? COL.ok : COL.bad);
      return w;
    }

    /** Send a walker to a cabin / CEO / door. */
    /**
     * key is one of: QUANT | RISK | NEWS | MACRO | COMPLIANCE | CEO |
     *                entry_door | exit_door
     */
    moveTo(tradeId, key) {
      const w = this.walkers.get(tradeId);
      if (!w) return;
      const doorKey = key === "entry_door" ? "entry" : key === "exit_door" ? "exit"
        : (key === "entry" || key === "exit") ? key : null;
      const tgt = doorKey ? this.layout.doors[doorKey] : (this.layout.cabins[key] || this.layout.cabins.CEO);
      w.target = doorKey || key;
      w.state = "walking";
      w.path = this._path(w.pos, tgt);
      w.usingShaft = !doorKey && tgt.z > 0.15;
    }

    _path(from, to, key) {
      const pts = [];
      const front = 1.75;
      if (from.z > 0.05) {
        pts.push({ x: from.x, y: from.y + front * 0.9, z: from.z * 0.92 });
        pts.push({ x: from.x, y: from.y + front, z: 0 });
      }
      // ground walk: via an aisle point so the route reads as a real path
      const midY = Math.min(from.y, to.y + front) - 0.35;
      pts.push({ x: from.x, y: Math.max(0.15, midY), z: 0 });
      if (Math.abs(to.x - from.x) > 0.4) {
        const aisleY = Math.max(0.15, midY);
        const last = pts[pts.length - 1];
        if (!last || Math.abs(last.x - to.x) > 0.05 || Math.abs(last.y - aisleY) > 0.05) {
          pts.push({ x: to.x, y: aisleY, z: 0 });
        }
      }
      if (to.z > 0.05) {
        pts.push({ x: to.x, y: to.y + front * 0.85, z: 0 });
        pts.push({ x: to.x, y: to.y + front * 0.85, z: to.z });
        pts.push({ x: to.x, y: to.y, z: to.z });
      } else {
        pts.push({ x: to.x, y: to.y, z: 0 });
      }
      return pts;
    }

    cabinThinking(key) {
      const st = this.cabinState[key] || {};
      st.status = "thinking";
      st.verdict = null;
      st.until = this._t + 999;
      this.cabinState[key] = st;
      const cab = this.layout.cabins[key];
      if (cab) this.float({ x: cab.x, y: cab.y, z: cab.z + cab.h + 0.25 }, "…", COL.accent);
    }

    cabinVote(key, v) {
      const st = this.cabinState[key] || {};
      st.status = v.verdict;
      st.conf = v.confidence;
      st.reason = v.reason;
      st.model = v.model;
      st.flags = v.risk_flags || [];
      st.until = this._t + 14;
      this.cabinState[key] = st;
      const cab = this.layout.cabins[key];
      if (cab) {
        const ok = v.verdict === "APPROVE";
        this.float({ x: cab.x, y: cab.y, z: cab.z + cab.h + 0.3 },
          `${v.verdict} ${Math.round(v.confidence)}%`, ok ? COL.ok : COL.bad);
      }
    }

    endTrade(tradeId, doorKey, outcome, money) {
      const w = this.walkers.get(tradeId);
      const tgt = doorKey === "entry" ? this.layout.doors.entry : this.layout.doors.exit;
      const chip = this.tradeChips.get(tradeId);
      if (chip) chip.until = this._t + 6;
      if (w) {
        w.state = "leaving";
        w.done = true;
        w.path = this._path(w.pos, tgt, doorKey);
        w.exitAt = this._t + 4.5;
        w.outcome = outcome;
      }
      if (money) {
        this.float({ x: tgt.x, y: tgt.y, z: 1.0 }, money.text, money.color);
      }
    }

    /** pt is a WORLD point {x, y, z} — projected at draw time so it follows the camera. */
    float(pt, text, color) {
      this.floats.push({ pt, text, color, born: this._t, life: 3.4 });
    }

    /** Rising money text above the desk a trade came from. */
    floatAtSeat(tradeId, text, color) {
      const chip = this.tradeChips.get(tradeId);
      const seat = chip ? chip.seat : null;
      const pt = seat ? { x: seat.x, y: seat.y, z: 1.4 } : { x: 3.5, y: 3.5, z: 1.4 };
      this.float(pt, text, color || COL.ok);
    }

    // ── picking ──────────────────────────────────────────────────────────
    _pick(mx, my) {
      // walkers first (they are drawn above the floor)
      let best = null, bestD = 20;
      this.walkers.forEach((w) => {
        const [px, py] = this.p(w.pos.x, w.pos.y, w.pos.z);
        const dx = (mx - px) / this.cam.zoom, dy = (my - py) / this.cam.zoom;
        const d = Math.hypot(dx, dy);
        if (d < bestD) { bestD = d; best = { kind: "trade", id: w.id, trade: w.trade }; }
      });
      if (best) return best;
      // cabins
      for (const key of Object.keys(this.layout.cabins)) {
        const cab = this.layout.cabins[key];
        const [px, py] = this.p(cab.x, cab.y, cab.z);
        const dx = (mx - px) / this.cam.zoom, dy = (my - py) / this.cam.zoom;
        if (Math.hypot(dx, dy) < 34) return { kind: "cabin", id: key, data: this.cabinState[key] };
      }
      // recent trade chips
      let chipHit = null, chipD = 24;
      this.tradeChips.forEach((chip, id) => {
        const [px, py] = this.p(chip.seat.x, chip.seat.y, 1.5);
        const dx = (mx - px) / this.cam.zoom, dy = (my - py) / this.cam.zoom;
        const d = Math.hypot(dx, dy);
        if (d < chipD) { chipD = d; chipHit = { kind: "trade", id, trade: null }; }
      });
      return chipHit;
    }

    // ── main loop ────────────────────────────────────────────────────────
    _frame(now) {
      const dt = Math.min(0.05, (now - this._last) / 1000);
      this._last = now;
      this._t += dt;
      this.cam.x = lerp(this.cam.x, this.cam.tx, 0.12);
      this.cam.y = lerp(this.cam.y, this.cam.ty, 0.12);
      this.cam.zoom = lerp(this.cam.zoom, this.cam.tzoom, 0.12);
      this._update(dt);
      this._draw();
      requestAnimationFrame(this._frame.bind(this));
    }

    _update(dt) {
      this.walkers.forEach((w) => {
        if (!w.path.length) {
          if (w.done && w.exitAt && this._t > w.exitAt) { w.alpha -= dt * 1.2; if (w.alpha <= 0) this.walkers.delete(w.id); }
          return;
        }
        const tgt = w.path[0];
        const dx = tgt.x - w.pos.x, dy = tgt.y - w.pos.y, dz = (tgt.z - w.pos.z) * 0.75;
        const dist = Math.hypot(dx, dy, dz) || 1e-6;
        const step = w.speed * dt;
        if (dist <= step) {
          w.pos = { x: tgt.x, y: tgt.y, z: tgt.z };
          w.path.shift();
          if (!w.path.length) {
            if (w.done) {
              // walked through the door
              w.alpha -= dt * 0.9;
              if (w.alpha <= 0) this.walkers.delete(w.id);
            } else {
              w.state = "waiting";
              w.inside = w.target;
            }
          }
        } else {
          w.pos.x += (dx / dist) * step;
          w.pos.y += (dy / dist) * step;
          w.pos.z += (dz / dist) * step;
          w.phase += dt * 9;
          w.state = "walking";
        }
      });
      this.floats = this.floats.filter((f) => this._t - f.born < f.life);
    }

    // ── scene drawing ────────────────────────────────────────────────────
    _draw() {
      const c = this.ctx;
      c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      c.clearRect(0, 0, this.w, this.h);

      c.save();
      c.translate(this.cam.x, this.cam.y);
      c.scale(this.cam.zoom, this.cam.zoom);
      c.translate(-this.cam.x, -this.cam.y);

      this._drawGround();
      this._drawCabinsBack();
      this._drawDesks();
      this._drawDoors();
      this._drawWalkers();
      this._drawFloats();
      c.restore();

      this._drawVignette();
    }

    _drawGround() {
      const c = this.ctx;
      const b = this.layout.bounds;
      const x0 = b.x0 - 0.9, x1 = b.x1 + 0.9, y0 = b.y0 - 0.9, y1 = b.y1 + 1.4;
      const A = this.p(x0, y1, 0), B = this.p(x1, y1, 0), C = this.p(x1, y0, 0), D = this.p(x0, y0, 0);
      const g = c.createLinearGradient(A[0], A[1], C[0], C[1]);
      g.addColorStop(0, COL.floorB);
      g.addColorStop(1, COL.floorA);
      this._quad([A, B, C, D], g, "rgba(90,210,255,.10)", 1.4);

      c.save();
      c.beginPath();
      c.moveTo(A[0], A[1]); c.lineTo(B[0], B[1]); c.lineTo(C[0], C[1]); c.lineTo(D[0], D[1]); c.closePath();
      c.clip();
      c.strokeStyle = COL.grid; c.lineWidth = 1;
      for (let x = Math.ceil(x0); x <= x1; x++) {
        const p1 = this.p(x, y0, 0), p2 = this.p(x, y1, 0);
        c.beginPath(); c.moveTo(p1[0], p1[1]); c.lineTo(p2[0], p2[1]); c.stroke();
      }
      for (let y = Math.ceil(y0); y <= y1; y++) {
        const p1 = this.p(x0, y, 0), p2 = this.p(x1, y, 0);
        c.beginPath(); c.moveTo(p1[0], p1[1]); c.lineTo(p2[0], p2[1]); c.stroke();
      }
      c.restore();
    }

    _drawDesks() {
      const L = this.layout;
      // long slabs, like the reference image
      const c = this.ctx;
      L.rows.forEach((row) => {
        this.box(row.cx, row.y + 0.2, 0, row.w, row.d, 0.34,
          COL.slabTop, COL.slabFront, COL.slabSide, "rgba(0,0,0,.25)");
        const p1 = this.p(row.cx - row.w / 2, row.y + 0.2 + row.d / 2, 0.345);
        const p2 = this.p(row.cx + row.w / 2, row.y + 0.2 + row.d / 2, 0.345);
        c.strokeStyle = "rgba(120,170,220,.18)"; c.lineWidth = 1;
        c.beginPath(); c.moveTo(p1[0], p1[1]); c.lineTo(p2[0], p2[1]); c.stroke();
      });
      // seated traders + monitors, back rows first
      const seats = [...L.seats].sort((a, b) => (a.x + a.y) - (b.x + b.y));
      seats.forEach((s, i) => {
        const activeId = this.active.get(i);
        const chip = activeId ? this.tradeChips.get(activeId) : null;
        const base = this.p(s.x, s.y, 0.34);
        // monitor on the far side of the slab
        const mp = this.p(s.x + 0.05, s.y - 0.22, 0.34);
        const c = this.ctx;
        c.save();
        c.globalAlpha = 0.95;
        c.fillStyle = COL.monitor;
        this._roundRect(mp[0] - 7, mp[1] - 13, 14, 10, 2);
        c.fill();
        c.strokeStyle = activeId ? "rgba(90,210,255,.75)" : "rgba(90,210,255,.20)";
        c.lineWidth = 1; c.stroke();
        c.restore();

        const pal = this.paletteFor("seat" + i);
        const seated = !activeId || (this.walkers.get(activeId) && this.walkers.get(activeId).state === "seated");
        if (seated) {
          this.avatar(base[0], base[1], pal, { sitting: true, scale: 0.98 });
        } else if (activeId && !this.walkers.has(activeId)) {
          this.avatar(base[0], base[1], pal, { sitting: true, scale: 0.98, alpha: 0.45 });
        }
        // idle desks still show a dim symbol tag (the "dozens of traders" look)
        if (!activeId) {
          const sym = this.symbolForSeat(i);
          const tag = this.p(s.x, s.y + 0.02, 1.05);
          this.chip(tag[0], tag[1], sym, "rgba(20,32,44,.72)", "rgba(160,190,215,.65)",
            { size: 8.6, pad: 5, border: "rgba(120,170,220,.18)" });
        }
      });
    }

    _drawCabinsBack() {
      // soft pools of light on the floor beneath each cabin, then the towers
      Object.values(this.layout.cabins).forEach((cab) => {
        const c = this.ctx;
        const [px, py] = this.p(cab.x, cab.y + cab.d * 0.4, 0);
        c.save();
        const g = c.createRadialGradient(px, py, 2, px, py, 46);
        g.addColorStop(0, hexA(cab.color, 0.10));
        g.addColorStop(0.55, hexA(cab.color, 0.04));
        g.addColorStop(1, "rgba(0,0,0,0)");
        c.fillStyle = g;
        c.beginPath(); c.ellipse(px, py, 46, 20, 0, 0, Math.PI * 2); c.fill();
        c.restore();
      });
      this._drawCabinsGlass();
    }

    _drawCabinsGlass() {
      Object.values(this.layout.cabins).forEach((cab) => this._cabinBody(cab));
    }

    _cabinBody(cab) {
      const c = this.ctx;
      const st = this.cabinState[cab.key] || {};
      const thinking = st.status === "thinking";
      const glow = thinking ? 0.55 + 0.45 * Math.sin(this._t * 4)
        : st.until > this._t ? 1 : 0.25;
      const color = cab.color;
      const F = this.boxFaces(cab.x, cab.y, cab.z, cab.w, cab.d, cab.h);

      // floor pad + access shaft (behind everything)
      const fx = cab.x, fy = cab.y + cab.d * 0.85;
      const s0 = this.p(fx, fy, 0), s1 = this.p(fx, fy, cab.z);
      c.save();
      c.strokeStyle = hexA(color, 0.14);
      c.lineWidth = 6; c.lineCap = "round";
      c.beginPath(); c.moveTo(s0[0], s0[1]); c.lineTo(s1[0], s1[1]); c.stroke();
      c.strokeStyle = hexA(color, 0.5);
      c.lineWidth = 1.1; c.setLineDash([5, 7]);
      c.beginPath(); c.moveTo(s0[0], s0[1]); c.lineTo(s1[0], s1[1]); c.stroke();
      c.setLineDash([]);
      c.fillStyle = hexA(color, 0.22);
      c.beginPath(); c.ellipse(s0[0], s0[1], 8, 3.8, 0, 0, Math.PI * 2); c.fill();
      // support legs
      c.strokeStyle = "rgba(150,190,225,.20)"; c.lineWidth = 1.8;
      [[-0.44, 0.44], [0.44, 0.44], [-0.44, -0.44]].forEach(([ox, oy]) => {
        const bx = this.p(cab.x + ox * cab.w, cab.y + oy * cab.d, 0);
        const tx = this.p(cab.x + ox * cab.w, cab.y + oy * cab.d, cab.z - 0.02);
        c.beginPath(); c.moveTo(bx[0], bx[1]); c.lineTo(tx[0], tx[1]); c.stroke();
      });
      c.restore();

      // elevated platform slab
      this.box(cab.x, cab.y, cab.z - 0.16, cab.w + 0.26, cab.d + 0.26, 0.16,
        "#2b3644", "#1d252f", "#161d25", "rgba(255,255,255,.07)");

      // ── back panes (behind the operator) ─────────────────────────────
      c.save();
      this._quad(F.right, hexA(color, 0.13), hexA(color, 0.22));
      c.restore();

      // ── what is inside the cabin ─────────────────────────────────────
      const cx2 = cab.x - cab.w * 0.10, cy2 = cab.y + cab.d * 0.02;
      const base = this.p(cx2, cy2, cab.z);
      // monitor on the back wall
      c.save();
      c.fillStyle = "rgba(9,14,20,.85)";
      this._roundRect(base[0] - 11, base[1] - 26, 22, 14, 2);
      c.fill();
      c.strokeStyle = hexA(color, thinking ? 0.95 : 0.5);
      c.lineWidth = 1;
      c.stroke();
      c.restore();
      const pal = { body: color, bodyDark: shade(color, -0.38), skin: "#f0d3b0", hair: "#241d16" };
      this.avatar(base[0] + 4, base[1], pal, { sitting: true, scale: cab.key === "CEO" ? 1.02 : 0.9 });

      // ── front panes + top (glass over the operator) ───────────────────
      c.save();
      this._quad(F.front, hexA(color, 0.09), hexA(color, 0.20));
      this._quad(F.top, hexA(color, 0.16), hexA(color, 0.30));
      // a single diagonal highlight so the glass reads as glass
      const Ca = F.corners.A2, Cb = F.corners.C2;
      const gx0 = Ca[0] + (Cb[0] - Ca[0]) * 0.22, gy0 = Ca[1] + (Cb[1] - Ca[1]) * 0.16;
      c.strokeStyle = "rgba(255,255,255,.16)";
      c.lineWidth = 1.4;
      c.beginPath();
      c.moveTo(gx0, gy0);
      c.lineTo(gx0 + (Cb[0] - Ca[0]) * 0.16, gy0 + (Cb[1] - Ca[1]) * 0.5 + 26);
      c.stroke();
      c.restore();

      // ── neon frame + base glow ───────────────────────────────────────
      c.save();
      c.globalAlpha = 0.30 + 0.70 * glow;
      c.strokeStyle = color; c.lineWidth = 2;
      c.beginPath();
      [F.corners.A2, F.corners.B2, F.corners.C2, F.corners.D2].forEach((pt, i) =>
        i ? c.lineTo(pt[0], pt[1]) : c.moveTo(pt[0], pt[1]));
      c.closePath(); c.stroke();
      c.restore();

      // ── plate + live verdict ────────────────────────────────────────
      const plate = this.p(cab.x, cab.y + cab.d * 0.55, cab.z + cab.h * 0.58);
      this.chip(plate[0], plate[1], CABIN_LABEL[cab.key] || cab.key,
        "rgba(9,14,20,.92)", color, { size: cab.key === "CEO" ? 11 : 10, border: color });

      if (thinking) {
        const dots = ".".repeat(1 + (Math.floor(this._t * 3) % 3));
        this.text("thinking" + dots, plate[0], plate[1] - 15,
          { size: 9.5, color: COL.accent, alpha: 0.95 });
      } else if (st.verdict && st.until > this._t) {
        const ok = st.verdict === "APPROVE";
        const vs = this.p(cab.x, cab.y, cab.z + cab.h + 0.5);
        this.chip(vs[0], vs[1], `${st.verdict} · ${Math.round(st.conf)}%`,
          ok ? "rgba(12,48,32,.95)" : "rgba(58,16,20,.95)", ok ? "#8bf0bd" : "#ffb0b3",
          { size: 10, border: ok ? COL.ok : COL.bad });
        if (st.reason) {
          const words = String(st.reason).split(" ");
          const line = words.slice(0, 12).join(" ") + (words.length > 12 ? "…" : "");
          this.text(line, vs[0], vs[1] - 17,
            { size: 9, color: "rgba(205,222,236,.85)", weight: 500, alpha: Math.min(1, (st.until - this._t) / 3) });
        }
      }
    }

    _drawDoors() {
      ["entry", "exit"].forEach((k) => {
        const d = this.layout.doors[k];
        const color = d.color;
        const base = this.p(d.x, d.y, 0);
        const c = this.ctx;
        // glow pool on the floor in front of the door
        c.save();
        const pulse = 0.5 + 0.5 * Math.sin(this._t * 1.6 + (k === "entry" ? 0 : 1.5));
        const pg = c.createRadialGradient(base[0], base[1] + 6, 2, base[0], base[1] + 6, 40);
        pg.addColorStop(0, hexA(color, 0.14 + 0.10 * pulse));
        pg.addColorStop(1, "rgba(0,0,0,0)");
        c.fillStyle = pg;
        c.beginPath(); c.ellipse(base[0], base[1] + 6, 40, 17, 0, 0, Math.PI * 2); c.fill();
        c.restore();
        // frame
        const w = 30, h = 46;
        c.save();
        c.globalAlpha = 0.9;
        const g = c.createLinearGradient(base[0], base[1] - h, base[0], base[1]);
        g.addColorStop(0, hexA(color, 0.05));
        g.addColorStop(1, hexA(color, 0.42));
        c.fillStyle = g;
        this._roundRect(base[0] - w / 2, base[1] - h, w, h, 6);
        c.fill();
        c.strokeStyle = color; c.lineWidth = 2; c.stroke();
        // inner glow line
        c.beginPath();
        c.moveTo(base[0], base[1] - h + 6); c.lineTo(base[0], base[1] - 6);
        c.strokeStyle = hexA(color, 0.7); c.lineWidth = 1; c.stroke();
        c.restore();
        // sign
        this.chip(base[0], base[1] - h - 12, d.label + (k === "entry" ? " ▲" : " ▼"),
          "rgba(9,14,20,.92)", color, { size: 10.5, border: color });
        this.text(k === "entry" ? "approved trades exit here" : "rejected trades leave here",
          base[0], base[1] + 12, { size: 8.6, color: "rgba(150,175,195,.7)", weight: 500 });
      });
    }

    _drawWalkers() {
      const list = [...this.walkers.values()].sort((a, b) => (a.pos.x + a.pos.y) - (b.pos.x + b.pos.y));
      list.forEach((w) => {
        const [sx, sy] = this.p(w.pos.x, w.pos.y, w.pos.z);
        const walking = w.state === "walking";
        // selection ring
        if (this.selected === w.id) {
          const c = this.ctx;
          c.save();
          c.strokeStyle = COL.accent; c.lineWidth = 2; c.setLineDash([4, 4]);
          c.beginPath(); c.ellipse(sx, sy + 1, 13, 6, 0, 0, Math.PI * 2); c.stroke();
          c.restore();
        }
        // carrier chip above the head: which trade is this?
        const sym = (w.trade.symbol || "").replace("/USDT", "");
        const up = w.trade.side === "LONG";
        const chipY = sy - (walking ? 40 : 44);
        this.chip(sx, chipY, `${sym} ${up ? "▲" : "▼"}`,
          up ? "rgba(12,48,32,.92)" : "rgba(58,16,20,.92)", up ? "#8bf0bd" : "#ffb0b3",
          { size: 9.5, border: hexA(up ? COL.ok : COL.bad, 0.7) });
        this.avatar(sx, sy, w.palette, { walking, phase: w.phase, alpha: Math.max(0, w.alpha) });
        if (w.state === "waiting" && w.inside && this.layout.cabins[w.inside]) {
          const cv2 = this.layout.cabins[w.inside];
          this.text("in session", sx, sy + 14, { size: 8.4, color: hexA(cv2.color, 0.95) });
        }
      });
    }

    _drawFloats() {
      this.floats.forEach((f) => {
        const age = (this._t - f.born) / f.life;
        const [sx, sy] = this.p(f.pt.x, f.pt.y, f.pt.z + age * 1.15);
        this.text(f.text, sx, sy, {
          size: 11.5, color: f.color, weight: 700, alpha: Math.max(0, 1 - age * age),
        });
      });
    }

    _drawVignette() {
      const c = this.ctx;
      const g = c.createRadialGradient(this.w * 0.5, this.h * 0.45, Math.min(this.w, this.h) * 0.25,
        this.w * 0.5, this.h * 0.45, Math.max(this.w, this.h) * 0.78);
      g.addColorStop(0, "rgba(0,0,0,0)");
      g.addColorStop(1, "rgba(0,0,0,.55)");
      c.fillStyle = g;
      c.fillRect(0, 0, this.w, this.h);
    }
  }

  // ── colour utils ─────────────────────────────────────────────────────
  function shade(hex, amt) {
    const m = hex.replace("#", "");
    const num = parseInt(m.length === 3 ? m.split("").map((x) => x + x).join("") : m, 16);
    let r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
    r = Math.max(0, Math.min(255, Math.round(r + 255 * amt)));
    g = Math.max(0, Math.min(255, Math.round(g + 255 * amt)));
    b = Math.max(0, Math.min(255, Math.round(b + 255 * amt)));
    return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
  }
  function hexA(hex, a) {
    const m = hex.replace("#", "");
    const num = parseInt(m.length === 3 ? m.split("").map((x) => x + x).join("") : m, 16);
    return `rgba(${(num >> 16) & 255},${(num >> 8) & 255},${num & 255},${a})`;
  }

  window.SoulFloor = Floor;
  window.SoulLayout = { CABIN_ORDER, CABIN_LABEL, CABIN_COLORS, COL };
})();

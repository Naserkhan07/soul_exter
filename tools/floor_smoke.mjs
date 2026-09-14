/* =============================================================================
   Headless smoke test + renderer for the isometric floor.

   There is no browser in CI, so this loads web/floor.js against a stubbed
   canvas context. Two jobs:

     1. catch runtime errors / NaN coordinates in the render + walk logic
     2. dump every draw call to JSON so tools/render_floor.py can rasterise a
        real PNG of the floor for visual review

   usage:  node tools/floor_smoke.mjs [out.json]
   ========================================================================== */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const ops = [];
let errors = [];

// ── stubbed canvas 2D context ────────────────────────────────────────────
// Gradients are captured with their stops so the offline renderer can
// approximate them (it paints the average stop colour into the path).
function grad(type, x0, y0, x1, y1, r0, r1) {
  return {
    __grad: true, type,
    x0, y0, x1, y1, r0, r1,
    stops: [],
    addColorStop(o, c) { this.stops.push([o, c]); },
  };
}
function makeCtx(w, h) {
  let m = [1, 0, 0, 1, 0, 0];           // a b c d e f
  const stack = [];
  const apply = (x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  const ctx = {
    canvas: { width: w, height: h },
    // state
    fillStyle: "#000", strokeStyle: "#000", lineWidth: 1, globalAlpha: 1,
    font: "10px sans-serif", textAlign: "left", textBaseline: "top",
    shadowColor: "", shadowBlur: 0, lineCap: "butt", lineJoin: "miter",
    // transform
    save() { stack.push(m.slice()); },
    restore() { if (stack.length) m = stack.pop(); },
    setTransform(a, b, c, d, e, f) { m = [a, b, c, d, e, f]; },
    translate(x, y) { m = [m[0], m[1], m[2], m[3], m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]; },
    scale(x, y) { m = [m[0] * x, m[1] * x, m[2] * y, m[3] * y, m[4], m[5]]; },
    // paths
    beginPath() { this._p = []; },
    closePath() { if (this._p && this._p.length) this._p.push(this._p[0]); },
    moveTo(x, y) { this._p = this._p || []; this._p.push(apply(x, y)); },
    lineTo(x, y) { (this._p = this._p || []).push(apply(x, y)); },
    quadraticCurveTo(cx, cy, x, y) { (this._p = this._p || []).push(apply(x, y)); },
    arcTo(x1, y1, x2, y2) { (this._p = this._p || []).push(apply(x2, y2)); },
    arc(x, y, r, a0, a1) {
      const [px, py] = apply(x, y);
      const scale = Math.abs(m[0]) || 1;
      (this._p = this._p || []).push([px, py], [px + r * scale, py]);
      this._circle = { x: px, y: py, r: r * scale };
    },
    ellipse(x, y, rx, ry) {
      const [px, py] = apply(x, y);
      const s = Math.abs(m[0]) || 1;
      ops.push({ op: "ellipse", x: px, y: py, rx: rx * s, ry: ry * s, fill: this.fillStyle, stroke: null, alpha: this.globalAlpha });
    },
    rect(x, y, w2, h2) { (this._p = this._p || []).push(apply(x, y), apply(x + w2, y + h2)); },
    fill() { if (this._p && this._p.length) ops.push({ op: "poly", pts: this._p.slice(), fill: this.fillStyle, stroke: null, alpha: this.globalAlpha }); },
    stroke() { if (this._p && this._p.length) ops.push({ op: "poly", pts: this._p.slice(), fill: null, stroke: this.strokeStyle, lw: this.lineWidth, alpha: this.globalAlpha }); },
    fillRect(x, y, w2, h2) { const [px, py] = apply(x, y); ops.push({ op: "rect", x: px, y: py, w: w2 * (Math.abs(m[0]) || 1), h: h2 * (Math.abs(m[3]) || 1), fill: this.fillStyle, alpha: this.globalAlpha }); },
    clearRect() {},
    fillText(t, x, y) { const [px, py] = apply(x, y); ops.push({ op: "text", t, x: px, y: py, fill: this.fillStyle, size: parseFloat((this.font.match(/(\d+(\.\d+)?)px/) || [0, 10])[1]), alpha: this.globalAlpha }); },
    measureText(t) { return { width: String(t).length * 6.2 }; },
    setLineDash() {},
    clip() {},
    createLinearGradient(x0, y0, x1, y1) { return grad("linear", x0, y0, x1, y1); },
    createRadialGradient(x0, y0, r0, x1, y1, r1) { return grad("radial", x0, y0, x1, y1, r0, r1); },
  };
  return ctx;
}

// ── stubbed DOM ──────────────────────────────────────────────────────────
const listeners = {};
const canvas = {
  clientWidth: 1600, clientHeight: 900, width: 1600, height: 900,
  style: {}, addEventListener: (k, f) => { (listeners[k] ||= []).push(f); },
  getContext: () => makeCtx(1600, 900),
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 1600, height: 900 }),
  setPointerCapture() {},
};
global.window = { devicePixelRatio: 1, addEventListener() {} };
global.document = { getElementById: () => canvas, querySelector: () => null, querySelectorAll: () => [] };
global.performance = { now: () => Date.now() };
global.requestAnimationFrame = () => 0;
global.setTimeout = setTimeout;

// ── load floor.js ────────────────────────────────────────────────────────
const src = fs.readFileSync(path.join(root, "web", "floor.js"), "utf8");
try {
  new Function("window", "document", "performance", "requestAnimationFrame", "setTimeout", src)(
    global.window, global.document, global.performance, global.requestAnimationFrame, global.setTimeout);
} catch (e) {
  console.error("FLOOR.JS FAILED TO LOAD:", e);
  process.exit(1);
}
const Floor = global.window.SoulFloor;
if (!Floor) { console.error("window.SoulFloor missing"); process.exit(1); }

// ── drive a full trade through the floor ─────────────────────────────────
const floor = new Floor(canvas);
const board = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "TAO", "INJ", "ZEC", "SUI", "NEAR", "LINK",
  "UNI", "AAVE", "DOT", "XLM", "PAXG", "HYPE", "TIA", "APT", "SEI", "TON", "ARB", "OP"]
  .map((b, i) => ({ symbol: b + "/USDT", base: b, price: 100 + i, change_pct: (i % 7) - 3 }));
floor.setBoard(board);

const trade = {
  id: "T-ABC123", symbol: "SOL/USDT", side: "LONG", strategy: "MOMENTUM_BREAKOUT",
  entry: 152.4, stop: 149.1, target: 158.2, rr: 1.76, score: 0.62, desk: { index: 11, row: 1, col: 3 },
};
const trade2 = { ...trade, id: "T-DEF456", symbol: "DOGE/USDT", side: "SHORT", desk: { index: 30, row: 3, col: 6 } };

function step(n = 1, dt = 1 / 60) {
  for (let i = 0; i < n; i++) {
    floor._t += dt;
    floor.cam.x = floor.cam.tx; floor.cam.y = floor.cam.ty; floor.cam.zoom = floor.cam.tzoom;
    floor._update(dt);
    try { floor._draw(); } catch (e) { errors.push(String(e)); }
  }
}
function assert(cond, msg) { if (!cond) errors.push("ASSERT: " + msg); }

// 1. spawn four traders well clear of the panel areas
floor.resize();                       // frame the real layout
floor.cam.x = floor.cam.tx; floor.cam.y = floor.cam.ty; floor.cam.zoom = floor.cam.tzoom;

const trades = [
  { id: "T-SOL001", symbol: "SOL/USDT", side: "LONG", strategy: "MOMENTUM_BREAKOUT", entry: 152.4, stop: 149.1, target: 158.2, rr: 1.76, score: 0.62, desk: { index: 11, row: 1, col: 3 } },
  { id: "T-DOGE02", symbol: "DOGE/USDT", side: "SHORT", strategy: "MEAN_REVERSION", entry: 0.132, stop: 0.136, target: 0.124, rr: 2.0, score: 0.48, desk: { index: 27, row: 3, col: 3 } },
  { id: "T-TAO003", symbol: "TAO/USDT", side: "LONG", strategy: "TREND_PULLBACK", entry: 385.0, stop: 377.2, target: 402.0, rr: 2.18, score: 0.71, desk: { index: 44, row: 5, col: 4 } },
  { id: "T-ZEC004", symbol: "ZEC/USDT", side: "SHORT", strategy: "VOLATILITY_SQUEEZE", entry: 28.4, stop: 29.3, target: 26.2, rr: 2.44, score: 0.55, desk: { index: 58, row: 7, col: 2 } },
];
trades.forEach((t) => floor.spawn(t));
step(40);
trades.forEach((t, i) => assert(floor.walkers.get(t.id), `trader ${i} should be on the floor`));

const VOTE = (verdict, confidence, reason, flags) => ({
  verdict, confidence, reason, model: "mock::test", risk_flags: flags || [], stage: 1,
});

// trade 1: four cabins in, one to go
for (const [key, verdict, conf, reason] of [
  ["QUANT", "APPROVE", 74, "R:R 1.76 with volume confirmation; clears this desk."],
  ["RISK", "APPROVE", 61, "stop 2.17% against a 3.80% target; clears this desk."],
  ["NEWS", "REJECT", 68, "RSI 70 into a strong tape; chasing an over-extended candle."],
  ["MACRO", "APPROVE", 66, "BTC +0.73%, beta proxy 1.55; riding the tape, clears."],
]) {
  floor.moveTo(trades[0].id, key);
  step(360);
  floor.cabinThinking(key);
  step(6);
  floor.cabinVote(key, VOTE(verdict, conf, reason, verdict === "REJECT" ? ["chasing an extended candle"] : []));
  step(24);
}
floor.moveTo(trades[0].id, "COMPLIANCE");
step(240);

// trade 2: escalated to the CEO after a 4-1 split
floor.moveTo(trades[1].id, "COMPLIANCE");
step(300);
floor.cabinVote("COMPLIANCE", VOTE("APPROVE", 58, "no rule breaches: sizing within mandate"));
floor.cabinThinking("CEO");
step(30);
floor.cabinVote("CEO", VOTE("APPROVE", 63, "council 4/5 in favour; the dissenting stop concern is priced in"));

// trade 3: approved, walking to the entry door
floor.endTrade(trades[2].id, "entry", "ENTER", { text: "+$48.20", color: "#35d07f" });
step(120);

// trade 4: rejected, walking out the exit door
floor.cabinVote("QUANT", VOTE("REJECT", 79, "R:R 1.10 below the 1.4 desk minimum"));
floor.moveTo(trades[3].id, "QUANT");
step(200);
floor.endTrade(trades[3].id, "exit", "SKIP", { text: "-$12.40", color: "#ff5c62" });
step(150);

// a live P&L float above a desk that just closed
floor.floatAtSeat(trades[2].id, "+$48.20", "#35d07f");
step(30);

// Re-vote every cabin at the very end: the hero shot should show all six
// cabins holding a live verdict, exactly as they do while a trade is in flight.
const FINAL = {
  QUANT:      ["APPROVE", 74, "R:R 1.76 with volume confirmation; clears this desk."],
  RISK:       ["APPROVE", 61, "stop 2.17% against a 3.80% target; clears this desk."],
  NEWS:       ["REJECT", 68, "RSI 70 into a strong tape; chasing an over-extended candle."],
  MACRO:      ["APPROVE", 66, "BTC +0.73%, beta proxy 1.55; riding the tape."],
  COMPLIANCE: ["APPROVE", 58, "no rule breaches: sizing within mandate."],
};
Object.entries(FINAL).forEach(([k, [v, c, r]]) =>
  floor.cabinVote(k, VOTE(v, c, r, v === "REJECT" ? ["chasing an extended candle"] : [])));
floor.cabinVote("CEO", VOTE("APPROVE", 63, "council 4/5 in favour; dissent priced in.", ["NEWS dissent"]));
step(40);

const visited = [["cabins lit", Object.keys(floor.cabinState).length], ["walkers", floor.walkers.size]];

// ── geometry report ──────────────────────────────────────────────────────
const proj = {};
for (const [k, c] of Object.entries(floor.layout.cabins)) proj["cabin:" + k] = floor.p(c.x, c.y, c.z).map(Math.round);
for (const [k, d] of Object.entries(floor.layout.doors)) proj["door:" + k] = floor.p(d.x, d.y, 0).map(Math.round);
proj["seat:0"] = floor.p(floor.layout.seats[0].x, floor.layout.seats[0].y, 0).map(Math.round);
proj["seat:63"] = floor.p(floor.layout.seats[63].x, floor.layout.seats[63].y, 0).map(Math.round);

ops.length = 0;
floor._draw();

const nan = [];
ops.forEach((o, i) => {
  const vals = [o.x, o.y, o.w, o.h].filter((v) => v !== undefined);
  (o.pts || []).forEach((p) => vals.push(p[0], p[1]));
  if (vals.some((v) => !Number.isFinite(v))) nan.push({ i, op: o.op, t: o.t, x: o.x, y: o.y, pts: (o.pts || []).slice(0, 2) });
});

console.log("draw ops in captured frame:", ops.length);
console.log("projected landmarks:", JSON.stringify(proj, null, 1));
console.log("walk log:", JSON.stringify(visited));
console.log("errors:", errors.length ? errors : "none");
console.log("NaN draw ops:", nan.length ? nan.slice(0, 5) : "none");

// optional framing: --zoom 1.8 --focus cabins|doors|desks
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf("--" + name);
  return i >= 0 && argv[i + 1] ? Number(argv[i + 1]) : dflt;
};
const focus = (() => {
  const i = argv.indexOf("--focus");
  return i >= 0 && argv[i + 1] ? argv[i + 1] : null;
})();
if (opt("zoom", 0) > 0 || focus) {
  const z = opt("zoom", 1);
  floor.cam.tzoom = z;
  const seatMid = () => floor.p(4.2, 5.6, 0);
  const cabMid = () => floor.p(5.4, -4.2, 3.6);
  const doorMid = () => floor.p(4.0, 12.0, 0);
  const mid = focus === "cabins" ? cabMid() : focus === "doors" ? doorMid() : seatMid();
  // place the chosen subject at the centre of the free canvas area
  floor.cam.tx = 800 - (mid[0] - floor.cam.x);
  floor.cam.ty = 500 - (mid[1] - floor.cam.y);
  floor.cam.x = floor.cam.tx; floor.cam.y = floor.cam.ty;
  floor.cam.zoom = floor.cam.tzoom;
}
ops.length = 0;
floor._draw();

const out = argv[0] && !argv[0].startsWith("--") ? argv[0] : null;
if (out) {
  fs.writeFileSync(out, JSON.stringify({ ops, w: 1600, h: 900 }, null, 0));
  console.log("wrote", out);
}
process.exit(errors.length ? 1 : 0);

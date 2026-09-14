/**
 * Boot the built interface in a DOM and assert that it renders.
 *
 * There is no browser in this sandbox (the playwright download is blocked and
 * there is no system chromium), and a canvas UI cannot be checked by looking at
 * a screenshot alone. So: bundle the app for a browser, run it inside jsdom with
 * a canvas stub and a stubbed socket, feed it a realistic engine snapshot, and
 * assert the panels, the trade rows and the drawer actually appear.
 *
 *   node tools/ui_smoke.mjs            # builds, then checks
 *   node tools/ui_smoke.mjs --no-build
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const frontend = path.join(root, "frontend");
// jsdom lives with the front-end toolchain, not at the repo root
const { JSDOM } = createRequire(path.join(frontend, "package.json"))("jsdom");
const bundle = path.join(frontend, "node_modules/.cache/ui-smoke.js");

// --live <base> runs the checks against a REAL server payload instead of the
// built-in fixture. That is the only way to catch a contract drift (a field
// renamed on the wire) without a browser.
const liveArg = process.argv.indexOf("--live");
const liveBase = liveArg >= 0 ? (process.argv[liveArg + 1] ?? "http://127.0.0.1:8000") : null;

console.log("ui smoke: bundling…");
if (!process.argv.includes("--no-build")) {
  execFileSync(
    path.join(frontend, "node_modules/.bin/esbuild"),
    ["src/main.tsx", "--bundle", "--format=iife", "--platform=browser",
     "--loader:.css=text", `--outfile=${bundle}`, "--log-level=warning"],
    { cwd: frontend, stdio: "inherit" },
  );
}

const code = readFileSync(bundle, "utf8");
const html = readFileSync(path.join(root, "web", "index.html"), "utf8")
  .replace(/<script type="module"[\s\S]*?<\/script>/, "")
  .replace(/<script>[\s\S]*?MutationObserver[\s\S]*?<\/script>/, "");

// ---- the fixture: what /api/state returns ---------------------------------
const now = Date.now() / 1000;
const fixture = {
  engine: { llm_mode: "mock", cuda: false, paused: false, scan_seconds: 18, uptime_s: 642, model_profile: "standard" },
  council: {
    reviews: 39, escalations: 35, ceo_approvals: 9, ceo_rejections: 8,
    scoreboard: {
      min_evidence: 4,
      desks: {
        QUANT: { calls: 16, right: 10, hit_rate: 0.625, approvals: 9, wins: 6, losses: 3, r_sum: 11.07, pnl: 613.59, streak: 0, weight: 1.062, proven: true },
        RISK: { calls: 16, right: 5, hit_rate: 0.313, approvals: 12, wins: 5, losses: 7, r_sum: 4.23, pnl: 169.21, streak: 0, weight: 0.906, proven: true },
      },
    },
  },
  desk: { equity: 15694.14, starting_cash: 15000, realised: 589.85, win_rate: 62, open: 3, leverage: 0.6 },
  training: {
    enabled: true, rows: 168, settled_rows: 36, curriculum_rows: 120, lesson_rows: 12,
    waiting: 2, adapters_dir: "artifacts/adapters", trained_now: false, adapters: {},
    desks: {
      QUANT: { rows: 26, settled: 6, adapter: null },
      RISK: { rows: 24, settled: 4, adapter: null },
      NEWS: { rows: 20, settled: 0, adapter: null },
      MACRO: { rows: 22, settled: 2, adapter: null },
      COMPLIANCE: { rows: 21, settled: 1, adapter: null },
      CEO: { rows: 55, settled: 23, adapter: null },
    },
  },
  market: {
    mode: "sim",
    board: [
      { symbol: "BTC/USDT", price: 61230.5, change_pct: 1.24 },
      { symbol: "ETH/USDT", price: 2412.8, change_pct: -0.62 },
      { symbol: "SOL/USDT", price: 138.42, change_pct: 3.11 },
      { symbol: "TIA/USDT", price: 5.83, change_pct: -2.4 },
    ],
  },
  cabins: [
    { key: "QUANT", label: "QUANT", name: "Dr. Amara Osei", title: "Head of Quantitative Research",
      expertise: ["statistical edges", "signal decay", "position sizing"],
      reason: "The 24-bar drift and volume z-score are both in the top decile, and the pullback holds above the 20-EMA.",
      said: "Correlation to the book is 1.3 and the stop sits inside the noise band.", lastVote: "APPROVE", confidence: 72,
      model: "Qwen/Qwen2.5-7B-Instruct", role: "quant", isCeo: false, thinking: true, calls: 39, latency: 480, symbol: "TIA/USDT" },
    { key: "RISK", label: "RISK", name: "Viktor Hale", title: "Chief Risk Officer",
      expertise: ["drawdown control", "correlation", "stop placement"],
      reason: "Risk per seat is 0.75% and the book already carries this factor twice; I want the size cut before it is taken.",
      lastVote: "REJECT", confidence: 61, model: "mistralai/Mistral-7B-Instruct-v0.3", role: "risk", isCeo: false, thinking: false, calls: 39, latency: 510 },
    { key: "NEWS", label: "NEWS", name: "Lina Marchetti", title: "Head of News Flow and Catalysts",
      expertise: ["catalysts", "funding", "event risk"],
      reason: "No catalyst behind the move and the funding print is stretched. This is a chase, not a setup.",
      lastVote: "APPROVE", confidence: 70, model: "HuggingFaceH4/zephyr-7b-beta", role: "news", isCeo: false, thinking: false, calls: 39, latency: 455 },
    { key: "MACRO", label: "MACRO", name: "Rahul Menon", title: "Global Macro Strategist",
      expertise: ["regime detection", "rates", "index expression"],
      reason: "If the front end is repricing, express the short at index level rather than in a single high-beta name.",
      lastVote: "HOLD", confidence: 55, model: "Qwen/Qwen2.5-3B-Instruct", role: "macro", isCeo: false, thinking: false, calls: 38, latency: 300 },
    { key: "COMPLIANCE", label: "COMPLIANCE", name: "Sofia Bergman", title: "Head of Trading Compliance",
      expertise: ["position limits", "venue rules", "audit"],
      reason: "The clip is inside every venue limit and the audit trail is complete.", lastVote: "APPROVE", confidence: 80,
      model: "microsoft/Phi-3.5-mini-instruct", role: "compliance", isCeo: false, thinking: false, calls: 38, latency: 280 },
  ],
  ceo: { key: "CEO", label: "CEO", name: "Naveed", title: "Head of Desk", isCeo: true, thinking: false,
    reason: "Rule written: when the trade is a regime call, take the index, not the single name.",
    said: "Rule written: when the trade is a regime call, take the index, not the single name.",
    lastVote: "APPROVE", confidence: 68, model: "Qwen/Qwen2.5-14B-Instruct", role: "ceo", calls: 17, latency: 900 },
  positions: [
    { trade_id: "T-9D0AC4", symbol: "ARB/USDT", side: "LONG", entry: 1.1412, price: 1.1601, stop: 1.1203, target: 1.1889, qty: 420, pnl: 7.9, pnl_pct: 1.66, dollar_risk: 32.1 },
    { trade_id: "T-91B77E", symbol: "SOL/USDT", side: "SHORT", entry: 141.2, price: 139.8, stop: 143.4, target: 136.1, qty: 12, pnl: 16.8, pnl_pct: 0.99, dollar_risk: 26.4 },
  ],
  closed: [
    { trade_id: "T-8123AA", symbol: "INJ/USDT", side: "LONG", entry: 24.1, exit_price: 24.9, pnl: 21.4, pnl_pct: 3.31 },
  ],
  equity_curve: Array.from({ length: 40 }, (_, i) => ({ t: now - 1600 + i * 40, equity: 15000 + Math.sin(i / 3) * 120 + i * 17 })),
  registry: {
    QUANT: { key: "QUANT", label: "QUANT", model: "Qwen/Qwen2.5-7B-Instruct", role: "quant", is_ceo: false },
    RISK: { key: "RISK", label: "RISK", model: "mistralai/Mistral-7B-Instruct-v0.3", role: "risk", is_ceo: false },
    NEWS: { key: "NEWS", label: "NEWS", model: "HuggingFaceH4/zephyr-7b-beta", role: "news", is_ceo: false },
    MACRO: { key: "MACRO", label: "MACRO", model: "Qwen/Qwen2.5-3B-Instruct", role: "macro", is_ceo: false },
    COMPLIANCE: { key: "COMPLIANCE", label: "COMPLIANCE", model: "microsoft/Phi-3.5-mini-instruct", role: "compliance", is_ceo: false },
    CEO: { key: "CEO", label: "CEO", model: "Qwen/Qwen2.5-14B-Instruct", role: "ceo", is_ceo: true },
  },
  recent_councils: [
    {
      id: "T-9D0AC4", symbol: "ARB/USDT", side: "LONG", strategy: "MOMENTUM_BREAKOUT",
      entry: 1.1412, stop: 1.1203, target: 1.1889, rr: 2.28, score: 0.61,
      approvals: 4, rejections: 1, route: "ESCALATED", decision: "ENTER", confidence: 71,
      ts: now - 120, opened: true,
      verdicts: [
        { cabin: "QUANT", verdict: "APPROVE", confidence: 68, reason: "Momentum breakout with volume z 2.1 and a clean EMA stack.", model: "Qwen2.5-7B-Instruct", latency_ms: 470 },
        { cabin: "RISK", verdict: "APPROVE", confidence: 62, reason: "Stop is inside the ATR band; size is within the session cap.", model: "Mistral-7B-Instruct-v0.3", latency_ms: 505 },
        { cabin: "NEWS", verdict: "REJECT", confidence: 71, reason: "Headline risk around the unlock schedule; reason flagged as fragile.", model: "zephyr-7b-beta", latency_ms: 430, risk_flags: ["event risk"] },
        { cabin: "MACRO", verdict: "APPROVE", confidence: 66, reason: "BTC tailwind and risk-on regime support continuation.", model: "Qwen2.5-3B-Instruct", latency_ms: 300 },
        { cabin: "COMPLIANCE", verdict: "APPROVE", confidence: 74, reason: "No wash-trade or venue restrictions flagged.", model: "Phi-3.5-mini-instruct", latency_ms: 280 },
      ],
      ceo: { cabin: "CEO", verdict: "APPROVE", confidence: 71, reason: "One dissent on event risk, which the stop already covers. Approve at 0.8x size.", model: "Qwen2.5-14B-Instruct", latency_ms: 900 },
      scout: { symbol: "ARB/USDT", side: "LONG", verdict: "CONFIRM", conviction: 0.72, salience: 0.61, z_margin: 2.2, kc_sparsity: 0.12 },
    },
    {
      id: "T-91B77E", symbol: "SOL/USDT", side: "SHORT", strategy: "VOLATILITY_SQUEEZE",
      entry: 141.2, stop: 143.4, target: 136.1, rr: 2.3, score: 0.55,
      approvals: 2, rejections: 3, route: "ESCALATED", decision: "SKIP", confidence: 58, ts: now - 400,
      verdicts: [
        { cabin: "QUANT", verdict: "APPROVE", confidence: 60, reason: "Squeeze breakout lower with expanding ATR.", model: "Qwen2.5-7B-Instruct", latency_ms: 460 },
        { cabin: "RISK", verdict: "REJECT", confidence: 64, reason: "Reward to the next support is thin against the invalidation.", model: "Mistral-7B-Instruct-v0.3", latency_ms: 520 },
      ],
    },
  ],
  scout: {
    enabled: true, engine: "numpy LIF (FlyWire-inspired)",
    neurons: { orn: 64, ln: 260, pn: 96, kc: 192, mbon: 10 },
    synapses: 11996, judged: 42, confirmed: 17, waited: 21, contradicted: 4,
    admitted: 14, admit_rate: 0.33, min_z: 1.3, top_n: 3, rewards: 6, mean_reward: 0.41,
    plasticity_events: 6,
    last_batch: [
      { trade_id: "T-A1", symbol: "TIA/USDT", side: "SHORT", verdict: "CONFIRM", conviction: 0.81, salience: 0.6, z_margin: 3.1, admitted: true },
      { trade_id: "T-A2", symbol: "ETH/USDT", side: "LONG", verdict: "CONFIRM", conviction: 0.66, salience: 0.5, z_margin: 2.4, admitted: true },
      { trade_id: "T-A3", symbol: "HBAR/USDT", side: "LONG", verdict: "WAIT", conviction: 0.21, salience: 0.2, z_margin: 0.6, admitted: false },
    ],
  },
  debate: {
    rounds: 4,
    topic: "SOL/USDT LONG (MOMENTUM_BREAKOUT) — the council passed it 4-1. Is that the right call?",
    speakers: [
      { key: "QUANT", name: "Dr. Amara Osei", title: "Head of Quantitative Research" },
      { key: "RISK", name: "Viktor Hale", title: "Chief Risk Officer" },
      { key: "NEWS", name: "Lina Marchetti", title: "Head of News Flow and Catalysts" },
      { key: "MACRO", name: "Rahul Menon", title: "Global Macro Strategist" },
      { key: "COMPLIANCE", name: "Sofia Bergman", title: "Head of Trading Compliance and Mandate" },
      { key: "CEO", name: "Naveed", title: "Managing Partner, Head of Desk" },
    ],
    transcript: [
      { room: "desk", topic: "SOL/USDT LONG", speaker: "QUANT", name: "Dr. Amara Osei",
        label: "QUANT", model: "Qwen2.5-7B-Instruct", turn: "claim",
        text: "A 2.4 R:R only pays if the win rate holds at 46% or better.", round: 3, ts: now - 40 },
      { room: "desk", topic: "SOL/USDT LONG", speaker: "RISK", name: "Viktor Hale",
        label: "RISK", model: "Mistral-7B-Instruct-v0.3", turn: "challenge",
        text: "Where is the loss capped if the venue gaps through your stop?", round: 3, ts: now - 30 },
      { room: "desk", topic: "SOL/USDT LONG", speaker: "RISK", name: "Viktor Hale",
        label: "RISK DESK", model: "Mistral-7B-Instruct-v0.3", turn: "carry",
        text: 'Carried — "when the council splits, the smaller size is the decision". '
              + "You will hear it from me before the size goes on.",
        rule: "when the council splits, the smaller size is the decision",
        training: true, round: 4, ts: 1710000000 },
      { room: "desk", topic: "post-mortem: ARB/USDT SHORT closed -45.36 (-0.88%)",
        speaker: "QUANT", name: "Dr. Amara Osei", label: "QUANT DESK",
        model: "Qwen2.5-7B-Instruct", turn: "postmortem",
        text: "ARB/USDT closed -45.36 (-0.88%) and I was short it. My own flag was "
              + '"stop inside the noise band" — that goes into my training set as a refusal.',
        training: true, round: 4, ts: 1710000060 },
      { room: "desk", topic: "SOL/USDT LONG", speaker: "CEO", name: "Naveed",
        label: "CEO", model: "Qwen2.5-14B-Instruct", turn: "lesson",
        text: "Rule written: when a setup is extended, halve the size instead of skipping it.", round: 3, ts: now - 20 },
    ],
    lessons: [
      { topic: "SOL/USDT LONG", speaker: "CEO", speaker_label: "Naveed, Managing Partner",
        text: "when a setup is extended, halve the size instead of skipping it", ts: now - 20, round: 3 },
    ],
  },
  instruments: { selected: ["BTC/USDT", "ETH/USDT", "EUR/USD"], count: 3, classes: ["crypto", "forex"] },
  trade_log: [
    { trade_id: "T-9D0AC4", symbol: "ARB/USDT", side: "LONG", approvals: 4, rejections: 1, route: "ESCALATED", decision: "ENTER", opened: true, ts: now - 120 },
    { trade_id: "T-91B77E", symbol: "SOL/USDT", side: "SHORT", approvals: 2, rejections: 3, route: "ESCALATED", decision: "SKIP", opened: false, ts: now - 400 },
  ],
};

if (liveBase) {
  const res = await fetch(`${liveBase}/api/state`);
  if (!res.ok) {
    console.error(`live state fetch failed: ${res.status}`);
    process.exit(1);
  }
  const live = await res.json();
  if (live?.recent_councils?.length) console.log(`live payload: ${live.recent_councils.length} councils`);
  fixture.engine = live.engine ?? fixture.engine;
  fixture.council = live.council ?? fixture.council;
  fixture.desk = live.desk ?? fixture.desk;
  fixture.market = live.market ?? fixture.market;
  fixture.cabins = live.cabins ?? fixture.cabins;
  fixture.ceo = live.ceo ?? fixture.ceo;
  fixture.positions = live.positions ?? [];
  fixture.closed = live.closed ?? [];
  fixture.equity_curve = live.equity_curve ?? [];
  fixture.registry = live.registry ?? fixture.registry;
  fixture.recent_councils = live.recent_councils ?? [];
  fixture.trade_log = live.trade_log ?? [];
  fixture.scout = live.scout ?? fixture.scout;
  fixture.training = live.training ?? fixture.training;
}

const errors = [];
const dom = new JSDOM(html, {
  runScripts: "outside-only",
  pretendToBeVisual: true,
  url: "http://localhost:8000/",
});
const { window } = dom;

// ---- stubs: canvas, ResizeObserver, socket, fetch ------------------------
const ops = { fills: 0, texts: 0 };
window.HTMLCanvasElement.prototype.getContext = function getContext() {
  return {
    canvas: this,
    globalAlpha: 1, fillStyle: "", strokeStyle: "", lineWidth: 1, font: "",
    textAlign: "", textBaseline: "", lineCap: "", lineJoin: "",
    save() {}, restore() {}, setTransform() {}, clearRect() {},
    beginPath() {}, moveTo() {}, lineTo() {}, quadraticCurveTo() {}, closePath() {},
    fill() { ops.fills++; }, stroke() {}, ellipse() {}, rect() {}, clip() {},
    fillText() { ops.texts++; }, measureText(t) { return { width: String(t).length * 6 }; },
    createLinearGradient() { return { addColorStop() {} }; },
    createRadialGradient() { return { addColorStop() {} }; },
  };
};
window.ResizeObserver = class {
  observe() {} unobserve() {} disconnect() {}
};
window.WebSocket = class {
  constructor() { setTimeout(() => this.onclose?.({}), 5); }
  close() {}
  send() {}
};
const settingsFixture = {
  roster: [
    { key: "QUANT", name: "Dr. Amara Osei", title: "Head of Quantitative Research", role: "QUANT",
      is_ceo: false, slot: 0, model: "Qwen/Qwen2.5-7B-Instruct", backend: "local-hf (4-bit)",
      temperature: 0.2, expertise: ["statistical edge", "feature decay"], style: "Closes arguments with numbers.",
      key_required: false, auth: "none — local weights, ungated download", license: "open weights, ungated" },
    { key: "RISK", name: "Viktor Hale", title: "Chief Risk Officer", role: "RISK",
      is_ceo: false, slot: 1, model: "mistralai/Mistral-7B-Instruct-v0.3", backend: "local-hf (4-bit)",
      temperature: 0.15, expertise: ["tail risk"], style: "Asks what breaks first.",
      key_required: false, auth: "none", license: "open weights, ungated" },
    { key: "CEO", name: "Naveed", title: "Managing Partner, Head of Desk", role: "CEO",
      is_ceo: true, slot: 5, model: "Qwen/Qwen2.5-14B-Instruct", backend: "local-hf (4-bit)",
      temperature: 0.3, expertise: ["portfolio construction"], style: "Pays for the risk.",
      key_required: false, auth: "none", license: "open weights, ungated" },
  ],
  instruments: {
    total: 6,
    default: ["BTC/USDT"],
    classes: [
      { key: "crypto", label: "Crypto", source: "Binance public REST (keyless) → simulator fallback",
        instrument: "spot pairs", count: 2,
        symbols: [{ symbol: "BTC/USDT", name: "Bitcoin / Tether", kind: "venue" },
                  { symbol: "ETH/USDT", name: "Ether / Tether", kind: "venue" }] },
      { key: "forex", label: "Forex", source: "ECB/Frankfurter reference rates (keyless)",
        instrument: "spot FX majors and crosses", count: 2,
        symbols: [{ symbol: "EUR/USD", name: "Euro / US Dollar", kind: "rates" },
                  { symbol: "USD/JPY", name: "US Dollar / Yen", kind: "rates" }] },
    ],
  },
  selected: ["BTC/USDT", "ETH/USDT"],
  engine: { llm_mode: "mock", model_profile: "standard", market_mode: "sim", desks: 64 },
  training: {
    enabled: true, rows: 168, settled_rows: 36, curriculum_rows: 120, lesson_rows: 12,
    waiting: 2, adapters_dir: "artifacts/adapters", trained_now: false,
    desks: {
      QUANT: { rows: 26, settled: 6, adapter: null },
      RISK: { rows: 24, settled: 4, adapter: null },
      CEO: { rows: 55, settled: 23, adapter: null },
    },
  },
};

window.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/settings")) {
    return { ok: true, json: async () => settingsFixture };
  }
  if (u.includes("/api/state") || u.includes("/api/trades")) {
    return { ok: true, json: async () => fixture };
  }
  return { ok: true, json: async () => ({ ok: true }) };
};
window.console.error = (...args) => { errors.push(args.map((a) => (typeof a === "string" ? a : String(a))).join(" | ")); };
window.console.warn = (...args) => { errors.push(`warn: ${args.map(String).join(" ")}`); };

try {
  window.eval(code);
} catch (err) {
  console.error("bundle threw while booting:", err);
  process.exit(1);
}

// ---- let react paint, then inspect --------------------------------------
await new Promise((r) => setTimeout(r, 900));
const text = window.document.body.textContent ?? "";
const q = (sel) => window.document.querySelectorAll(sel).length;
const panel = (name) => window.document.querySelector(`.panel.${name}`)?.textContent ?? "";
const scratch = window.document.createElement("div");
scratch.innerHTML = panel("scout");
const scoutText = scratch.textContent ?? "";
const checks = [
  ["brand", text.includes("SOUL EXTER")],
  ["council panel", text.includes("Council")],
  ["cabin QUANT", text.includes("QUANT")],
  ["cabin COMPLIANCE", text.includes("COMPLIANCE")],
  ["ceo card", text.includes("CEO")],
  ["scout panel", q(".panel.scout") > 0],
  ["scout numbers", /\d/.test(scoutText)],
  ["book panel", q(".panel.book") > 0],
  ["cabin cards", q(".cabin-card") >= 5],
  ["market tape", text.includes("BTC")],
  ["trade record", q(".trade-row") > 0],
  ["fly verdicts", /CONFIRM|WAIT|CONTRADICT/.test(text)],
  ["equity panel", q(".spark") > 0],
  ["debate room panel", q(".panel.debate") > 0],
  ["debate names shown", /Amara Osei|Viktor Hale|Naveed/.test(text)],
  ["debate lesson on file", /halve the size|Rules this desk has agreed/i.test(text)],
];

const buttons = [...window.document.querySelectorAll("button")];

// ---- interactions: the trade drawer, then the settings drawer ------------
// the first row in the book, whatever the desk happens to be trading today —
// looking for a hard-coded symbol breaks the moment the universe changes
const tradeButton = window.document.querySelector("button.trade-row")
  ?? buttons.find((b) => (b.textContent ?? "").includes("ARB"));
let drawerOk = false;
if (tradeButton) {
  tradeButton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 200));
  const drawer = window.document.querySelector(".drawer");
  const drawerText = drawer?.textContent ?? "";
  const stages = drawer ? drawer.querySelectorAll(".stage").length : 0;
  drawerOk = !!drawer && stages >= 2 && /APPROVE|REJECT|not needed/i.test(drawerText);
  // close it again so it cannot shadow the settings drawer
  drawer?.querySelector("button")?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 120));
}
checks.push(["trade drawer has the stages", drawerOk]);

const settingsButton = buttons.find((b) => (b.textContent ?? "").trim() === "Settings");
if (settingsButton) {
  settingsButton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 300));
  const panel = window.document.querySelector(".drawer.settings");
  const t = panel?.textContent ?? "";
  checks.push(["settings drawer opens", !!panel]);
  checks.push([
    "settings roster names the desks",
    /Amara Osei|Viktor Hale|Naveed/.test(t) && /Qwen|Mistral/.test(t),
  ]);
  checks.push(["settings says there are no keys", /no API keys/i.test(t)]);
  // and the market tree behind the second tab
  const tab = [...(panel?.querySelectorAll("button.tab") ?? [])]
    .find((b) => (b.textContent ?? "").includes("Markets"));
  tab?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 150));
  const bookText = window.document.querySelector(".drawer.settings")?.textContent ?? "";
  checks.push(["market book lists the classes", /Crypto/.test(bookText) && /Forex/.test(bookText)]);
  checks.push(["market book lists forex pairs", /EUR\/USD/.test(bookText)]);
  const wantSyms = settingsFixture.instruments.classes
    .reduce((n, c) => n + c.symbols.length, 0);
  const boxes = window.document.querySelectorAll(".drawer.settings .book-grid .check.sym input");
  checks.push(["every instrument in the book has a checkbox", boxes.length === wantSyms]);
  checks.push(["class header counts what is ticked", /2\/2 ticked/.test(bookText)]);
  // the search box has to actually narrow the book, not just exist
  const search = window.document.querySelector(".drawer.settings .book-tools .search");
  checks.push(["market search box is there", !!search]);
  if (search) {
    const setValue = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, "value").set;
    setValue.call(search, "JPY");
    search.dispatchEvent(new window.Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 150));
    const left = window.document.querySelectorAll(
      ".drawer.settings .book-grid .check.sym input");
    const filtered = window.document.querySelector(".drawer.settings .book-grid")?.textContent ?? "";
    checks.push(["search narrows the book to the match",
      left.length === 1 && /USD\/JPY/.test(filtered) && !/BTC\/USDT/.test(filtered)]);
  }
} else {
  checks.push(["settings drawer opens", false]);
}

// ---- the desk chat: click a cabin, get its reasoning and its turns --------
// Close the settings drawer first so it cannot shadow the chat.
window.document.querySelector(".drawer.settings .drawer-head button")
  ?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
await new Promise((r) => setTimeout(r, 120));

// ---- the debate room: the top-bar button opens the full chat room --------
const roomButton = buttons.find((b) => /^(chat|debate) room$/i.test((b.textContent ?? "").trim()));
if (roomButton) {
  roomButton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 30));
  const room = window.document.querySelector(".room-overlay .panel.debate.room");
  checks.push(["debate room opens over the floor", !!room]);
  const rtext = room?.textContent ?? "";
  checks.push(["room names every speaker", /Amara Osei/.test(rtext) && /Naveed/.test(rtext)]);
  checks.push([
    "room shows each desk's record",
    new RegExp("\\d+/\\d+ right|not proven", "i").test(rtext),
  ]);
  checks.push([
    "room has a composer aimed at a desk",
    !!room?.querySelector(".composer input") && !!room?.querySelector(".composer select"),
  ]);
  checks.push(["room lists the rules it agreed", /Rules this desk has agreed/.test(rtext)]);
  checks.push([
    "room shows the training set",
    /trained on [\d,]+ rows/i.test(rtext.replace(/\s+/g, " ")),
  ]);
  checks.push(["room shows a desk carrying the rule", /carries the rule/.test(rtext)]);
  checks.push(["room reviews a closed trade", /after the close/.test(rtext)]);
  checks.push(["room prints the rule a turn is about", /class="rule-chip"/.test(room?.innerHTML ?? "")]);
  // the filter is the answer to "show me them getting trained"
  const filter = [...(room?.querySelectorAll("button") ?? [])]
    .find((b) => /training (only|turns)/i.test(b.textContent ?? ""));
  checks.push(["room has a training-only filter", !!filter]);
  if (filter) {
    const before = room.querySelectorAll(".turn").length;
    filter.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 30));
    const after = room.querySelectorAll(".turn").length;
    checks.push(["training filter hides the chatter", after > 0 && after < before]);
    filter.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 30));
  }
  const close = [...(room?.querySelectorAll("button") ?? [])].find((b) => (b.textContent ?? "").trim() === "close");
  close?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  checks.push(["room closes again", !window.document.querySelector(".room-overlay")]);

  // the settings drawer reports what each desk has been trained on
  const settingsButton = buttons.find((b) => /settings/i.test((b.textContent ?? "").trim()));
  settingsButton?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  // the drawer keeps whichever tab was last used, so make sure we are on "The desk"
  const deskTab = [...(window.document.querySelectorAll(".drawer.settings .tab") ?? [])]
    .find((b) => /The desk/i.test(b.textContent ?? ""));
  deskTab?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 40));
  const drawer = window.document.querySelector(".drawer.settings");
  const dtext = (drawer?.textContent ?? "").replace(/\s+/g, " ");
  checks.push(["settings shows the training set", /Training set: [\d,]+ rows/i.test(dtext)]);
  checks.push(["settings reports the adapters", /Adapters/i.test(dtext)]);
} else {
  checks.push(["debate room opens over the floor", false]);
}

const cabinCard = window.document.querySelector(".panel.rail .cabin-card")
  ?? window.document.querySelector(".cabin-card");
if (cabinCard) {
  cabinCard.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 200));
  const chat = window.document.querySelector(".drawer.chat");
  const chatText = chat?.textContent ?? "";
  checks.push(["cabin click opens its chat", !!chat]);
  checks.push([
    "chat names the desk and shows a verdict or a reason",
    /Amara Osei|Viktor Hale|Lina Marchetti|Rahul Menon|Sofia Bergman|Naveed/.test(chatText)
      && /APPROVE|REJECT|HOLD|no vote|reading the tape|waiting for/i.test(chatText),
  ]);
  checks.push(["chat has an ask box", !!chat?.querySelector("input")]);
  window.document.querySelector(".drawer.chat .drawer-head button")
    ?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 80));
} else {
  checks.push(["cabin click opens its chat", false]);
}

const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
const html_ = window.document.body.innerHTML.length;

// checks that only mean something against a real server payload
const liveChecks = liveBase ? [
  ["live: trade rows rendered", q(".trade-row") > 0],
  ["live: rows carry a symbol", /[A-Z]{2,6}/.test(q(".trade-row") ? window.document.querySelector(".trade-row").textContent : "")],
  ["live: equity is a number", /[0-9],[0-9]{3}/.test(text) || /\$[0-9]/.test(text)],
  ["live: a cabin model shown", /Qwen|Mistral|zephyr|Phi|mock|gpt|Llama/i.test(text)],
  ["live: scout read reported", /judged|confirm|wait|contradict/i.test(text)],
] : [];

// the live API contract: the roster, the instrument book and the debate room
const apiChecks = [];
if (liveBase) {
  const roster = await (await fetch(`${liveBase}/api/settings`)).json();
  const debate = await (await fetch(`${liveBase}/api/debate`)).json();
  const classes = roster?.instruments?.classes ?? [];
  const forex = classes.find((c) => c.key === "forex")?.symbols ?? [];
  apiChecks.push(
    ["live api: six desks in the roster", (roster.roster ?? []).length === 6],
    ["live api: every desk has a name and title", (roster.roster ?? []).every((r) => r.name && r.title)],
    ["live api: no API keys anywhere", (roster.roster ?? []).every((r) => r.key_required === false)],
    // the brief: five voting desks plus a head of desk, and six *different*
    // local models — not one model wearing six prompt hats
    ["live api: six desks run six different models",
      new Set((roster.roster ?? []).map((r) => r.model)).size === 6],
    ["live api: the head of desk runs its own model", (() => {
      const rs = roster.roster ?? [];
      const ceo = rs.find((r) => r.is_ceo);
      return !!ceo && rs.filter((r) => !r.is_ceo).every((r) => r.model !== ceo.model);
    })()],
    ["live api: seven asset classes offered", classes.length === 7],
    ["live api: forex pairs are selectable", forex.length >= 30],
    ["live api: every forex pair is checkable",
      forex.length === classes.find((c) => c.key === "forex")?.count],
    ["live api: badges follow the data",
      classes.every((c) => c.symbols.every((s) => ["venue", "rates", "sim"].includes(s.live ?? s.kind)))],
    ["live api: debate room knows its speakers", (debate.speakers ?? []).length >= 6],
  );

  // Ask a desk a question: the trade's numbers go into the prompt and the desk
  // answers in the room, so "why did you agree" is answerable from the floor.
  // the transcript endpoint caps what it returns, so count by timestamp, not by length
  const since = Date.now() / 1000 - 1;
  const asked = await (await fetch(`${liveBase}/api/debate/ask`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ cabin: "QUANT", question: "Why did you vote the way you did on the last trade?" }),
  })).json();
  const after = await (await fetch(`${liveBase}/api/debate`)).json();
  apiChecks.push(
    ["live api: a desk answers a direct question",
      asked?.ok === true && typeof asked?.said?.text === "string" && asked.said.text.length > 20],
    ["live api: the answer is a turn from that desk",
      asked?.said?.speaker === "QUANT" && asked?.said?.turn === "answer"],
    ["live api: the answer is in the transcript",
      (after.transcript ?? []).some((t) => t.turn === "answer" && t.speaker === "QUANT" && t.ts >= since)],
  );
}

console.log(JSON.stringify({
  mounted: html_ > 2000,
  domBytes: html_,
  canvasOps: ops,
  checks: Object.fromEntries(checks),
  liveChecks: Object.fromEntries(liveChecks),
  apiChecks: Object.fromEntries(apiChecks),
  consoleErrors: errors.slice(0, 6),
  consoleErrorCount: errors.length,
  failed,
}, null, 2));

const liveFailed = liveChecks.filter(([, ok]) => !ok).map(([name]) => name);
const apiFailed = apiChecks.filter(([, ok]) => !ok).map(([name]) => name);
if (liveFailed.length) console.error("FAILED LIVE CHECKS:", liveFailed.join(", "));
if (apiFailed.length) console.error("FAILED API CHECKS:", apiFailed.join(", "));

if (failed.length || liveFailed.length || apiFailed.length) {
  if (failed.length) console.error("FAILED UI CHECKS:", failed.join(", "));
  process.exitCode = 1;
} else {
  console.log("ui smoke: all checks passed");
}

// jsdom holds the event loop open; the checks are done, so leave deliberately
process.exit(process.exitCode ?? 0);

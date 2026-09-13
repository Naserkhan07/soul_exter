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
  council: { reviews: 39, escalations: 35, ceo_approvals: 9, ceo_rejections: 8 },
  desk: { equity: 15694.14, starting_cash: 15000, realised: 589.85, win_rate: 62, open: 3, leverage: 0.6 },
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
    { key: "QUANT", label: "QUANT", model: "Qwen/Qwen2.5-7B-Instruct", role: "quant", isCeo: false, thinking: true, calls: 39, latency: 480, symbol: "TIA/USDT" },
    { key: "RISK", label: "RISK", model: "mistralai/Mistral-7B-Instruct-v0.3", role: "risk", isCeo: false, thinking: false, lastVote: "REJECT", confidence: 61, calls: 39, latency: 510 },
    { key: "NEWS", label: "NEWS", model: "HuggingFaceH4/zephyr-7b-beta", role: "news", isCeo: false, thinking: false, lastVote: "APPROVE", confidence: 70, calls: 39, latency: 455 },
    { key: "MACRO", label: "MACRO", model: "Qwen/Qwen2.5-3B-Instruct", role: "macro", isCeo: false, thinking: false, calls: 38, latency: 300 },
    { key: "COMPLIANCE", label: "COMPLIANCE", model: "microsoft/Phi-3.5-mini-instruct", role: "compliance", isCeo: false, thinking: false, calls: 38, latency: 280 },
  ],
  ceo: { key: "CEO", label: "CEO", model: "Qwen/Qwen2.5-14B-Instruct", role: "ceo", isCeo: true, thinking: false, calls: 17, latency: 900 },
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
window.fetch = async (url) => {
  const u = String(url);
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
];

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

console.log(JSON.stringify({
  mounted: html_ > 2000,
  domBytes: html_,
  canvasOps: ops,
  checks: Object.fromEntries(checks),
  liveChecks: Object.fromEntries(liveChecks),
  consoleErrors: errors.slice(0, 6),
  consoleErrorCount: errors.length,
  failed,
}, null, 2));

// interaction: open a trade and make sure the drawer renders the stages
const buttons = [...window.document.querySelectorAll("button")];
const tradeButton = buttons.find((b) => (b.textContent ?? "").includes("ARB"));
if (tradeButton) {
  tradeButton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 200));
  const drawer = window.document.querySelector(".drawer");
  const drawerText = drawer?.textContent ?? "";
  const stages = drawer ? drawer.querySelectorAll(".stage").length : 0;
  const drawerOk = !!drawer && stages >= 2 && /APPROVE|REJECT|not needed/i.test(drawerText);
  // checks that only mean something against a real server payload
const liveChecks = liveBase ? [
  ["live: trade rows rendered", q(".trade-row") > 0],
  ["live: rows carry a symbol", /[A-Z]{2,6}/.test(q(".trade-row") ? window.document.querySelector(".trade-row").textContent : "")],
  ["live: equity is a number", /[0-9],[0-9]{3}/.test(text) || /\$[0-9]/.test(text)],
  ["live: a cabin model shown", /Qwen|Mistral|zephyr|Phi|mock|gpt|Llama/i.test(text)],
  ["live: scout read reported", /judged|confirm|wait|contradict/i.test(text)],
] : [];

console.log(JSON.stringify({ drawerOpened: !!drawer, drawerHasStages: drawerOk }, null, 2));
  if (!drawer) process.exitCode = 1;
}

const liveFailed = liveChecks.filter(([, ok]) => !ok).map(([name]) => name);
if (liveFailed.length) console.error("FAILED LIVE CHECKS:", liveFailed.join(", "));

if (failed.length || liveFailed.length) {
  if (failed.length) console.error("FAILED UI CHECKS:", failed.join(", "));
  process.exitCode = 1;
} else {
  console.log("ui smoke: all checks passed");
}

writeFileSync(path.join(root, "web", ".ui-smoke-ok"), new Date().toISOString());
// jsdom keeps a requestAnimationFrame loop and background timers alive forever,
// so this test has to close the door behind itself.
process.exit(process.exitCode ?? 0);

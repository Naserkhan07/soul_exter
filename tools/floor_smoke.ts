/**
 * Offline smoke test for the floor.
 *
 * Builds a deterministic room with traders in every state the engine can put
 * them in, steps the animation by hand, and writes the resulting frame as a
 * list of drawing ops. tools/render_floor.py turns that into a PNG, so the
 * renderer can be checked without a browser (and without a GPU).
 *
 *   node tools/floor_smoke.mjs [out.json] [--focus all|cabins|desks|doors]
 *                             [--zoom 1.0] [--size 1600x900] [--frames 120]
 */
import { writeFileSync } from "node:fs";
import { SoulFloor, demoBrief } from "../frontend/src/floor/renderer";
import { CABINS, CEO, DESK_SLOTS } from "../frontend/src/floor/layout";
import type { Cabin, Tick, Trader } from "../frontend/src/floor/types";

const argv = process.argv.slice(2);
const out = argv.find((a) => !a.startsWith("--")) ?? "/tmp/floor_frame.json";
const flag = (name: string, fallback: string): string => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const [w, h] = flag("size", "1600x900").split("x").map((v) => parseInt(v, 10));
const frames = parseInt(flag("frames", "150"), 10);
const focus = flag("focus", "all") as "all" | "cabins" | "desks" | "doors";
const zoom = parseFloat(flag("zoom", "1"));

const floor = new SoulFloor(null);
floor.resize(w, h, 1);
// The zoom rides along with the focus: "all" always fits the whole room (so the
// zoom is a no-op there by design), while the presets crop and therefore honour
// it — which is the only way to render the desk detail tiers offline.
floor.focusOn({ mode: focus, zoom });

// the desk as it is rostered in soul/brains/base.py: names, titles, local model
const ROSTER: Array<[string, string, string, string, string]> = [
  ["QUANT", "Qwen2.5-7B-Instruct", "quant", "Dr. Amara Osei", "Head of Quantitative Research"],
  ["RISK", "Mistral-7B-Instruct-v0.3", "risk", "Viktor Hale", "Chief Risk Officer"],
  ["NEWS", "zephyr-7b-beta", "news", "Lina Marchetti", "Head of News Flow and Catalysts"],
  ["MACRO", "Qwen2.5-14B-Instruct", "macro", "Rahul Menon", "Global Macro Strategist"],
  ["COMPLIANCE", "Phi-3.5-mini-instruct", "compliance", "Sofia Bergman", "Head of Trading Compliance"],
  ["CEO", "Qwen2.5-14B-Instruct", "ceo", "Marcus Vale", "Managing Partner, Head of Desk"],
];
const cabins: Cabin[] = ROSTER.map(([key, model, role, name, title]) => ({
  key,
  label: key,
  model,
  role,
  name,
  title,
  isCeo: key === "CEO",
  thinking: false,
  since: 0,
  calls: 12 + key.length,
  latency: 420 + key.length * 11,
}));
// put the room in a live-looking state: one cabin deliberating, two answered
cabins.find((c) => c.key === "NEWS")!.thinking = true;
cabins.find((c) => c.key === "NEWS")!.symbol = "TIA/USDT";
cabins.find((c) => c.key === "QUANT")!.lastVote = "APPROVE";
cabins.find((c) => c.key === "QUANT")!.confidence = 72;
cabins.find((c) => c.key === "RISK")!.lastVote = "REJECT";
cabins.find((c) => c.key === "RISK")!.confidence = 61;
cabins.find((c) => c.key === "CEO")!.thinking = true;
cabins.find((c) => c.key === "CEO")!.symbol = "ARB/USDT";

const symbols = ["SOL", "XRP", "ADA", "INJ", "TIA", "ARB", "TON", "SUI", "NEAR", "APT", "HYPE", "ZEC"];
const ticks: Tick[] = symbols.map((s, i) => ({
  symbol: `${s}/USDT`,
  price: 0.42 + i * 7.31,
  change_pct: ((i * 37) % 19) / 3 - 2.4,
}));

const N = 14;
for (let i = 0; i < N; i++) {
  const brief = demoBrief(i);
  brief.desk = { index: i % DESK_SLOTS.length, row: 0, col: 0 };
  floor.spawn(brief, { announce: true });
}
floor.setBoard(ticks);
floor.setState({ cabins, ticks });
floor.cabinThinking("NEWS");
floor.cabinVote("QUANT", "APPROVE", 72, "SOL/USDT",
  "The 24-bar drift and volume z-score are both in the top decile, and the pullback held the 20 EMA. Edge is real, size is fine at 0.75%.");
floor.cabinVote("RISK", "REJECT", 61, "TIA/USDT",
  "Correlation to the book is 1.6 and the stop sits inside the noise band. I will not underwrite this at any size.");

// step the animation deterministically, in the order the engine would do it:
// trades walk in and sit, then get called up to the cabins, then a couple leave
const dt = 1000 / 60;
const step = (n: number) => {
  for (let f = 0; f < n; f++) floor.frame(dt);
};
step(680); // everyone walks in from the welcome door and sits down

for (let i = 0; i < N; i++) {
  const id = `DEMO-${i}`;
  if (i < 4) floor.moveTo(id, CABINS[i % CABINS.length].key);
  else if (i === 4) floor.moveTo(id, "CEO");
  else if (i === 5) floor.endTrade(id, "ENTER", "unanimous 5/0");
  else if (i === 6) floor.endTrade(id, "SKIP", "risk veto 2/3");
}
step(760);

// verdicts landing while people are still walking
floor.cabinVote("NEWS", "REJECT", 58, "TIA/USDT",
  "No catalyst behind the move and the funding print is stretched. This is a chase, not a setup.");
// a debate turn landing while the floor is live: the cabins do not only vote,
// they argue with each other and the conclusion becomes a rule
floor.cabinSpeak("MACRO", "claim",
  "If the front end is repricing, express the short at index level rather than in a single high-beta name.");
floor.cabinSpeak("CEO", "lesson",
  "Rule written: when the trade is a regime call, take the index, not the single name.");
floor.float("DEMO-8", "+1.84%", "good");
floor.float("DEMO-9", "-0.62%", "bad");
step(Math.max(40, frames));

floor.refit();                       // frame whatever the scene has become
const ops = floor.paintOps();
const traders = [...floor.traders.values()] as Trader[];
const stats: Record<string, number | string> = {
  ops: ops.length,
  traders: traders.length,
  seated: traders.filter((t) => t.state === "seated").length,
  walking: traders.filter((t) => t.state === "walking").length,
  atCabin: traders.filter((t) => t.state === "in_cabin").length,
  atDoor: traders.filter((t) => t.state === "at_door").length,
  labels: ops.filter((o) => o.op === "text").length,
  cabinsPlaced: CABINS.length + 1,
  ceo: CEO.key,
};
// ---- council cards must never sit on each other ---------------------------
// The six cards are packed in screen space, so a change to a card's contents
// (a longer reason, a verdict line appearing) can silently re-introduce the
// overlap that the packing pass exists to prevent. Check the painted geometry.
const CARD_FILL = "#0c1420";
const GAP_X = 12;
const GAP_Y = 9;
const cards = ops.filter(
  (o) => o.op === "round" && String((o as { fill?: string }).fill ?? "").toLowerCase() === CARD_FILL,
) as Array<{ x: number; y: number; w: number; h: number }>;
const collisions: string[] = [];
for (let i = 0; i < cards.length; i++) {
  for (let j = i + 1; j < cards.length; j++) {
    const a = cards[i];
    const b = cards[j];
    if (a.x < b.x + b.w + GAP_X && a.x + a.w > b.x - GAP_X &&
        a.y < b.y + b.h + GAP_Y && a.y + a.h > b.y - GAP_Y) {
      collisions.push(`card ${i} (${Math.round(a.x)},${Math.round(a.y)}) vs card ${j} (${Math.round(b.x)},${Math.round(b.y)})`);
    }
  }
}
stats.cards = cards.length;
stats.cardCollisions = collisions.length;
if (cards.length < CABINS.length + 1) {
  console.error(`floor smoke: only ${cards.length} council cards painted, expected ${CABINS.length + 1}`);
  process.exit(1);
}
if (collisions.length) {
  console.error(`floor smoke: council cards collide:\n  ${collisions.join("\n  ")}`);
  process.exit(1);
}

const payload = { size: [w, h], focus, zoom, stats, ops };
writeFileSync(out, JSON.stringify(payload));
console.log(JSON.stringify({ out, ...stats }, null, 2));

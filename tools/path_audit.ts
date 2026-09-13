/**
 * Path audit: does a trade walk like a person, and never through a wall?
 *
 * The floor claims two things that are easy to draw and hard to *prove*:
 *
 *   1. a trade comes in through the welcome door, is seated at a desk, and only
 *      then stands up and visits the cabins one by one, physically going inside
 *      each one before moving on;
 *   2. nobody walks through a structure on the way — no clipping through desks,
 *      cabin glass, the platform edge or the hall.
 *
 * Both are checked here frame by frame against the real layout: the run fails
 * (exit code 1) if a trader's feet are ever inside a solid it has no business
 * being in, or if the seated-first order is broken.
 *
 *   node tools/path_audit.mjs
 */
import { SoulFloor, demoBrief } from "../frontend/src/floor/renderer";
import { CABINS, CEO, CEO_TERRACE, DESK_SLOTS, DOORS, FLOOR, PLATFORM, PLATFORM_WALK } from "../frontend/src/floor/layout";
import type { Cabin } from "../frontend/src/floor/types";

const floor = new SoulFloor(null);
floor.resize(1400, 900, 1);
floor.focusOn({ mode: "all" });
const cabinStates: Cabin[] = [...CABINS, CEO].map((c) => ({
  key: c.key,
  label: c.key,
  isCeo: c.key === "CEO",
  thinking: false,
  since: 0,
  calls: 0,
}));
floor.setState({ cabins: cabinStates });

const brief = demoBrief(0);
floor.spawn(brief);
const id = brief.id;

/** Is this point inside the penthouse? */
const insideCeoCabin = (x: number, y: number): boolean =>
  x > CEO.x && x < CEO.x + CEO.w && y > CEO.y && y < CEO.y + CEO.d;

/**
 * Every solid a walker must not be standing in, in floor coordinates.
 *
 * `ok` answers one question: is *this* trader allowed to be inside *this* solid
 * at this moment? A trader may stand at its own desk, and it may pass through
 * the doorway of the cabin it is visiting — not the glass, and not somebody
 * else's desk.
 */
interface Walker {
  state: string;
  cabin?: string;
  desk: number;
  x: number;
  y: number;
  destination?: { kind: string; cabin?: string };
}
interface Solid {
  name: string;
  x: number;
  y: number;
  w: number;
  d: number;
  ok?: (tr: Walker, lastCabin: string | null) => boolean;
}
const atOwnDesk = (tr: { desk: number }, i: number) => tr.desk === i;
const solids: Solid[] = [
  ...DESK_SLOTS.map((d, i) => ({
    name: `desk ${i}`,
    x: d.x, y: d.y + 0.16, w: 1.9, d: 1.1,
    ok: (tr: Walker) => atOwnDesk(tr, i) && (tr.state === "seated" || tr.state === "walking"),
  })),
  ...CABINS.map((c) => ({
    name: `cabin ${c.key}`,
    x: c.x, y: c.y, w: c.w, d: c.d,
    ok: (tr: Walker, lastCabin: string | null) => {
      if (tr.state === "in_cabin" && tr.cabin === c.key) return true;
      // leaving: still inside the cabin it just left, on its way to the doorway
      if (lastCabin === c.key) return true;
      // the walk in: only inside the doorway, i.e. the line the door actually is
      const heading = tr.destination?.kind === "cabin" && tr.destination.cabin === c.key;
      return heading && Math.abs(tr.x - c.doorX) <= 0.85;
    },
  })),
  {
    name: "cabin CEO",
    x: CEO.x, y: CEO.y, w: CEO.w, d: CEO.d,
    ok: (tr: Walker, lastCabin: string | null) => {
      if (tr.state === "in_cabin" && tr.cabin === "CEO") return true;
      if (lastCabin === "CEO") return true;
      const heading = tr.destination?.kind === "cabin" && tr.destination.cabin === "CEO";
      if (!heading) return false;
      // through the doorway, or already inside the room it was sent to
      return insideCeoCabin(tr.x, tr.y) || Math.abs(tr.x - CEO.doorX) <= 1.2;
    },
  },
];

/** Walkways a trader is allowed to be on, as a rough union of rectangles. */
function onWalkable(x: number, y: number, state: string, cabin: string | undefined,
                    headingCeo: boolean, lastCabin: string | null): boolean {
  if (state === "in_cabin") return true;          // inside a cabin it was sent to
  // inside the penthouse is the point of the visit, and the walk to the spot
  // it stands in happens inside the room
  if (insideCeoCabin(x, y) && (headingCeo || lastCabin === "CEO")) return true;
  if (x < -1 || x > FLOOR.w + 1 || y < -2 || y > FLOOR.d + 2) return false;
  // the platform deck and the strip in front of the cabins
  if (y >= PLATFORM.y - 1.4 && y <= PLATFORM_WALK + 0.9) return true;
  // the main floor: the desk rows, the promenade and the lobby
  if (y >= PLATFORM_WALK - 0.4 && y <= FLOOR.d - 0.05) return true;
  // the two door aprons: inside the door line, on the stairs and the threshold
  for (const door of [DOORS.entry, DOORS.exit]) {
    if (x >= door.x - 1.6 && x <= door.x + door.w + 1.6 && y <= FLOOR.d + 1.8) return true;
  }
  // the mezzanine behind the cabins, on its way to the CEO door
  if (y >= CEO_TERRACE.y - 0.5 && y <= CEO_TERRACE.y + CEO_TERRACE.d + 0.6 &&
      x >= CEO_TERRACE.x - 0.6 && x <= CEO_TERRACE.x + CEO_TERRACE.w + 0.6) return true;
  return false;
}

const issues: string[] = [];
const chain: string[] = [];
let seatedBeforeCabin = false;
let lastCabin: string | null = null;
let sawSeated = false;
let firstCabinAt = -1;

const push = (line: string): void => {
  if (chain[chain.length - 1] !== line) chain.push(line);
};

for (let i = 0; i < 7200; i++) {
  floor.frame(16);
  const tr = floor.traders.get(id);
  if (!tr) break;
  const dest = tr.destination?.kind === "cabin" ? tr.destination.cabin : tr.destination?.kind ?? "";
  push(`${tr.state}${dest ? ":" + dest : ""}`);

  if (tr.state === "seated") sawSeated = true;
  if (tr.state === "in_cabin" && tr.cabin) lastCabin = tr.cabin;
  if (tr.state === "in_cabin" && firstCabinAt < 0) {
    firstCabinAt = i;
    seatedBeforeCabin = sawSeated;
  }
  // the scripted review: all five cabins, then the CEO, then the door
  if (i === 200) ["QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE", "CEO"].forEach((k) => floor.moveTo(id, k));
  if (i === 7000) floor.endTrade(id, "ENTER", "order sent");

  for (const s of solids) {
    const inside = tr.x > s.x && tr.x < s.x + s.w && tr.y > s.y && tr.y < s.y + s.d;
    if (inside && !(s.ok?.(tr, lastCabin) ?? false)) {
      issues.push(`frame ${i}: ${tr.state}${tr.cabin ? ":" + tr.cabin : ""} standing inside ${s.name} at (${tr.x.toFixed(1)}, ${tr.y.toFixed(1)})`);
    }
  }
  const headingCeo = tr.destination?.kind === "cabin" && tr.destination.cabin === "CEO";
  if (!onWalkable(tr.x, tr.y, tr.state, tr.cabin, headingCeo, lastCabin)) {
    issues.push(`frame ${i}: ${tr.state} off the walkable floor at (${tr.x.toFixed(1)}, ${tr.y.toFixed(1)})`);
  }
  if (issues.length > 60) break;
}

const tr = floor.traders.get(id);
const cabins = ["QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE", "CEO"];
const visitOrder = chain.filter((s) => s.startsWith("in_cabin:")).map((s) => s.split(":")[1]);
const entered = cabins.filter((k) => visitOrder.includes(k));

console.log("walk chain:", chain.slice(0, 14).join(" -> "));
console.log("           ", chain.slice(-4).join(" -> "));
console.log("seated before its first cabin:", seatedBeforeCabin);
console.log("cabins entered (in_cabin):", entered.length ? entered.join(" -> ") : "(none)");
console.log("walked through a structure:", issues.length ? issues.join("\n  ") : "no");

const inOrder = cabins.every((k, i) => visitOrder.indexOf(k) === i);
const ok = issues.length === 0 && seatedBeforeCabin && inOrder && visitOrder.length === cabins.length;
console.log(ok
  ? "path audit: PASS — door -> seat -> every cabin in order -> door, nothing clipped"
  : `path audit: FAIL — order=${visitOrder.join(",")} seatedFirst=${seatedBeforeCabin} issues=${issues.length}`);
process.exit(ok ? 0 : 1);

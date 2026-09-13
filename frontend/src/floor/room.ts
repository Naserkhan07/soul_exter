/**
 * The room.
 *
 * A cut-away trading floor: tall walls on the two FAR sides (which is the only
 * way an isometric interior works — a near wall would hide the room), low glass
 * balustrades on the near sides, a raised platform of glass cabins along the
 * back for the LLM stages, and rows of desks in front of them.
 */
import {
  Projector,
  box,
  chip,
  contactShadow,
  cylinder,
  glow,
  lightPool,
  motes,
  quad,
  shadeFaces,
  shaft,
  slab,
  cardSize,
  namePlate,
  speechCard,
  woodGrain,
} from "./geom";
import { hash01, palette, rgba, shade, tint } from "./palette";
import {
  CABINS,
  CEO,
  CEO_STAIR,
  CEO_TERRACE,
  DESK_SLOTS,
  DOORS,
  FLOOR,
  PLATFORM,
  RECEPTION,
  STAIR,
  type CabinSlot,
  type DeskSlot,
} from "./layout";
import { drawCabinAgent, drawChair, drawTrader, type Facing } from "./actors";
import type { Cabin, Op, Tick, Trader, Verdict } from "./types";

export const WALL_X = -1.6;
export const WALL_Y = CEO.y - 2.2;
export const WALL_H = 8.8;

export const VERDICT_COLOR: Record<string, string> = {
  APPROVE: palette.longColor,
  REJECT: palette.shortColor,
  ABSTAIN: palette.abstainColor,
};

// ---------------------------------------------------------------------------
// floor
// ---------------------------------------------------------------------------
export function drawFloor(ops: Op[], pr: Projector, t: number): void {
  const { w, d } = FLOOR;
  // the slab itself, with a slight sheen gradient across it
  ops.push({
    op: "poly",
    pts: [pr.p(0, 0), pr.p(w, 0), pr.p(w, d), pr.p(0, d)],
    grad: {
      from: pr.p(0, 0),
      to: pr.p(w, d),
      stops: [
        [0, shade(palette.floorBase, 1.25)],
        [0.45, palette.floorBase],
        [1, shade(palette.floorBase, 0.72)],
      ],
    },
  });

  // travertine banding: alternating strips give the floor a real surface
  for (let i = 0; i < 23; i++) {
    const y = (i * d) / 23;
    ops.push({
      op: "poly",
      pts: [pr.p(0, y), pr.p(w, y), pr.p(w, y + d / 46), pr.p(0, y + d / 46)],
      fill: i % 2 ? palette.travertineA : palette.travertineB,
      alpha: 0.35,
    });
  }
  // grout lines on the other axis
  for (let i = 0; i <= 32; i++) {
    const x = (i * w) / 32;
    ops.push({
      op: "line",
      pts: [pr.p(x, 0), pr.p(x, d)],
      stroke: palette.floorGrout,
      lw: Math.max(1, pr.len(0.03)),
      alpha: 0.5,
    });
  }
  // speckle for stone texture — deterministic, so it does not crawl between frames
  for (let i = 0; i < 340; i++) {
    const x = hash01(i * 3 + 1) * w;
    const y = hash01(i * 7 + 2) * d;
    const [sx, sy] = pr.p(x, y);
    const c = hash01(i * 11 + 3) > 0.5 ? "#3a4150" : "#0d1116";
    ops.push({
      op: "ellipse",
      cx: sx,
      cy: sy,
      rx: 0.9 + hash01(i * 13) * 1.6,
      ry: 0.5 + hash01(i * 17) * 0.9,
      fill: c,
      alpha: 0.16 + hash01(i * 19) * 0.14,
    });
  }

  // carpet under the desk blocks, felt runners down the promenade
  for (const [x0, w0] of [
    [2.6, 15.4],
    [26.2, 15.4],
  ] as const) {
    quad(ops, pr, x0, 14.2, w0, 17.2, 0.012, palette.carpet, 0.85);
    ops.push({
      op: "line",
      pts: [pr.p(x0, 14.2, 0.02), pr.p(x0 + w0, 14.2, 0.02)],
      stroke: rgba(palette.wallTrim, 0.5),
      lw: Math.max(1, pr.len(0.05)),
      alpha: 0.6,
    });
  }
  quad(ops, pr, 19.4, 11.0, 6.6, 22.0, 0.014, palette.aisle, 0.9);
  quad(ops, pr, 1.0, 31.0, 44.0, 2.9, 0.014, palette.aisle, 0.55);
  // inlay border around the whole floor
  const inlay = "#3b4354";
  for (const [x0, y0, w0, d0] of [
    [0.5, 0.5, w - 1, d - 1],
  ] as const) {
    ops.push({
      op: "poly",
      pts: [pr.p(x0, y0), pr.p(x0 + w0, y0), pr.p(x0 + w0, y0 + d0), pr.p(x0, y0 + d0)],
      stroke: rgba(inlay, 0.75),
      lw: Math.max(1, pr.len(0.09)),
    });
  }
  // a polished-stone highlight that sweeps slowly across the aisle
  const sweep = 0.5 + 0.5 * Math.sin(t / 11000);
  lightPool(ops, pr, 20 + sweep * 14, 26, 5.5, palette.lampCool, 0.035, 0.02);

  // ---- floor decal: the mark of the house, in the middle of the promenade ----
  const dx = 25.0;
  const dy = 25.4;
  ops.push({
    op: "ellipse",
    cx: pr.p(dx, dy, 0.02)[0],
    cy: pr.p(dx, dy, 0.02)[1],
    rx: pr.len(4.6),
    ry: pr.len(4.6) * 0.55,
    stroke: rgba(palette.cabinAccent, 0.35),
    lw: Math.max(1, pr.len(0.06)),
  });
  ops.push({
    op: "ellipse",
    cx: pr.p(dx, dy, 0.02)[0],
    cy: pr.p(dx, dy, 0.02)[1],
    rx: pr.len(3.5),
    ry: pr.len(3.5) * 0.55,
    stroke: rgba(palette.cabinAccent, 0.22),
    lw: Math.max(1, pr.len(0.04)),
  });
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2;
    const r0 = 3.6;
    const r1 = i % 4 === 0 ? 4.4 : 4.05;
    ops.push({
      op: "line",
      pts: [pr.p(dx + Math.cos(a) * r0, dy + Math.sin(a) * r0 * 0.55, 0.02),
            pr.p(dx + Math.cos(a) * r1, dy + Math.sin(a) * r1 * 0.55, 0.02)],
      stroke: rgba(palette.cabinAccent, 0.28),
      lw: Math.max(1, pr.len(0.04)),
    });
  }
  ops.push({
    op: "text",
    x: pr.p(dx, dy - 0.9, 0.02)[0],
    y: pr.p(dx, dy - 0.9, 0.02)[1],
    text: "SOUL EXTER",
    fill: rgba(palette.cabinAccent, 0.4),
    size: Math.max(9, pr.len(0.85)),
    weight: "800",
    align: "center",
  });
  ops.push({
    op: "text",
    x: pr.p(dx, dy + 1.2, 0.02)[0],
    y: pr.p(dx, dy + 1.2, 0.02)[1],
    text: "TRADING FLOOR",
    fill: rgba(palette.textDim, 0.45),
    size: Math.max(7, pr.len(0.42)),
    weight: "600",
    align: "center",
  });
}

// ---------------------------------------------------------------------------
// walls, ceiling, ticker
// ---------------------------------------------------------------------------
export function drawWalls(ops: Op[], pr: Projector, ticks: Tick[], mode: string, t: number): void {
  const y0 = WALL_Y;
  const y1 = FLOOR.d + 1.4;

  // ---- far wall (behind the cabins), facing the camera -------------------
  ops.push({
    op: "poly",
    pts: [pr.p(WALL_X, y0, 0), pr.p(WALL_X, y1, 0), pr.p(WALL_X, y1, WALL_H), pr.p(WALL_X, y0, WALL_H)],
    grad: {
      from: pr.p(WALL_X, y0, WALL_H),
      to: pr.p(WALL_X, y1, 0),
      stops: [
        [0, shade(palette.wallBack, 1.15)],
        [0.5, palette.wallBack],
        [1, shade(palette.wallBack, 0.6)],
      ],
    },
  });
  // ---- far wall (behind the desks) ---------------------------------------
  ops.push({
    op: "poly",
    pts: [pr.p(WALL_X, WALL_Y, 0), pr.p(WALL_X + FLOOR.w + 3, WALL_Y, 0),
          pr.p(WALL_X + FLOOR.w + 3, WALL_Y, WALL_H), pr.p(WALL_X, WALL_Y, WALL_H)],
    grad: {
      from: pr.p(WALL_X, WALL_Y, WALL_H),
      to: pr.p(WALL_X + FLOOR.w + 3, WALL_Y, 0),
      stops: [
        [0, shade(palette.wallBack, 1.05)],
        [1, shade(palette.wallBack, 0.55)],
      ],
    },
  });
  // wall trim where the walls meet the floor
  ops.push({
    op: "poly",
    pts: [pr.p(WALL_X, y0, 0), pr.p(WALL_X, y1, 0), pr.p(WALL_X, y1, 0.22), pr.p(WALL_X, y0, 0.22)],
    fill: palette.wallTrim,
    alpha: 0.9,
  });
  ops.push({
    op: "poly",
    pts: [pr.p(WALL_X, WALL_Y, 0.22), pr.p(WALL_X + FLOOR.w + 3, WALL_Y, 0.22),
          pr.p(WALL_X + FLOOR.w + 3, WALL_Y, 0.0), pr.p(WALL_X, WALL_Y, 0.0)],
    fill: palette.wallTrim,
    alpha: 0.9,
  });

  // ---- vertical pilasters on the wall, for scale -------------------------
  for (let i = 0; i <= 8; i++) {
    const y = y0 + ((y1 - y0) * i) / 8;
    box(ops, pr, WALL_X, y - 0.28, 0, 0.34, 0.56, WALL_H, shadeFaces(palette.ceilingBeam, { stroke: "#0a0d12", lw: 1 }), {
      only: ["right"],
    });
  }

  // ---- ceiling: only the far band, so it never hides the floor ----------
  // A dark ceiling band over the far part of the room. Without it the beams are
  // bright bars floating in a void; with it they read as a roof.
  ops.push({
    op: "poly",
    pts: [pr.p(WALL_X, WALL_Y, 7.8), pr.p(WALL_X + FLOOR.w + 3, WALL_Y, 7.8),
          pr.p(WALL_X + FLOOR.w + 3, 5.6, 7.8), pr.p(WALL_X, 5.6, 7.8)],
    grad: {
      from: pr.p(WALL_X, WALL_Y, 7.8),
      to: pr.p(WALL_X + FLOOR.w + 3, 5.6, 7.8),
      stops: [
        [0, "#0d131c"],
        [0.6, "#0a0f16"],
        [1, "rgba(6,9,13,0.0)"],
      ],
    },
  });
  const beams = 7;
  for (let i = 0; i <= beams; i++) {
    const x = WALL_X + ((FLOOR.w + 3) * i) / beams;
    box(ops, pr, x - 0.22, WALL_Y, 7.35, 0.44, 12.4, 0.42,
      { top: shade(palette.ceilingBeam, 0.55), left: shade(palette.ceilingBeam, 0.95),
        right: shade(palette.ceilingBeam, 0.62), stroke: "#070a0f", lw: 1 },
      { only: ["top", "left", "right"] });
  }
  // light strips under those beams, and the shafts they throw
  for (let i = 0; i < 4; i++) {
    const x = WALL_X + 4 + i * 11;
    box(ops, pr, x, WALL_Y + 2.4, 7.1, 0.5, 4.0, 0.18, shadeFaces(palette.lampCool));
    shaft(ops, pr, x + 0.25, WALL_Y + 4.4, 6.9, 0.3, 0.44, 1.9, palette.lampCool, 0.055);
    lightPool(ops, pr, x + 0.25, WALL_Y + 4.4, 3.0, palette.lampCool, 0.06);
  }
  motes(ops, pr, 22, 12, 2.5, 18, 90, 4242, "#cfe4ff", 0.16);

  // ---- market wall: the ticker board above the cabins --------------------
  drawTicker(ops, pr, ticks, mode, t);
}

function drawTicker(ops: Op[], pr: Projector, ticks: Tick[], mode: string, t: number): void {
  const x0 = WALL_X + 0.3;
  const y0 = WALL_Y + 1.2;
  const w = 30;
  const h = 5.6;
  const z = 0.6;
  box(ops, pr, x0, y0, z, 0.5, w, h, shadeFaces("#111823", { stroke: "#2b3a4d", lw: 1.4 }));
  const face: Array<[number, number, number]> = [
    [x0 + 0.55, y0 + 0.4, z + h - 0.5],
    [x0 + 0.55, y0 + w - 0.4, z + h - 0.5],
    [x0 + 0.55, y0 + w - 0.4, z + 0.5],
    [x0 + 0.55, y0 + 0.4, z + 0.5],
  ];
  ops.push({
    op: "poly",
    pts: face.map(([x, y, zz]) => pr.p(x, y, zz)),
    grad: {
      from: pr.p(x0 + 0.55, y0 + 0.4, z + h - 0.5),
      to: pr.p(x0 + 0.55, y0 + w - 0.4, z + 0.5),
      stops: [
        [0, "#0a1018"],
        [1, "#0d1a28"],
      ],
    },
    stroke: "#2e3f52",
    lw: 1.4,
  });
  // header
  const [hx, hy] = pr.p(x0 + 0.6, y0 + 0.8, z + h - 1.0);
  ops.push({ op: "text", x: hx, y: hy, text: "SOUL EXTER", fill: palette.text, size: Math.max(10, pr.len(0.42)), weight: "800", align: "left" });
  ops.push({
    op: "text", x: hx, y: hy + Math.max(13, pr.len(0.55)), text: `COUNCIL FLOOR  ·  ${mode.toUpperCase()}  ·  LIVE`,
    fill: rgba(palette.cabinAccent, 0.85), size: Math.max(8, pr.len(0.3)), weight: "600", align: "left",
  });
  // rows of market data, two columns, scrolled by time
  const rows = Math.min(9, Math.max(4, Math.floor((w - 2) / 3)));
  for (let i = 0; i < rows; i++) {
    const tk = ticks[(i + Math.floor(t / 2600)) % Math.max(1, ticks.length)];
    const yy = y0 + 2.6 + i * 2.9;
    if (!tk) break;
    const [sx, sy] = pr.p(x0 + 0.6, yy, z + h - 1.6);
    const up = tk.change_pct >= 0;
    const size = Math.max(8, pr.len(0.3));
    ops.push({ op: "text", x: sx, y: sy, text: tk.symbol.replace("/USDT", ""), fill: "#cfe0f5", size: size * 1.05, weight: "700", align: "left" });
    ops.push({ op: "text", x: sx, y: sy + size * 1.25, text: tk.price.toFixed(tk.price > 100 ? 1 : 4), fill: palette.textDim, size, align: "left", mono: true });
    ops.push({
      op: "text", x: sx + pr.len(2.1), y: sy, text: `${up ? "▲" : "▼"} ${Math.abs(tk.change_pct).toFixed(2)}%`,
      fill: up ? palette.longColor : palette.shortColor, size, weight: "700", align: "left", mono: true,
    });
  }
  glow(ops, pr, x0 + 0.9, y0 + w / 2, 5.0, palette.cabinAccent, 0.05);
}

// ---------------------------------------------------------------------------
// near-side balustrades + doors
// ---------------------------------------------------------------------------
function balustrade(ops: Op[], pr: Projector, x0: number, y0: number, x1: number, y1: number, z = 0): void {
  const len = Math.hypot(x1 - x0, y1 - y0);
  const posts = Math.max(2, Math.round(len / 3.2));
  for (let i = 0; i <= posts; i++) {
    const f = i / posts;
    const x = x0 + (x1 - x0) * f;
    const y = y0 + (y1 - y0) * f;
    box(ops, pr, x - 0.08, y - 0.08, z, 0.16, 0.16, 1.05, shadeFaces("#2b3341"));
  }
  const [ax, ay] = pr.p(x0, y0, z + 1.02);
  const [bx, by] = pr.p(x1, y1, z + 1.02);
  const [cx, cy] = pr.p(x0, y0, z + 0.86);
  const [dx, dy] = pr.p(x1, y1, z + 0.86);
  ops.push({ op: "line", pts: [[ax, ay], [bx, by]], stroke: "#3c4658", lw: Math.max(1.5, pr.len(0.06)) });
  ops.push({
    op: "poly",
    pts: [[ax, ay], [bx, by], [dx, dy], [cx, cy]],
    fill: rgba(palette.cabinGlass, 0.12),
    stroke: rgba(palette.cabinGlass, 0.25),
    lw: 1,
  });
}

function door(
  ops: Op[],
  pr: Projector,
  x: number,
  w: number,
  color: string,
  label: string,
  t: number,
  active: boolean,
): void {
  const y = FLOOR.d;
  const h = 3.3;
  const post = 0.28;
  // threshold, lit and glowing onto the floor
  box(ops, pr, x - 0.2, y - 0.5, 0, w + 0.4, 1.0, 0.09, shadeFaces(shade(color, 0.75)));
  lightPool(ops, pr, x + w / 2, y + 0.4, 3.6, color, active ? 0.26 : 0.13);
  shaft(ops, pr, x + w / 2, y - 0.6, h, 0, w * 0.28, w * 0.42, color, active ? 0.16 : 0.07);

  // frame
  box(ops, pr, x - post, y - 0.5, 0, post, 1.0, h, shadeFaces(palette.doorFrame));
  box(ops, pr, x + w, y - 0.5, 0, post, 1.0, h, shadeFaces(palette.doorFrame));
  box(ops, pr, x - post, y - 0.5, h - 0.42, w + post * 2, 1.0, 0.42, shadeFaces(palette.doorFrame));
  // glass door panels, slightly ajar
  const open = active ? 0.62 : 0.24;
  box(ops, pr, x + 0.1, y - 0.35, 0, (w / 2 - 0.2) * (1 - open), 0.12, h - 0.5,
    { top: rgba(palette.doorGlass, 0.9), left: rgba(palette.cabinGlass, 0.2), right: rgba(palette.cabinGlass, 0.14), stroke: rgba(palette.cabinGlass, 0.4), lw: 1 });
  box(ops, pr, x + w / 2 + 0.1, y - 0.35, 0, (w / 2 - 0.2) * (1 - open * 0.6), 0.12, h - 0.5,
    { top: rgba(palette.doorGlass, 0.9), left: rgba(palette.cabinGlass, 0.2), right: rgba(palette.cabinGlass, 0.14), stroke: rgba(palette.cabinGlass, 0.4), lw: 1 });

  // sign board above the door
  const [sx, sy] = pr.p(x + w / 2, y - 1.0, h + 0.55);
  chip(ops, pr, sx, sy, label, color, 1, 1.25);
  // floor arrow painted at the threshold
  ops.push({
    op: "poly",
    pts: [pr.p(x + w * 0.2, y - 1.6, 0.02), pr.p(x + w * 0.5, y - 2.2, 0.02),
          pr.p(x + w * 0.8, y - 1.6, 0.02), pr.p(x + w * 0.5, y - 1.35, 0.02)],
    fill: rgba(color, active ? 0.4 : 0.18),
  });
}

export function drawNearSide(ops: Op[], pr: Projector, t: number, active: { entry: number; exit: number }): void {
  const y = FLOOR.d;
  const entryEnd = DOORS.entry.x - 0.4;
  const exitStart = DOORS.exit.x + DOORS.exit.w + 0.4;
  // balustrades left of the entry door, between the doors, and right of the exit
  balustrade(ops, pr, 0.4, y, entryEnd, y);
  balustrade(ops, pr, DOORS.entry.x + DOORS.entry.w + 0.4, y, exitStart - 0.4, y);
  balustrade(ops, pr, exitStart, y, FLOOR.w - 0.4, y);
  // right-hand side balustrade (the near-right edge)
  balustrade(ops, pr, FLOOR.w, 0.8, FLOOR.w, y - 0.4);

  door(ops, pr, DOORS.entry.x, DOORS.entry.w, palette.entryDoor, "WELCOME", t, active.entry > 0);
  door(ops, pr, DOORS.exit.x, DOORS.exit.w, palette.exitDoor, "EXIT", t, active.exit > 0);
}

// ---------------------------------------------------------------------------
// platform + stairs
// ---------------------------------------------------------------------------
export function drawPlatform(ops: Op[], pr: Projector, t: number): void {
  const p = PLATFORM;
  // slab with a stone face and an accent light strip along the front edge
  box(ops, pr, p.x, p.y, 0, p.w, p.d, p.z, shadeFaces("#1a2029", { stroke: "#0b0f15", lw: 1 }));
  ops.push({
    op: "poly",
    pts: [pr.p(p.x, p.y + p.d, p.z), pr.p(p.x + p.w, p.y + p.d, p.z),
          pr.p(p.x + p.w, p.y + p.d, p.z - 0.16), pr.p(p.x, p.y + p.d, p.z - 0.16)],
    fill: rgba(palette.cabinAccent, 0.65),
  });
  ops.push({
    op: "poly",
    pts: [pr.p(p.x, p.y + p.d, p.z - 0.5), pr.p(p.x + p.w, p.y + p.d, p.z - 0.5),
          pr.p(p.x + p.w, p.y + p.d, p.z - 0.62), pr.p(p.x, p.y + p.d, p.z - 0.62)],
    fill: rgba(palette.ceilingBeam, 0.6),
  });
  // walking surface
  quad(ops, pr, p.x + 0.3, p.y + 0.3, p.w - 0.6, p.d - 0.6, p.z + 0.002, "#222a36", 0.95);
  for (let i = 0; i <= 14; i++) {
    const x = p.x + 0.3 + ((p.w - 0.6) * i) / 14;
    ops.push({ op: "line", pts: [pr.p(x, p.y + 0.3, p.z + 0.004), pr.p(x, p.y + p.d - 0.3, p.z + 0.004)],
      stroke: rgba("#0d1117", 0.55), lw: 1 });
  }
  // balustrade along the front of the platform, broken at the stairs
  balustrade(ops, pr, p.x + 0.4, p.y + p.d - 0.2, STAIR.x - 0.2, p.y + p.d - 0.2, p.z);
  balustrade(ops, pr, STAIR.x + STAIR.w + 0.2, p.y + p.d - 0.2, p.x + p.w - 0.4, p.y + p.d - 0.2, p.z);

  drawStairs(ops, pr, t);
  drawCeoStairs(ops, pr, t);
}

function drawStairs(ops: Op[], pr: Projector, t: number): void {
  // steps up from the promenade to the cabin platform
  const steps = STAIR.steps;
  const depth = (STAIR.yBottom - STAIR.yTop) / steps;
  const rise = PLATFORM.z / steps;
  for (let i = 0; i < steps; i++) {
    const y = STAIR.yBottom - (i + 1) * depth;
    const z = i * rise;
    box(ops, pr, STAIR.x, y, 0, STAIR.w, depth, z + rise,
      shadeFaces("#2b323e", { stroke: "#171c24", lw: 1 }));
    // nosing highlight on each tread
    ops.push({
      op: "poly",
      pts: [pr.p(STAIR.x, y + depth, z + rise), pr.p(STAIR.x + STAIR.w, y + depth, z + rise),
            pr.p(STAIR.x + STAIR.w, y + depth, z + rise - 0.03), pr.p(STAIR.x, y + depth, z + rise - 0.03)],
      fill: rgba(palette.cabinAccent, 0.35),
    });
  }
  // handrails
  for (const side of [STAIR.x + 0.1, STAIR.x + STAIR.w - 0.1]) {
    const [ax, ay] = pr.p(side, STAIR.yBottom, 0.95);
    const [bx, by] = pr.p(side, STAIR.yTop, 0.95 + PLATFORM.z);
    ops.push({ op: "line", pts: [[ax, ay], [bx, by]], stroke: "#48525f", lw: Math.max(1.4, pr.len(0.07)), alpha: 0.95 });
  }
  lightPool(ops, pr, STAIR.x + STAIR.w / 2, (STAIR.yBottom + STAIR.yTop) / 2, 4.0, palette.lampWarm, 0.08);
}

function drawCeoStairs(ops: Op[], pr: Projector, t: number): void {
  const steps = 5;
  const depth = (CEO_STAIR.yBottom - CEO_STAIR.yTop) / steps;
  const rise = (CEO.z - PLATFORM.z) / steps;
  for (let i = 0; i < steps; i++) {
    const y = CEO_STAIR.yBottom - (i + 1) * depth;
    box(ops, pr, CEO_STAIR.x, y, PLATFORM.z, CEO_STAIR.w, depth, i * rise + rise,
      shadeFaces("#333a46", { stroke: "#1b2029", lw: 1 }));
  }
  lightPool(ops, pr, CEO_STAIR.x + CEO_STAIR.w / 2, CEO_STAIR.yBottom, 3.4, palette.ceoAccent, 0.12, PLATFORM.z);

  // ---- the mezzanine behind the cabin row -------------------------------
  // Walkers reach the CEO door along this deck, so it has to exist: a route
  // that crosses thin air reads as a bug even when the path behind it is right.
  const terrace = { x: CEO_TERRACE.x, y: CEO_TERRACE.y, w: CEO_TERRACE.w, d: CEO_TERRACE.d };
  slab(ops, pr, terrace.x, terrace.y, CEO.z - 0.04, terrace.w, terrace.d, 0.36,
    shadeFaces(palette.cabinFrame, { stroke: "#0b0f14", lw: 1 }));
  // plating, so the deck reads as a working surface rather than a slab of sky
  for (let i = 0; i < 7; i++) {
    const x0 = terrace.x + 1.0 + i * ((terrace.w - 2.0) / 6);
    ops.push({
      op: "line",
      pts: [pr.p(x0, terrace.y + 0.18, CEO.z - 0.03), pr.p(x0, terrace.y + terrace.d - 0.16, CEO.z - 0.03)],
      stroke: rgba("#8fa3bb", 0.07), lw: 1,
    });
  }
  // the two risers that carry the deck, standing on the platform below
  for (const px of [terrace.x + 4.2, terrace.x + terrace.w - 4.6]) {
    box(ops, pr, px, 0.3, PLATFORM.z, 0.42, 0.42, CEO.z - PLATFORM.z,
      shadeFaces("#20262f", { stroke: "#141920", lw: 1 }));
  }
  // rail along the open (front) edge — left open at the far right, where the
  // console stair lands
  const railTo = terrace.x + terrace.w - 3.2;
  box(ops, pr, terrace.x + 0.2, terrace.y + terrace.d - 0.16, CEO.z + 0.02,
    railTo - terrace.x - 0.2, 0.1, 0.76, shadeFaces("#2b323d", { stroke: "#141920", lw: 1 }));
  for (let i = 0; i <= 8; i++) {
    const px = terrace.x + 0.2 + (i / 8) * (railTo - terrace.x - 0.2);
    box(ops, pr, px - 0.045, terrace.y + terrace.d - 0.16, CEO.z + 0.02, 0.09, 0.09, 0.76,
      shadeFaces("#232a34"));
  }
  // the light strip the penthouse throws down the back of the floor
  ops.push({
    op: "poly",
    pts: [
      pr.p(terrace.x + 0.4, terrace.y + 0.12, CEO.z + 0.01),
      pr.p(terrace.x + terrace.w - 0.4, terrace.y + 0.12, CEO.z + 0.01),
      pr.p(terrace.x + terrace.w - 0.4, terrace.y + 0.12, CEO.z + 0.05),
      pr.p(terrace.x + 0.4, terrace.y + 0.12, CEO.z + 0.05),
    ],
    fill: rgba(palette.ceoAccent, 0.32),
  });
}

// ---------------------------------------------------------------------------
// cabins
// ---------------------------------------------------------------------------
export function drawCabins(
  ops: Op[],
  pr: Projector,
  cabins: Cabin[],
  t: number,
  activeSymbol: Partial<Record<string, string>>,
  occupants: Partial<Record<string, Trader>> = {},
): CardRect[] {
  // The six cards are packed as one newspaper page, not six independent
  // balloons: cabins sit close together along the back wall, so their screen
  // anchors land within a card's width of each other and a per-cabin stagger
  // alone drops one card onto its neighbour. Lay them out first, then paint.
  const wanted = [
    ...CABINS.map((slot, i) => ({ slot, state: cabins.find((c) => c.key === slot.key), isCeo: false, i })),
    { slot: CEO, state: cabins.find((c) => c.key === "CEO"), isCeo: true, i: -1 },
  ].filter((w) => pr.visible(w.slot.x + w.slot.w / 2, w.slot.y + w.slot.d * 0.4, w.slot.z, 760));

  const boxes = wanted.map((w) => {
    const anchor = cabinCardAnchor(pr, w.slot, w.isCeo, w.i);
    const card = cabinCardContent(w.state, w.isCeo ? palette.ceoAccent : palette.cabinAccent);
    const size = cardSize(pr, { ...card, lines: CARD_LINES, width: cardWidth(pr) });
    return { key: w.slot.key, anchor, w: size.w, h: size.h };
  });
  const packed = packCards(boxes);

  const cards: Array<() => void> = [];
  for (const w of wanted) {
    drawCabin(ops, pr, w.slot, w.state, t, activeSymbol[w.slot.key], w.isCeo, occupants[w.slot.key],
      packed.get(w.slot.key), cards);
  }
  // every roof is up by now: the cards go on top of the room, not inside it
  for (const paint of cards) paint();

  // Where each card ended up, so a click on a card can open that desk's chat.
  return boxes.map((b) => {
    const [px, py] = packed.get(b.key) ?? b.anchor;
    return { key: b.key, x: px - b.w / 2, y: py - b.h, w: b.w, h: b.h };
  });
}

/** A painted council card: enough to hit-test a click against. */
export interface CardRect {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Card width in screen px — the same number the painter uses. */
function cardWidth(pr: Projector): number {
  return Math.max(168, pr.len(8.2));
}

/** Where a cabin would like its card: above the roof, staggered by rank. */
function cabinCardAnchor(pr: Projector, slot: CabinSlot, isCeo: boolean, idx: number): [number, number] {
  const rank = idx < 0 ? 0 : idx % 2;
  const stagger = idx < 0 ? 1.5 : rank * 4.1;
  const dx = idx < 0 ? 0 : (rank ? 1.5 : -1.5);
  // 1.2 units of air above the roof plate: the plate carries the model id and
  // the card carries the argument, and they should not share a line.
  return pr.p(slot.x + slot.w / 2 + dx, slot.y + slot.d * 0.35, slot.z + (isCeo ? 6.8 : 5.6) + stagger);
}

/** How much of the argument a card shows. The rest is one click away. */
const CARD_LINES = 2;

function cabinCardContent(state: Cabin | undefined, base: string): { name: string; title: string; body: string; verdict?: string; confidence?: number; accent: string } {
  const thinking = !!state?.thinking;
  return {
    name: state?.name ?? state?.label ?? "",
    // No job title on the card: the desk's title and expertise live in its chat,
    // and a shorter card lets all six arguments sit close to their own cabin
    // instead of being pushed up the screen into a ladder.
    title: "",
    body: (state?.said || state?.reason || "").trim() || (thinking ? "reading the tape…" : "waiting for a trade"),
    verdict: state?.lastVote,
    confidence: state?.confidence,
    accent: voteAccent(state?.lastVote, base),
  };
}

/**
 * Greedy label packing. Each card may drift a little sideways and then upwards;
 * the first offset that clears every card already placed wins, and if the whole
 * window is full it keeps climbing until it is clear. Deterministic, so the
 * floor does not reshuffle itself between frames.
 */
function packCards(items: Array<{ key: string; anchor: [number, number]; w: number; h: number }>): Map<string, [number, number]> {
  const order = [...items].sort((a, b) => a.anchor[1] - b.anchor[1]);
  const placed: Array<{ x0: number; x1: number; y0: number; y1: number }> = [];
  const out = new Map<string, [number, number]>();
  // Cards that merely touch read as one card: two boxes sharing an edge with a
  // 3px seam looked like a single run-on paragraph in the render. Pack with a
  // gutter, not with a hairline.
  const GAPX = 12;
  const GAPY = 9;
  const hits = (b: { x0: number; x1: number; y0: number; y1: number }) =>
    placed.some((p) => b.x0 < p.x1 + GAPX && b.x1 > p.x0 - GAPX && b.y0 < p.y1 + GAPY && b.y1 > p.y0 - GAPY);
  for (const it of order) {
    const [ax, ay] = it.anchor;
    const offsets: Array<[number, number]> = [];
    for (let up = 0; up <= 360; up += 16) {
      for (const dx of [0, -26, 26, -52, 52, -78, 78]) {
        if (up === 0 && dx === 0) { offsets.push([0, 0]); continue; }
        offsets.push([dx, -up]);
      }
    }
    let chosen: [number, number] = [0, 0];
    for (const [dx, dy] of offsets) {
      const box = { x0: ax + dx - it.w / 2, x1: ax + dx + it.w / 2, y0: ay + dy - it.h, y1: ay + dy };
      if (!hits(box)) { chosen = [dx, dy]; break; }
      chosen = [dx, dy];
    }
    const [px, py] = [ax + chosen[0], ay + chosen[1]];
    placed.push({ x0: px - it.w / 2, x1: px + it.w / 2, y0: py - it.h, y1: py });
    out.set(it.key, [px, py]);
  }
  return out;
}

function drawCabin(
  ops: Op[],
  pr: Projector,
  slot: CabinSlot,
  state: Cabin | undefined,
  t: number,
  activeSymbol: string | undefined,
  isCeo: boolean,
  occupant?: Trader,
  cardAt?: [number, number],
  defer?: Array<() => void>,
): void {
  // off-screen cabins (and their cards) are not painted at all
  if (!pr.visible(slot.x + slot.w / 2, slot.y + slot.d * 0.4, slot.z, 760)) return;
  const accent = isCeo ? palette.ceoAccent : palette.cabinAccent;
  const thinking = !!state?.thinking;
  const vote = state?.lastVote;
  const z = slot.z;
  const pulse = thinking ? 0.5 + 0.5 * Math.sin(t / 320) : 0;
  const interior = isCeo ? tint(palette.ceoInterior, "#ff9d3d", 0.4) : palette.cabinInterior;
  const wallT = 2.9;

  // ---- slab + interior ---------------------------------------------------
  box(ops, pr, slot.x, slot.y, z, slot.w, slot.d, 0.18, shadeFaces(palette.cabinFloor, { stroke: "#0b0f15", lw: 1 }));
  const [icx, icy] = [slot.x + slot.w / 2, slot.y + slot.d / 2];
  lightPool(ops, pr, icx, icy, slot.w * 0.44, interior, thinking ? 0.16 + pulse * 0.24 : 0.2, z + 0.2);
  quad(ops, pr, slot.x + 0.3, slot.y + 0.3, slot.w - 0.6, slot.d - 0.6, z + 0.2, "#2b3240", 0.85);

  // ---- screen wall at the back of the cabin ------------------------------
  const sw = slot.w - 1.0;
  const screenX = slot.x + 0.5;
  const screenY = slot.y + 0.22;
  box(ops, pr, screenX, screenY, z + 0.2, 0.18, sw, 1.5, shadeFaces("#111722", { stroke: "#0a0d13", lw: 1 }));
  // the wall of charts, angled toward the camera
  ops.push({
    op: "poly",
    pts: [pr.p(screenX + 0.2, screenY + 0.1, z + 1.62), pr.p(screenX + 0.2, screenY + sw - 0.1, z + 1.62),
          pr.p(screenX + 0.2, screenY + sw - 0.1, z + 0.42), pr.p(screenX + 0.2, screenY + 0.1, z + 0.42)],
    grad: {
      from: pr.p(screenX + 0.2, screenY + 0.1, z + 1.62),
      to: pr.p(screenX + 0.2, screenY + sw - 0.1, z + 0.42),
      stops: [
        [0, "#0b1a28"],
        [1, "#08111c"],
      ],
    },
    stroke: rgba(accent, 0.45),
    lw: 1.1,
  });
  // a couple of chart traces on the wall
  for (let c = 0; c < 2; c++) {
    const pts: Array<[number, number]> = [];
    const yb = screenY + 0.4 + c * (sw - 0.6) / 2;
    for (let i = 0; i <= 14; i++) {
      const f = i / 14;
      const val = 0.5 + 0.3 * Math.sin(f * 6 + c * 2 + t / (3000 + c * 900)) + (hash01(i * 7 + c * 13) - 0.5) * 0.2;
      pts.push(pr.p(screenX + 0.24, yb + f * ((sw - 0.8) / 2), z + 0.5 + val * 0.75));
    }
    ops.push({ op: "line", pts, stroke: c === 0 ? rgba(accent, 0.9) : rgba(palette.longColor, 0.75), lw: Math.max(1, pr.len(0.035)) });
  }
  ops.push({ op: "text", x: pr.p(screenX + 0.3, screenY + sw - 0.4, z + 1.34)[0], y: pr.p(screenX + 0.3, screenY + sw - 0.4, z + 1.34)[1],
    text: isCeo ? "FINAL DECISION" : (state?.label ?? slot.key), fill: rgba(accent, 0.95), size: Math.max(8, pr.len(0.3)), weight: "800", align: "left" });

  // ---- console desk + chair + agent --------------------------------------
  const deskZ = z + 0.2;
  box(ops, pr, slot.x + slot.w - 2.4, slot.y + 1.1, deskZ, 1.7, 2.6, 0.72, shadeFaces("#2f3743", { stroke: "#161b22", lw: 1 }));
  // console screens facing the agent
  for (let i = 0; i < 2; i++) {
    box(ops, pr, slot.x + slot.w - 2.5 - i * 0.1, slot.y + 1.25 + i * 1.25, deskZ + 0.72, 0.12, 0.95, 0.62,
      shadeFaces("#0c1219", { stroke: "#1d2733", lw: 1 }));
    ops.push({
      op: "poly",
      pts: [pr.p(slot.x + slot.w - 2.44, slot.y + 1.3 + i * 1.25, deskZ + 1.3),
            pr.p(slot.x + slot.w - 2.44, slot.y + 2.16 + i * 1.25, deskZ + 1.3),
            pr.p(slot.x + slot.w - 2.44, slot.y + 2.16 + i * 1.25, deskZ + 0.78),
            pr.p(slot.x + slot.w - 2.44, slot.y + 1.3 + i * 1.25, deskZ + 0.78)],
      fill: rgba(i === 0 ? accent : "#7fd6ff", thinking ? 0.5 + pulse * 0.3 : 0.3),
    });
  }
  drawCabinAgent(ops, pr, slot.x + slot.w - 3.1, slot.y + 2.5, deskZ, "-x", accent, thinking, t);

  // ---- the trader who walked in -------------------------------------------
  // Drawn here, not with the walkers, so the glass wall in front of them is
  // painted afterwards: a trade that is being reviewed is *inside* the cabin,
  // which is where the brief says it has to go. The plate above their head
  // still carries the asset, so nobody in the room is anonymous.
  if (occupant) {
    // Deeper into the room than the doorway: the brief is explicit that a trade
    // has to go *in* every cabin, so the visitor stands beside the desk, inside
    // the glass, with the model's own agent at the console next to them.
    const [ix, iy, iz] = [slot.x + slot.w * 0.34, slot.y + slot.d * 0.44, deskZ];
    drawTrader(ops, pr, { ...occupant, x: ix, y: iy } as Trader, t, {
      label: occupant.symbol,
      sublabel: occupant.side,
      accent: occupant.side === "SHORT" ? palette.shortColor : palette.longColor,
      side: occupant.side,
      plateScale: 0.8,
    });
  }

  // ---- who is in there, and what they think ------------------------------
  // Two cards above the roof: the desk's name and title, and the argument they
  // just made. The verdict card is the answer to "why did this one agree?" —
  // it stays up until the next trade replaces it, so the floor is readable
  // without opening anything.
  // One card per cabin: who is in there, how they voted, and why — in their
  // own words. It sits above the roof, staggered so five of them across the
  // back of the room do not stack on top of each other.
  const idx = isCeo ? -1 : CABINS.findIndex((c) => c.key === slot.key);
  const [nx, ny] = cardAt ?? cabinCardAnchor(pr, slot, isCeo, idx);
  const card = cabinCardContent(state, accent);
  const head = isCeo ? 5.6 : 4.4;
  const roof = pr.p(slot.x + slot.w / 2, slot.y + slot.d * 0.9, z + head);
  // A stem from the roof up to the card: it is what makes a box of text read as
  // *this* cabin's voice rather than as a floating HUD element.
  if (ny < roof[1] - 4) {
    ops.push({ op: "line", pts: [roof, [nx, ny]], stroke: rgba(accent, 0.32), lw: 1.2 });
    ops.push({ op: "ellipse", cx: roof[0], cy: roof[1], rx: 2.4, ry: 1.4, fill: rgba(accent, 0.55) });
  }
  const paintCard = () =>
    speechCard(ops, pr, nx, ny, {
      ...card,
      tone: state?.said ? "live" : "idle",
      width: cardWidth(pr),
      lines: CARD_LINES,
      alpha: state ? 0.97 : 0.72,
    });
  // Cabins are painted back to front and the CEO box is the tallest, so a card
  // painted inside its own cabin's turn gets covered by the next cabin along.
  // The caller flushes the cards after the last roof is up.
  if (defer) defer.push(paintCard);
  else paintCard();
  // a plant, because every floor has one
  cylinder(ops, pr, slot.x + slot.w - 0.7, slot.y + slot.d - 0.7, deskZ, 0.26, 0.36, "#3a3327");
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2 + 0.4;
    ops.push({
      op: "ellipse",
      cx: pr.p(slot.x + slot.w - 0.7, slot.y + slot.d - 0.7, deskZ + 0.5 + i * 0.05)[0],
      cy: pr.p(slot.x + slot.w - 0.7, slot.y + slot.d - 0.7, deskZ + 0.5 + i * 0.05)[1],
      rx: pr.len(0.22), ry: pr.len(0.14),
      fill: shade("#3f7a4a", 0.8 + i * 0.06), alpha: 0.95,
    });
  }

  // ---- glass walls: front and the +x side --------------------------------
  const glassStyle = {
    top: rgba(palette.cabinGlass, 0.1),
    left: rgba(palette.cabinGlass, 0.14),
    right: rgba(palette.cabinGlass, 0.08),
    stroke: rgba(palette.cabinGlass, 0.34),
    lw: 1.1,
  };
  // front (-x side, the one facing the promenade... meaning the +x face of the box)
  ops.push({
    op: "poly",
    pts: [pr.p(slot.x + slot.w, slot.y + 0.1, z + wallT), pr.p(slot.x + slot.w, slot.y + slot.d - 0.1, z + wallT),
          pr.p(slot.x + slot.w, slot.y + slot.d - 0.1, z + 0.2), pr.p(slot.x + slot.w, slot.y + 0.1, z + 0.2)],
    grad: {
      from: pr.p(slot.x + slot.w, slot.y + 0.1, z + wallT),
      to: pr.p(slot.x + slot.w, slot.y + slot.d - 0.1, z + 0.2),
      stops: [
        [0, rgba(palette.cabinGlass, 0.2)],
        [0.42, rgba(palette.cabinGlass, 0.07)],
        [0.58, rgba("#ffffff", 0.06)],
        [1, rgba(palette.cabinGlass, 0.12)],
      ],
    },
    stroke: rgba(palette.cabinGlass, 0.36),
    lw: 1.1,
  });
  // side wall
  ops.push({
    op: "poly",
    pts: [pr.p(slot.x + 0.1, slot.y + slot.d, z + wallT), pr.p(slot.x + slot.w, slot.y + slot.d, z + wallT),
          pr.p(slot.x + slot.w, slot.y + slot.d, z + 0.2), pr.p(slot.x + 0.1, slot.y + slot.d, z + 0.2)],
    grad: {
      from: pr.p(slot.x + 0.1, slot.y + slot.d, z + wallT),
      to: pr.p(slot.x + slot.w, slot.y + slot.d, z + 0.2),
      stops: [
        [0, rgba("#ffffff", 0.09)],
        [0.5, rgba(palette.cabinGlass, 0.05)],
        [1, rgba(palette.cabinGlass, 0.13)],
      ],
    },
    stroke: rgba(palette.cabinGlass, 0.28),
    lw: 1,
  });
  // an open doorway on the promenade side
  box(ops, pr, slot.doorX - 0.55, slot.y + slot.d - 0.06, z, 1.1, 0.12, 1.7, shadeFaces("#1a212b", { stroke: rgba(accent, 0.4), lw: 1 }));

  // ---- frame posts + roof ------------------------------------------------
  for (const [px, py] of [
    [slot.x, slot.y],
    [slot.x + slot.w, slot.y],
    [slot.x, slot.y + slot.d],
    [slot.x + slot.w, slot.y + slot.d],
  ] as const) {
    box(ops, pr, px - 0.11, py - 0.11, z, 0.22, 0.22, wallT + 0.5, shadeFaces(palette.cabinFrame, { stroke: "#12161d", lw: 1 }));
  }
  box(ops, pr, slot.x - 0.3, slot.y - 0.3, z + wallT + 0.34, slot.w + 0.6, slot.d + 0.6, 0.34,
    shadeFaces(palette.cabinRoof, { stroke: "#0b0f14", lw: 1 }));
  // roof light strip, and the light it throws down
  ops.push({
    op: "poly",
    pts: [pr.p(slot.x - 0.1, slot.y + slot.d + 0.28, z + wallT + 0.36), pr.p(slot.x + slot.w + 0.1, slot.y + slot.d + 0.28, z + wallT + 0.36),
          pr.p(slot.x + slot.w + 0.1, slot.y + slot.d + 0.28, z + wallT + 0.2), pr.p(slot.x - 0.1, slot.y + slot.d + 0.28, z + wallT + 0.2)],
    fill: rgba(accent, thinking ? 0.75 + pulse * 0.2 : 0.5),
  });
  shaft(ops, pr, icx, icy + 1.2, z + wallT + 0.3, z + 0.2, slot.w * 0.32, slot.w * 0.5, interior, thinking ? 0.1 + pulse * 0.08 : 0.07);

  // ---- name plate on the roof, readable at any zoom ----------------------
  const [lx, ly] = pr.p(icx, slot.y + slot.d + 0.42, z + wallT + 0.72);
  const label = state?.label ?? slot.key;
  const model = shortModel(state?.model);
  chip(ops, pr, lx, ly, label, accent, 1, isCeo ? 1.5 : 1.25);
  if (model) {
    ops.push({
      op: "text", x: lx, y: ly + pr.len(0.62), text: model, fill: palette.textDim,
      size: Math.max(8, pr.len(0.26)), weight: "600", align: "center",
    });
  }
  // who is in there right now
  if (activeSymbol) {
    ops.push({
      op: "text", x: lx, y: ly - pr.len(0.55), text: activeSymbol, fill: rgba(accent, 0.95),
      size: Math.max(9, pr.len(0.3)), weight: "800", align: "center",
    });
  }
  // The status light lives on the cabin base, not on the roof: the roof row is
  // where the reasoning card lands, and a chip up there ends up behind it.
  if (thinking || vote) {
    const [sx, sy] = pr.p(slot.x + 0.5, slot.y + slot.d + 0.6, z + 0.32);
    if (thinking) chip(ops, pr, sx, sy, "DELIBERATING", "#7fd6ff", 0.9 + pulse * 0.1, 0.95);
    else chip(ops, pr, sx, sy, vote as string, VERDICT_COLOR[vote as string] ?? palette.abstainColor, 0.95, 0.95);
  }
  if (vote) {
    // a wash of colour on the cabin floor + a glow at the door, so the verdict
    // is readable from across the floor
    const c = VERDICT_COLOR[vote] ?? palette.abstainColor;
    lightPool(ops, pr, icx, icy, slot.w * 0.7, c, 0.16, z + 0.24);
    glow(ops, pr, slot.doorX, slot.y + slot.d, 1.6, c, 0.22);
  }
  if (isCeo && thinking) {
    glow(ops, pr, icx, icy, slot.w * 0.85, tint(palette.ceoAccent, "#ff8a2b", 0.35), 0.13 + pulse * 0.08);
  }
}

/** "Qwen2.5-14B-Instruct" -> "Qwen2.5-14B": on a roof plate the suffix is noise. */
export function shortModel(model?: string | null): string {
  if (!model) return "";
  const tail = model.split("/").pop() ?? model;
  const short = tail
    .replace(/-?instruct$/i, "")
    .replace(/-?it$/i, "")
    .replace(/-?beta$/i, "")
    .replace(/-?chat$/i, "")
    .replace(/-v\d+(\.\d+)?$/i, "");
  const pretty = short.length > 1 && short === short.toLowerCase()
    ? short.replace(/^[a-z]/, (c) => c.toUpperCase())
    : short;
  return pretty.length > 18 ? `${pretty.slice(0, 17)}…` : pretty;
}

// ---------------------------------------------------------------------------
// desks
// ---------------------------------------------------------------------------
export function drawDesk(ops: Op[], pr: Projector, desk: DeskSlot, t: number, occupied: boolean): void {
  if (!pr.visible(desk.x + 1.6, desk.y + 1.0, 0, 300)) return;
  const { x, y } = desk;
  const z = 0.0;
  const h = 0.74;
  const { deskW: w, deskD: d } = { deskW: 1.9, deskD: 1.25 };
  void w;
  void d;
  // Level of detail. There are 75 desks, and the full desk is ~78 ops of
  // grain, mouse, mug, lamp and sparkline: about 5,800 ops a frame, three
  // quarters of everything the renderer emits. At the zoom the floor is
  // actually watched from, most of that is sub-pixel, so it is gated on scale
  // instead of being paid for on every frame.
  const lod = pr.scale >= 24 ? 2 : pr.scale >= 18 ? 1 : 0;

  contactShadow(ops, pr, x + 1.15, y + 0.7, 1.5, 0.9, 0.34);

  // legs: two metal trestles
  for (const lx of [x + 0.18, x + 1.72]) {
    box(ops, pr, lx, y + 0.16, z, 0.1, 0.1, h - 0.06, shadeFaces(palette.deskLeg));
    box(ops, pr, lx, y + 1.0, z, 0.1, 0.1, h - 0.06, shadeFaces(palette.deskLegDark));
  }
  // cable tray
  if (lod >= 1) box(ops, pr, x + 0.25, y + 0.3, z + 0.18, 1.4, 0.12, 0.07, shadeFaces("#20262f"), { only: ["top", "right"] });

  // top, with a rounded front edge suggested by a lighter strip
  box(ops, pr, x, y + 0.16, h - 0.05, 1.9, 1.1, 0.06, shadeFaces(palette.deskTop, { stroke: rgba("#20140c", 0.7), lw: 1 }));
  if (lod >= 2) woodGrain(ops, pr, x, y + 0.16, h + 0.011, 1.9, 1.1, desk.index * 17 + 5, rgba("#2b1a0e", 0.55), 6, 0.22);
  if (lod >= 1) ops.push({
    op: "poly",
    pts: [pr.p(x, y + 1.26, h), pr.p(x + 1.9, y + 1.26, h), pr.p(x + 1.9, y + 1.26, h - 0.001), pr.p(x, y + 1.26, h - 0.001)],
    fill: rgba(palette.deskEdge, 0.9),
  });

  // ---- monitor -----------------------------------------------------------
  const mx = x + 1.62;
  const my = y + 0.38;
  box(ops, pr, mx, my, h + 0.01, 0.16, 0.34, 0.12, shadeFaces("#171c24"));   // foot
  box(ops, pr, mx + 0.03, my + 0.11, h + 0.1, 0.09, 0.11, 0.3, shadeFaces("#20262f"));  // neck
  box(ops, pr, mx - 0.03, my + 0.02, h + 0.38, 0.11, 0.66, 0.44, shadeFaces(palette.monitorBezel, { stroke: "#0a0d12", lw: 1 }));
  // the screen, showing a small candle chart
  const sx0 = mx + 0.09;
  const screenTop = h + 0.78;
  const screenBot = h + 0.43;
  ops.push({
    op: "poly",
    pts: [pr.p(sx0, my + 0.06, screenTop), pr.p(sx0, my + 0.62, screenTop),
          pr.p(sx0, my + 0.62, screenBot), pr.p(sx0, my + 0.06, screenBot)],
    grad: {
      from: pr.p(sx0, my + 0.06, screenTop),
      to: pr.p(sx0, my + 0.62, screenBot),
      stops: [
        [0, "#0d2233"],
        [1, "#071119"],
      ],
    },
    stroke: rgba(palette.screenGlow, 0.4),
    lw: 1,
  });
  const seed = desk.index * 29;
  const candles = lod >= 1 ? 9 : 4;
  for (let i = 0; i < candles; i++) {
    const f0 = i / candles;
    const up = hash01(seed + i * 3) > 0.45;
    const yb = my + 0.1 + f0 * 0.5;
    const hi = 0.06 + hash01(seed + i * 5) * 0.2;
    const lo = hi + 0.08 + hash01(seed + i * 7) * 0.14;
    const c = up ? rgba(palette.longColor, 0.9) : rgba(palette.shortColor, 0.85);
    ops.push({ op: "line", pts: [pr.p(sx0, yb, screenBot + hi), pr.p(sx0, yb, screenBot + lo)], stroke: c, lw: Math.max(1, pr.len(0.02)) });
  }
  glow(ops, pr, sx0, my + 0.34, 0.9, palette.screenGlow, 0.1 + 0.02 * Math.sin(t / 700 + desk.index));

  // second, smaller screen angled the other way
  ops.push({
    op: "poly",
    pts: [pr.p(x + 1.05, y + 0.32, h + 0.62), pr.p(x + 1.5, y + 0.32, h + 0.62),
          pr.p(x + 1.5, y + 0.32, h + 0.28), pr.p(x + 1.05, y + 0.32, h + 0.28)],
    fill: rgba("#123243", 0.92),
    stroke: rgba(palette.screenGlow, 0.35),
    lw: 1,
  });
  if (lod >= 1) ops.push({ op: "line", pts: [pr.p(x + 1.1, y + 0.32, h + 0.45), pr.p(x + 1.46, y + 0.32, h + 0.5)],
    stroke: rgba(palette.longColor, 0.8), lw: Math.max(1, pr.len(0.025)) });

  // keyboard
  box(ops, pr, x + 0.35, y + 0.42, h + 0.01, 0.62, 0.26, 0.035, shadeFaces("#1b2029"));
  // mouse + pad
  if (lod >= 2) ops.push({ op: "ellipse", cx: pr.p(x + 0.28, y + 0.68, h + 0.03)[0], cy: pr.p(x + 0.28, y + 0.68, h + 0.03)[1],
    rx: pr.len(0.09), ry: pr.len(0.055), fill: "#232a34" });
  // mug / papers / headset: a desk is never empty
  if (desk.index % 3 === 0) cylinder(ops, pr, x + 0.72, y + 0.9, h, 0.075, 0.13, "#8c5a4a");
  if (lod >= 1 && desk.index % 4 === 1) {
    box(ops, pr, x + 0.12, y + 0.86, h + 0.01, 0.3, 0.22, 0.012, shadeFaces("#c9cfd8"));
    box(ops, pr, x + 0.16, y + 0.9, h + 0.02, 0.26, 0.18, 0.01, shadeFaces("#aeb5c0"));
  }
  if (lod >= 2 && desk.index % 5 === 2) {
    cylinder(ops, pr, x + 1.82, y + 1.0, h, 0.11, 0.1, "#2b3038");
    ops.push({ op: "ellipse", cx: pr.p(x + 1.82, y + 1.0, h + 0.22)[0], cy: pr.p(x + 1.82, y + 1.0, h + 0.22)[1],
      rx: pr.len(0.16), ry: pr.len(0.09), fill: shade("#4a8a5a", 0.9), alpha: 0.95 });
  }
  // a small desk lamp lending the desk its own pool of light
  if (lod >= 1 && desk.index % 2 === 0) {
    cylinder(ops, pr, x + 1.78, y + 0.32, h, 0.045, 0.32, "#3a4250");
    ops.push({ op: "ellipse", cx: pr.p(x + 1.7, y + 0.3, h + 0.4)[0], cy: pr.p(x + 1.7, y + 0.3, h + 0.4)[1],
      rx: pr.len(0.12), ry: pr.len(0.07), fill: shade(palette.lampWarm, 1.0), alpha: 0.9 });
    lightPool(ops, pr, x + 1.55, y + 0.5, 1.15, palette.lampWarm, occupied ? 0.12 : 0.07, h + 0.02);
  }
  // chair (always there — empty when the trader is away)
  drawChair(ops, pr, desk.seat[0], desk.seat[1], 0, "-x", lod);
}


// ---------------------------------------------------------------------------
// working floor furniture: lounge, war wall, planters, coffee
// ---------------------------------------------------------------------------
function sofa(ops: Op[], pr: Projector, x: number, y: number, w: number, d: number, facing: "+x" | "+y"): void {
  const base = "#2a3140";
  const seat = "#39424f";
  contactShadow(ops, pr, x + w / 2, y + d / 2, Math.max(w, d) * 0.62, Math.max(w, d) * 0.42, 0.34);
  box(ops, pr, x, y, 0, w, d, 0.34, shadeFaces(base, { stroke: "#151a21", lw: 1 }));
  box(ops, pr, x + 0.06, y + 0.06, 0.28, w - 0.12, d - 0.12, 0.12, shadeFaces(seat));
  if (facing === "+x") {
    box(ops, pr, x + w - 0.22, y, 0.3, 0.22, d, 0.5, shadeFaces(base, { stroke: "#151a21", lw: 1 }));
    for (let i = 0; i < 3; i++) {
      box(ops, pr, x + 0.05, y + 0.1 + i * ((d - 0.2) / 3), 0.36, w - 0.5, (d - 0.3) / 3, 0.1, shadeFaces(seat));
    }
  } else {
    box(ops, pr, x, y + d - 0.22, 0.3, w, 0.22, 0.5, shadeFaces(base, { stroke: "#151a21", lw: 1 }));
    for (let i = 0; i < 3; i++) {
      box(ops, pr, x + 0.1 + i * ((w - 0.2) / 3), y + 0.05, 0.36, (w - 0.3) / 3, d - 0.5, 0.1, shadeFaces(seat));
    }
  }
}

function planter(ops: Op[], pr: Projector, cx: number, cy: number, z: number, scale = 1): void {
  cylinder(ops, pr, cx, cy, z, 0.32 * scale, 0.5 * scale, "#3a3f48");
  ops.push({ op: "ellipse", cx: pr.p(cx, cy, z + 0.5 * scale)[0], cy: pr.p(cx, cy, z + 0.5 * scale)[1],
    rx: pr.len(0.3 * scale), ry: pr.len(0.18 * scale), fill: "#2b2a24" });
  for (let i = 0; i < 7; i++) {
    const a = (i / 7) * Math.PI * 2 + 0.7;
    const h = (0.6 + hash01(i * 13 + Math.round(cx * 10)) * 0.5) * scale;
    const [bx, by] = pr.p(cx + Math.cos(a) * 0.16, cy + Math.sin(a) * 0.16, z + 0.5 * scale + h * 0.5);
    const [tx, ty] = pr.p(cx + Math.cos(a) * 0.3, cy + Math.sin(a) * 0.3, z + 0.5 * scale + h);
    ops.push({ op: "line", pts: [[bx, by], [tx, ty]], stroke: shade("#3f7a4a", 0.85 + i * 0.05),
      lw: Math.max(1, pr.len(0.07 * scale)) });
    ops.push({ op: "ellipse", cx: tx, cy: ty, rx: pr.len(0.16 * scale), ry: pr.len(0.1 * scale),
      fill: shade("#4c8f57", 0.85 + hash01(i * 7) * 0.3), alpha: 0.95 });
  }
}

/** A long data wall: charts on a panel, the thing every trading floor has. */
function warWall(ops: Op[], pr: Projector, x: number, y: number, len: number, t: number): void {
  const h = 4.2;
  box(ops, pr, x, y, 0, 0.42, len, h, shadeFaces("#1b2330", { stroke: "#0c1017", lw: 1.2 }));
  const plots = 4;
  for (let i = 0; i < plots; i++) {
    const y0 = y + 0.6 + i * ((len - 1.2) / plots);
    const y1 = y0 + (len - 1.2) / plots - 0.5;
    ops.push({
      op: "poly",
      pts: [pr.p(x + 0.44, y0, h - 0.7), pr.p(x + 0.44, y1, h - 0.7),
            pr.p(x + 0.44, y1, 0.75), pr.p(x + 0.44, y0, 0.75)],
      grad: {
        from: pr.p(x + 0.44, y0, h - 0.7),
        to: pr.p(x + 0.44, y1, 0.75),
        stops: [
          [0, "#0a1a26"],
          [1, "#08131d"],
        ],
      },
      stroke: rgba(palette.cabinAccent, 0.35),
      lw: 1,
    });
    for (let k = 0; k < 2; k++) {
      const pts: Array<[number, number]> = [];
      for (let j = 0; j <= 12; j++) {
        const f = j / 12;
        const val = 0.5 + 0.3 * Math.sin(f * 5 + i * 1.7 + k * 2.2 + t / (4200 + i * 700));
        pts.push(pr.p(x + 0.46, y0 + f * (y1 - y0), 0.8 + val * (h - 1.6)));
      }
      ops.push({ op: "line", pts, stroke: k === 0 ? rgba(palette.cabinAccent, 0.8) : rgba(palette.longColor, 0.7),
        lw: Math.max(1, pr.len(0.04)) });
    }
  }
  lightPool(ops, pr, x + 1.6, y + len / 2, 5.0, palette.cabinAccent, 0.05);
}

export function drawProps(ops: Op[], pr: Projector, t: number): void {
  // ---- lounge by the welcome door: where trades wait to be seen ----------
  quad(ops, pr, 3.0, 26.6, 8.2, 5.4, 0.018, "#1d232e", 0.75);
  sofa(ops, pr, 3.4, 27.2, 3.0, 1.5, "+y");
  sofa(ops, pr, 3.4, 29.6, 3.0, 1.5, "+y");
  // low table with a bowl
  box(ops, pr, 7.0, 28.2, 0, 1.5, 0.9, 0.4, shadeFaces("#3a3128", { stroke: "#1c1712", lw: 1 }));
  cylinder(ops, pr, 7.75, 28.65, 0.4, 0.22, 0.12, "#6a5a45");
  planter(ops, pr, 4.0, 31.6, 0, 1.1);
  planter(ops, pr, 10.6, 27.4, 0, 0.9);
  // coffee / water station
  box(ops, pr, 10.9, 30.0, 0, 1.7, 0.8, 0.95, shadeFaces("#2b323d", { stroke: "#161b22", lw: 1 }));
  box(ops, pr, 11.05, 30.1, 0.95, 0.6, 0.6, 0.5, shadeFaces("#3c4553"));
  cylinder(ops, pr, 12.2, 30.4, 0.95, 0.16, 0.34, "#8fb3d9");
  lightPool(ops, pr, 11.7, 30.4, 2.4, palette.lampWarm, 0.07);

  // ---- war wall down the right-hand side ---------------------------------
  warWall(ops, pr, 48.6, 12.0, 17.0, t);
  // standing bar tables for the deskless
  for (let i = 0; i < 3; i++) {
    const x = 45.0;
    const y = 16.5 + i * 4.2;
    contactShadow(ops, pr, x, y, 0.6, 0.5, 0.3);
    cylinder(ops, pr, x, y, 0, 0.09, 0.98, "#39414e");
    cylinder(ops, pr, x, y, 0.98, 0.52, 0.06, "#5a6270");
    cylinder(ops, pr, x + 0.95, y + 0.2, 0, 0.075, 0.62, "#39414e");
    cylinder(ops, pr, x + 0.95, y + 0.2, 0.62, 0.2, 0.05, "#4a525f");
  }
  lightPool(ops, pr, 45.6, 21.0, 4.4, palette.lampWarm, 0.08);

  // ---- the promenade: planters flanking the stairs ------------------------
  planter(ops, pr, 20.9, 12.4, 0, 1.2);
  planter(ops, pr, 29.4, 12.4, 0, 1.2);
  planter(ops, pr, 20.9, 32.4, 0, 1.0);
  planter(ops, pr, 29.4, 32.4, 0, 1.0);
}

export function drawReception(ops: Op[], pr: Projector, t: number): void {
  const r = RECEPTION;
  contactShadow(ops, pr, r.x + r.w / 2, r.y + r.d / 2, 1.6, 0.9, 0.32);
  box(ops, pr, r.x, r.y, 0, r.w, r.d, 1.05, shadeFaces("#2c3340", { stroke: "#161b22", lw: 1 }));
  box(ops, pr, r.x - 0.15, r.y - 0.12, 1.05, r.w + 0.3, r.d + 0.24, 0.07, shadeFaces("#3d4756", { stroke: "#1b212a", lw: 1 }));
  // backlit sign
  ops.push({
    op: "poly",
    pts: [pr.p(r.x, r.y + r.d, 1.12), pr.p(r.x + r.w, r.y + r.d, 1.12),
          pr.p(r.x + r.w, r.y + r.d, 0.78), pr.p(r.x, r.y + r.d, 0.78)],
    fill: rgba(palette.entryDoor, 0.5),
    stroke: rgba(palette.entryDoor, 0.8),
    lw: 1,
  });
  const [sx, sy] = pr.p(r.x + r.w / 2, r.y + r.d + 0.3, 1.35);
  ops.push({ op: "text", x: sx, y: sy, text: "CHECK IN", fill: palette.text, size: Math.max(8, pr.len(0.28)), weight: "800", align: "center" });
  // terminals on the desk
  box(ops, pr, r.x + 0.4, r.y + 0.25, 1.12, 0.5, 0.4, 0.34, shadeFaces("#1a2029", { stroke: "#0b0e13", lw: 1 }));
  ops.push({ op: "poly", pts: [pr.p(r.x + 0.44, r.y + 0.27, 1.44), pr.p(r.x + 0.86, r.y + 0.27, 1.44),
    pr.p(r.x + 0.86, r.y + 0.27, 1.14), pr.p(r.x + 0.44, r.y + 0.27, 1.14)], fill: rgba("#1b4a63", 0.95) });
  // queue rope
  for (let i = 0; i < 5; i++) {
    const x = r.x - 0.6 + i * 0.9;
    box(ops, pr, x, r.y + 1.5, 0, 0.06, 0.06, 0.85, shadeFaces("#4a5364"));
    if (i < 4) {
      const [ax, ay] = pr.p(x + 0.05, r.y + 1.53, 0.82);
      const [bx, by] = pr.p(x + 0.95, r.y + 1.53, 0.82);
      ops.push({ op: "line", pts: [[ax, ay], [bx, by]], stroke: rgba("#c9a15a", 0.75), lw: Math.max(1, pr.len(0.04)) });
    }
  }
  lightPool(ops, pr, r.x + r.w / 2, r.y + r.d + 1.2, 3.4, palette.entryDoor, 0.09);
  void t;
}


function voteAccent(vote: string | undefined, fallback: string): string {
  return (vote && VERDICT_COLOR[vote]) || fallback;
}

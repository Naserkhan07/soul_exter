/**
 * People.
 *
 * Traders are drawn from simple shaded boxes in an axis-aligned local frame, so
 * the isometric look stays consistent — the same trick every 2.5D game uses.
 * They are small, but they carry most of the information on the floor: which
 * asset they are trading (on the plate above the head), which side, whether the
 * trade is winning, and what the council just said about them.
 */
import { Projector, box, chip, contactShadow, cylinder, namePlate, shadeFaces } from "./geom";
import { hash01, palette, rgba, shade } from "./palette";
import type { Op, Side, Trader, Verdict } from "./types";

export type Facing = "+x" | "-x" | "+y" | "-y";

interface Frame {
  /** shoulder axis (unit, world) */
  ax: number;
  ay: number;
  /** forward axis (unit, world) */
  bx: number;
  by: number;
}

export function frameFor(facing: Facing): Frame {
  switch (facing) {
    case "+x":
      return { ax: 0, ay: 1, bx: 1, by: 0 };
    case "-x":
      return { ax: 0, ay: 1, bx: -1, by: 0 };
    case "+y":
      return { ax: 1, ay: 0, bx: 0, by: 1 };
    default:
      return { ax: 1, ay: 0, bx: 0, by: -1 };
  }
}

/** Pick the nearest of the four iso directions for a heading in screen space. */
export function facingFor(dx: number, dy: number): Facing {
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? "+x" : "-x";
  return dy >= 0 ? "+y" : "-y";
}

interface PartOpts {
  /** offset along the shoulder axis */
  s?: number;
  /** offset along the forward axis */
  f?: number;
  /** extra lift in world units */
  lift?: number;
}

/**
 * One body part: a box of size (across the shoulders, front-to-back, tall)
 * positioned relative to the person's centre at floor level.
 */
function part(
  ops: Op[],
  pr: Projector,
  fr: Frame,
  cx: number,
  cy: number,
  z: number,
  w: number,
  d: number,
  h: number,
  style: Parameters<typeof shadeFaces>[0] extends never ? never : string,
  opts: PartOpts & { alpha?: number; extraShade?: number } = {},
): void {
  const s = opts.s ?? 0;
  const f = opts.f ?? 0;
  const ox = cx + fr.ax * s + fr.bx * f;
  const oy = cy + fr.ay * s + fr.by * f;
  // axis-aligned world extents (both axes are axis-aligned by construction)
  const wWorld = Math.abs(fr.ax) * w + Math.abs(fr.bx) * d;
  const dWorld = Math.abs(fr.ay) * w + Math.abs(fr.by) * d;
  const x = ox - wWorld / 2;
  const y = oy - dWorld / 2;
  const zz = z + (opts.lift ?? 0);
  const faces = shadeFaces(style, { alpha: opts.alpha });
  box(ops, pr, x, y, zz, wWorld, dWorld, h, faces);
  if (opts.extraShade) {
    // a darker copy of the top face reads as a collar/cuff detail
    box(ops, pr, x, y, zz + h, wWorld, dWorld, h * 0.12, shadeFaces(shade(style, opts.extraShade)));
  }
}

export interface TraderDrawOpts {
  /** 0 = started, 1 = settled; used to fade people in and out of doors */
  alpha?: number;
  /** a little colour pop on the torso for the side of the trade */
  side?: Side;
  /** seated people lean slightly over the desk */
  seated?: boolean;
  /** walking cycle phase in radians */
  gait?: number;
  /** what to print on the plate above the head */
  label?: string;
  sublabel?: string;
  accent?: string;
  showPlate?: boolean;
  plateScale?: number;
  /** low zoom: just the asset and a colour stripe */
  compactPlate?: boolean;
  /** small verdict chip floating beside the head */
  badge?: { text: string; color: string };
}

/**
 * Draw one trader and the plate above their head.
 *
 * The plate is not optional in spirit: the brief was that every person on the
 * floor — seated, walking, waiting at a cabin, leaving — shows which asset they
 * are carrying. Everything that calls this draws a plate.
 */
export function drawTrader(
  ops: Op[],
  pr: Projector,
  tr: Trader,
  t: number,
  opts: TraderDrawOpts = {},
): void {
  const alpha = opts.alpha ?? 1;
  if (alpha <= 0.02) return;
  const gait = opts.gait ?? 0;
  const walking = !opts.seated && Math.abs(Math.sin(gait)) >= 0;
  const bob = opts.seated ? 0 : Math.abs(Math.sin(gait)) * 0.035;
  const lean = opts.seated ? -0.06 : 0;

  const seed = hash01(tr.palette * 977 + Math.round(tr.spawnedAt * 1000) % 997);
  const skin = palette.skin[Math.floor(hash01(tr.palette * 31 + 7) * palette.skin.length) % palette.skin.length];
  const hair = palette.hair[Math.floor(hash01(tr.palette * 53 + 11) * palette.hair.length) % palette.hair.length];
  const shirt = palette.shirt[Math.floor(hash01(tr.palette * 17 + 3) * palette.shirt.length) % palette.shirt.length];
  const trousers = palette.trousers[Math.floor(seed * palette.trousers.length) % palette.trousers.length];

  const swing = walking ? Math.sin(gait) : 0;
  const swing2 = walking ? Math.sin(gait + Math.PI) : 0;
  const fr = frameFor(facingForWorld(tr));

  const cx = tr.x;
  const cy = tr.y;
  const z = (tr as Trader & { z?: number }).z ?? 0;

  // ---- shadow -------------------------------------------------------------
  contactShadow(ops, pr, cx, cy, 0.34, 0.3, opts.seated ? 0.36 : 0.44, z);

  // ---- legs ---------------------------------------------------------------
  const legS = 0.1;
  const legF = walking ? swing * 0.16 : -0.04;
  const legF2 = walking ? swing2 * 0.16 : 0.04;
  const hipZ = z + 0.5 + bob * 0.6;
  part(ops, pr, fr, cx, cy, hipZ - 0.46, 0.17, 0.19, 0.46, trousers, { s: -legS, f: legF, alpha });
  part(ops, pr, fr, cx, cy, hipZ - 0.46, 0.17, 0.19, 0.46, trousers, { s: legS, f: legF2, alpha });
  // shoes
  part(ops, pr, fr, cx, cy, z + 0.02, 0.16, 0.26, 0.09, "#1b1e24", {
    s: -legS, f: legF + 0.04, alpha: alpha * 0.98,
  });
  part(ops, pr, fr, cx, cy, z + 0.02, 0.16, 0.26, 0.09, "#1b1e24", {
    s: legS, f: legF2 + 0.04, alpha: alpha * 0.98,
  });

  // ---- torso --------------------------------------------------------------
  const torsoZ = hipZ + 0.02;
  const torsoH = opts.seated ? 0.52 : 0.58;
  part(ops, pr, fr, cx, cy, torsoZ, 0.42, 0.24, torsoH, shirt, { f: lean, alpha });
  // shoulders: a slightly wider slab, lit from above so people read against
  // the dark floor even at small zoom
  part(ops, pr, fr, cx, cy, torsoZ + torsoH - 0.09, 0.45, 0.26, 0.1, shade(shirt, 1.35), {
    f: lean, alpha,
  });
  if (opts.side) {
    const c = opts.side === "LONG" ? palette.longColor : palette.shortColor;
    // a lanyard in the colour of the side being traded
    part(ops, pr, fr, cx, cy, torsoZ + torsoH - 0.3, 0.055, 0.28, 0.3, c, {
      s: 0.05, f: lean + 0.02, alpha: alpha * 0.92,
    });
  }

  // ---- arms ---------------------------------------------------------------
  const shoulderZ = torsoZ + torsoH - 0.16;
  const armSwing = walking ? swing * 0.14 : 0;
  const armF = opts.seated ? -0.2 : armSwing;
  // arms reach forward onto the desk when seated
  part(ops, pr, fr, cx, cy, shoulderZ - 0.42, 0.13, 0.13, 0.46, shirt, {
    s: -0.27, f: armF, alpha,
  });
  part(ops, pr, fr, cx, cy, shoulderZ - 0.42, 0.13, 0.13, 0.46, shirt, {
    s: 0.27, f: -armSwing + (opts.seated ? -0.28 : 0), alpha,
  });
  // hands
  part(ops, pr, fr, cx, cy, shoulderZ - 0.5, 0.11, 0.11, 0.1, skin, { s: -0.27, f: armF - 0.08, alpha });
  part(ops, pr, fr, cx, cy, shoulderZ - 0.5, 0.11, 0.11, 0.1, skin, {
    s: 0.27, f: -armSwing + (opts.seated ? -0.36 : -0.08), alpha,
  });

  // ---- head ---------------------------------------------------------------
  const headZ = torsoZ + torsoH + 0.03;
  part(ops, pr, fr, cx, cy, headZ, 0.2, 0.2, 0.19, skin, { f: lean - 0.01, alpha });
  part(ops, pr, fr, cx, cy, headZ + 0.14, 0.215, 0.215, 0.1, shade(hair, 1.4), { f: lean - 0.01, alpha });
  part(ops, pr, fr, cx, cy, headZ - 0.04, 0.21, 0.21, 0.1, hair, {
    f: lean + 0.055, alpha: alpha * 0.96,
  });
  // neck
  part(ops, pr, fr, cx, cy, headZ - 0.05, 0.1, 0.1, 0.08, shade(skin, 0.88), { alpha: alpha * 0.95 });

  if (opts.showPlate === false) return;

  // ---- plate above the head ----------------------------------------------
  const [hx, hy] = pr.p(cx, cy, z + headZ + 0.34);
  namePlate(ops, pr, hx, hy, opts.label ?? tr.symbol, opts.side ?? tr.side,
    opts.accent ?? (opts.side === "SHORT" ? palette.shortColor : palette.longColor),
    { sub: opts.sublabel, alpha, scale: opts.plateScale ?? 1, compact: opts.compactPlate });

  if (opts.badge) {
    chip(ops, pr, hx, hy - 40 * Math.max(0.6, pr.scale / 26) * (opts.plateScale ?? 1),
      opts.badge.text, opts.badge.color, alpha, opts.plateScale ?? 1);
  }
}

/** A trader's world-space facing, derived from the heading it last moved along. */
function facingForWorld(tr: Trader): Facing {
  const h = tr as Trader & { heading?: { dx: number; dy: number } };
  if (h.heading) return facingFor(h.heading.dx, h.heading.dy);
  return tr.side === "SHORT" ? "-y" : "+y";
}

/** Office chair, drawn under a seated trader. */
export function drawChair(ops: Op[], pr: Projector, cx: number, cy: number, z: number,
                          facing: Facing, lod = 2): void {
  const fr = frameFor(facing);
  contactShadow(ops, pr, cx, cy, 0.3, 0.28, 0.3, z);
  cylinder(ops, pr, cx, cy, z + 0.06, 0.06, 0.34, "#2f3742");
  // seat pan
  part(ops, pr, fr, cx, cy, z + 0.4, 0.4, 0.4, 0.09, palette.chairSeat);
  // Seventy-five empty chairs were 1,900 canvas ops a frame, and at the default
  // zoom a chair is six pixels wide: the backrest, the armrests and the
  // five-star base are there when you zoom in, not when you are watching the
  // floor move.
  if (lod < 1) return;
  // backrest, behind the sitter
  part(ops, pr, fr, cx, cy, z + 0.46, 0.38, 0.09, 0.44, palette.chairBack, { f: 0.19 });
  // armrests
  part(ops, pr, fr, cx, cy, z + 0.5, 0.07, 0.3, 0.06, palette.chairPost, { s: -0.2 });
  part(ops, pr, fr, cx, cy, z + 0.5, 0.07, 0.3, 0.06, palette.chairPost, { s: 0.2 });
  // five-star base
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2;
    const bx = cx + Math.cos(a) * 0.2;
    const by = cy + Math.sin(a) * 0.2;
    const [sx, sy] = pr.p(bx, by, z + 0.02);
    const [ox, oy] = pr.p(cx, cy, z + 0.02);
    ops.push({ op: "line", pts: [[ox, oy], [sx, sy]], stroke: "#2b323d", lw: Math.max(1, pr.len(0.05)) });
  }
}

/** The little figure that lives inside a cabin: the model itself. */
export function drawCabinAgent(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  z: number,
  facing: Facing,
  accent: string,
  thinking: boolean,
  t: number,
): void {
  const fr = frameFor(facing);
  const breathe = Math.sin(t / 900) * 0.012;
  contactShadow(ops, pr, cx, cy, 0.3, 0.26, 0.34, z);
  // suit in the cabin's accent colour
  part(ops, pr, fr, cx, cy, z + 0.52 + breathe, 0.42, 0.24, 0.5, shade(accent, 0.62));
  part(ops, pr, fr, cx, cy, z + 0.52 + breathe, 0.44, 0.26, 0.1, shade(accent, 0.78), { lift: 0.4 });
  part(ops, pr, fr, cx, cy, z + 0.46 + breathe, 0.18, 0.2, 0.44, "#252c37");
  part(ops, pr, fr, cx, cy, z + 1.06 + breathe, 0.2, 0.2, 0.19, "#e8bd94");
  part(ops, pr, fr, cx, cy, z + 1.2 + breathe, 0.215, 0.215, 0.1, "#20242c");
  // arms forward, as if working a console
  part(ops, pr, fr, cx, cy, z + 0.62 + breathe, 0.12, 0.12, 0.42, shade(accent, 0.62), { s: -0.26, f: -0.18 });
  part(ops, pr, fr, cx, cy, z + 0.62 + breathe, 0.12, 0.12, 0.42, shade(accent, 0.62), { s: 0.26, f: -0.18 });
  if (thinking) {
    ops.push({
      op: "ellipse",
      cx: pr.p(cx, cy, z + 1.45)[0],
      cy: pr.p(cx, cy, z + 1.45)[1],
      rx: pr.len(0.5),
      ry: pr.len(0.5) * 0.5,
      alpha: 0.5 + 0.2 * Math.sin(t / 260),
      grad: {
        radial: true,
        from: pr.p(cx, cy, z + 1.45),
        to: [pr.p(cx, cy, z + 1.45)[0] + pr.len(0.5), pr.p(cx, cy, z + 1.45)[1]],
        stops: [
          [0, rgba(accent, 0.45)],
          [1, rgba(accent, 0)],
        ],
      },
    });
  }
}

/** Vote pennant shown on a cabin after it answers. */
export function voteColor(v: Verdict | undefined): string {
  if (v === "APPROVE") return palette.longColor;
  if (v === "REJECT") return palette.shortColor;
  return palette.abstainColor;
}

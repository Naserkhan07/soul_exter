/**
 * Geometry: isometric projection, shaded solids, light, and the label plates.
 *
 * Everything a scene is made of is emitted as a flat list of drawing ops (see
 * types.ts). That indirection is the reason this renderer can be checked: the
 * browser rasterises the ops with a canvas, and tools/render_floor.py rasterises
 * the same ops with Pillow, so the smoke test shows what actually ships.
 */
import { LIGHT, hash01, rgba, shade, tint } from "./palette";
import type { Grad, Op } from "./types";

const COS30 = 0.8660254;

/**
 * Projects floor space to screen space.
 *
 * x runs down-right, y runs down-left, z is up. A unit of z and a unit of x are
 * the same length on screen, which is the classic 2:1 look of the reference.
 */
export class Projector {
  scale: number;
  tx: number;
  ty: number;

  constructor(scale = 26, tx = 0, ty = 0) {
    this.scale = scale;
    this.tx = tx;
    this.ty = ty;
  }

  clone(scale = this.scale, tx = this.tx, ty = this.ty): Projector {
    return new Projector(scale, tx, ty);
  }

  /** world -> screen */
  p(x: number, y: number, z = 0): [number, number] {
    const s = this.scale;
    return [this.tx + (x - y) * COS30 * s, this.ty + (x + y) * 0.5 * s - z * s];
  }

  /** world distance -> screen distance */
  len(d: number): number {
    return d * this.scale;
  }

  /** viewport size in CSS pixels (0 = unknown, in which case nothing is culled) */
  vw = 0;
  vh = 0;

  /** is this world point anywhere near the visible area? */
  visible(x: number, y: number, z = 0, pad = 160): boolean {
    if (!this.vw || !this.vh) return true;
    const [px, py] = this.p(x, y, z);
    return px >= -pad && px <= this.vw + pad && py >= -pad && py <= this.vh + pad;
  }
}

export interface Faces {
  top: string;
  right: string;
  left: string;
  stroke?: string;
  lw?: number;
  alpha?: number;
}

/** Shades the three visible faces of an axis-aligned box. */
export function shadeFaces(base: string, opts: Partial<Faces> = {}): Faces {
  const l = LIGHT.fromLeft;
  return {
    top: opts.top ?? shade(base, LIGHT.topBoost),
    right: opts.right ?? shade(base, l ? LIGHT.sideBoost : 1.0),
    left: opts.left ?? shade(base, l ? 1.0 : LIGHT.sideBoost),
    stroke: opts.stroke,
    lw: opts.lw,
    alpha: opts.alpha,
  };
}

/** Push a shaded axis-aligned box. `x,y,z` is the near/bottom/left corner. */
export function box(
  ops: Op[],
  pr: Projector,
  x: number,
  y: number,
  z: number,
  w: number,
  d: number,
  h: number,
  faces: Faces,
  opts: { round?: number; only?: Array<"top" | "left" | "right">; topZ?: number } = {},
): void {
  const topZ = z + h;
  const keep = opts.only ?? ["left", "right", "top"];

  // the two side faces first (they are behind the top face)
  const sideOrder: Array<"left" | "right"> = LIGHT.fromLeft ? ["right", "left"] : ["left", "right"];
  for (const side of sideOrder) {
    if (!keep.includes(side)) continue;
    const pts: Array<[number, number]> =
      side === "right"
        ? [pr.p(x + w, y, topZ), pr.p(x + w, y + d, topZ), pr.p(x + w, y + d, z), pr.p(x + w, y, z)]
        : [pr.p(x, y + d, topZ), pr.p(x + w, y + d, topZ), pr.p(x + w, y + d, z), pr.p(x, y + d, z)];
    ops.push({
      op: "poly",
      pts,
      fill: side === "right" ? faces.right : faces.left,
      alpha: faces.alpha,
      stroke: faces.stroke,
      lw: faces.lw,
    });
  }

  if (keep.includes("top")) {
    const t = opts.topZ ?? topZ;
    ops.push({
      op: "poly",
      pts: [pr.p(x, y, t), pr.p(x + w, y, t), pr.p(x + w, y + d, t), pr.p(x, y + d, t)],
      fill: faces.top,
      alpha: faces.alpha,
      stroke: faces.stroke,
      lw: faces.lw,
    });
  }
}

/** A thin slab lying on a surface — desk tops, cabin floors, platforms. */
export function slab(
  ops: Op[],
  pr: Projector,
  x: number,
  y: number,
  z: number,
  w: number,
  d: number,
  thick: number,
  faces: Faces,
  opts: { round?: number } = {},
): void {
  box(ops, pr, x, y, z - thick, w, d, thick, faces, opts);
}

/** Flat diamond on the floor plane — rugs, light pools, painted zones. */
export function quad(
  ops: Op[],
  pr: Projector,
  x: number,
  y: number,
  w: number,
  d: number,
  z: number,
  fill: string,
  alpha = 1,
  grad?: Grad,
  stroke?: string,
): void {
  ops.push({
    op: "poly",
    pts: [pr.p(x, y, z), pr.p(x + w, y, z), pr.p(x + w, y + d, z), pr.p(x, y + d, z)],
    fill,
    alpha,
    grad,
    stroke,
  });
}

/** Vertical cylinder (mugs, plants, chair pedestals, lamps). */
export function cylinder(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  z: number,
  r: number,
  h: number,
  base: string,
  opts: { alpha?: number; sides?: number } = {},
): void {
  const rx = pr.len(r) * 1.16;
  const ry = pr.len(r) * 0.62;
  const [, sy] = pr.p(cx, cy, z);
  const [sx] = pr.p(cx, cy, z);
  const hpx = pr.len(h);
  // body: a quad between the silhouette tangents, then the top cap
  ops.push({
    op: "poly",
    pts: [
      [sx - rx, sy],
      [sx + rx, sy],
      [sx + rx, sy - hpx],
      [sx - rx, sy - hpx],
    ],
    fill: shade(base, 0.82),
    alpha: opts.alpha,
  });
  ops.push({
    op: "ellipse",
    cx: sx,
    cy: sy,
    rx,
    ry,
    fill: shade(base, 0.62),
    alpha: opts.alpha,
  });
  ops.push({
    op: "ellipse",
    cx: sx,
    cy: sy - hpx,
    rx,
    ry,
    fill: shade(base, LIGHT.topBoost),
    alpha: opts.alpha,
  });
}

/** Soft contact shadow on the floor under something at (cx, cy). */
export function contactShadow(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  strength = 0.5,
  z = 0,
): void {
  const [sx, sy] = pr.p(cx, cy, z);
  ops.push({
    op: "ellipse",
    cx: sx + pr.len(rx) * 0.12,
    cy: sy + pr.len(ry) * 0.18,
    rx: pr.len(rx),
    ry: pr.len(ry) * 0.55,
    fill: "#000000",
    alpha: strength,
    grad: {
      radial: true,
      from: [sx, sy],
      to: [sx + pr.len(rx), sy],
      stops: [
        [0, "rgba(0,0,0,0.85)"],
        [0.55, "rgba(0,0,0,0.35)"],
        [1, "rgba(0,0,0,0)"],
      ],
    },
  });
}

/** Warm pool of light on the floor (or on any horizontal surface). */
export function lightPool(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  r: number,
  color: string,
  alpha: number,
  z = 0,
): void {
  const [sx, sy] = pr.p(cx, cy, z);
  const rx = pr.len(r) * 1.3;
  ops.push({
    op: "ellipse",
    cx: sx,
    cy: sy,
    rx,
    ry: rx * 0.55,
    alpha: 1,
    grad: {
      radial: true,
      from: [sx, sy],
      to: [sx + rx, sy],
      stops: [
        [0, rgba(color, alpha)],
        [0.5, rgba(color, alpha * 0.45)],
        [1, rgba(color, 0)],
      ],
    },
  });
}

/** A light shaft: wider at the bottom, fading out. */
export function shaft(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  zTop: number,
  zBottom: number,
  wTop: number,
  wBottom: number,
  color: string,
  alpha: number,
): void {
  const [tx, ty] = pr.p(cx, cy, zTop);
  const [bx, by] = pr.p(cx, cy, zBottom);
  const wt = pr.len(wTop);
  const wb = pr.len(wBottom);
  ops.push({
    op: "poly",
    pts: [
      [tx - wt, ty],
      [tx + wt, ty],
      [bx + wb, by],
      [bx - wb, by],
    ],
    grad: {
      from: [tx, ty],
      to: [tx, by],
      stops: [
        [0, rgba(color, alpha)],
        [0.55, rgba(color, alpha * 0.42)],
        [1, rgba(color, 0)],
      ],
    },
  });
}

/** Glow around an emissive surface (screen bloom, door spill). */
export function glow(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  r: number,
  color: string,
  alpha: number,
  squash = 0.6,
): void {
  const [sx, sy] = pr.p(cx, cy);
  ops.push({
    op: "ellipse",
    cx: sx,
    cy: sy,
    rx: pr.len(r),
    ry: pr.len(r) * squash,
    grad: {
      radial: true,
      from: [sx, sy],
      to: [sx + pr.len(r), sy],
      stops: [
        [0, rgba(color, alpha)],
        [0.45, rgba(color, alpha * 0.4)],
        [1, rgba(color, 0)],
      ],
    },
  });
}

/** Wood grain: a handful of darker streaks across a desk top. */
export function woodGrain(
  ops: Op[],
  pr: Projector,
  x: number,
  y: number,
  z: number,
  w: number,
  d: number,
  seed: number,
  color: string,
  count = 5,
  alpha = 0.16,
): void {
  for (let i = 0; i < count; i++) {
    const t = (i + 0.5) / count;
    const jitter = (hash01(seed * 31 + i) - 0.5) * 0.16;
    const yy = y + d * (t + jitter);
    ops.push({
      op: "line",
      pts: [pr.p(x + 0.06, yy, z), pr.p(x + w - 0.06, yy, z)],
      stroke: color,
      lw: Math.max(1, pr.len(0.035)),
      alpha,
    });
  }
}

/**
 * Floating name plate.
 *
 * This is the label that must hover over every trader's head: the asset, the
 * side, and the live number. It is drawn screen-aligned so the text is always
 * crisp and readable no matter where the camera is.
 */
export function namePlate(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  text: string,
  side: "LONG" | "SHORT" | "NONE",
  accent: string,
  opts: { sub?: string; alpha?: number; scale?: number; wide?: boolean; compact?: boolean } = {},
): void {
  const s = (opts.scale ?? 1) * Math.max(0.5, Math.min(1.45, pr.scale / 24));
  const compact = !!opts.compact;
  const pad = (compact ? 5.5 : 7) * s;
  const fontMain = Math.round((compact ? 10 : 11) * s);
  const fontSub = Math.round(8.4 * s);
  // width from a cheap per-character estimate (no canvas measureText needed —
  // this has to work identically in the offline rasteriser)
  const wMain = text.length * fontMain * 0.62;
  const wSub = !compact && opts.sub ? opts.sub.length * fontSub * 0.56 : 0;
  const bodyW = Math.max(wMain, wSub) + pad * 2 + (opts.wide ? 8 * s : 0);
  const bodyH = (compact ? 17 : opts.sub ? 26 : 18) * s;
  const x = cx - bodyW / 2;
  const y = cy - bodyH - 6 * s;
  const alpha = opts.alpha ?? 1;

  // stem down to the head
  ops.push({
    op: "line",
    pts: [
      [cx, y + bodyH],
      [cx, cy + 1],
    ],
    stroke: rgba("#000000", 0.5 * alpha),
    lw: Math.max(1, 1.6 * s),
    alpha,
  });
  ops.push({
    op: "round",
    x: x + 1.5 * s,
    y: y + 2 * s,
    w: bodyW,
    h: bodyH,
    r: 6 * s,
    fill: "rgba(0,0,0,0.42)",
    alpha,
  });
  ops.push({
    op: "round",
    x,
    y,
    w: bodyW,
    h: bodyH,
    r: compact ? bodyH / 2 : 6 * s,
    fill: "rgba(9,12,18,0.92)",
    stroke: rgba(accent, 0.55),
    lw: Math.max(1, 1.1 * s),
    grad: {
      from: [x, y],
      to: [x, y + bodyH],
      stops: [
        [0, rgba(accent, 0.22)],
        [0.45, "rgba(9,12,18,0.93)"],
        [1, "rgba(6,8,12,0.97)"],
      ],
    },
  });
  // side stripe
  ops.push({
    op: "round",
    x: x + 2 * s,
    y: y + 3 * s,
    w: 3.2 * s,
    h: bodyH - 6 * s,
    r: 1.6 * s,
    fill: accent,
    alpha: 0.95 * alpha,
  });
  ops.push({
    op: "text",
    x: x + pad + 3 * s,
    y: y + (compact ? 12 : opts.sub ? 12.8 : 12.5) * s,
    text,
    fill: "#eef3fa",
    size: fontMain,
    weight: "700",
    align: "left",
    alpha,
  });
  if (opts.sub && !compact) {
    ops.push({
      op: "text",
      x: x + pad + 3 * s,
      y: y + 23.5 * s,
      text: opts.sub,
      fill: side === "SHORT" ? "#ff9d9d" : side === "LONG" ? "#8ff0bd" : "#a8b4c4",
      size: fontSub,
      weight: "600",
      align: "left",
      alpha: 0.95 * alpha,
      mono: true,
    });
  }
}

/** Small screen-aligned chip (fly scout verdicts, cabin votes). */
export function chip(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  text: string,
  color: string,
  alpha = 1,
  scale = 1,
): void {
  const s = scale * Math.max(0.7, Math.min(1.4, pr.scale / 26));
  const font = Math.round(9.5 * s);
  const w = text.length * font * 0.6 + 12 * s;
  const h = 15 * s;
  ops.push({
    op: "round",
    x: cx - w / 2,
    y: cy - h / 2,
    w,
    h,
    r: h / 2,
    fill: rgba(color, 0.2),
    stroke: rgba(color, 0.8),
    lw: Math.max(1, 1.1 * s),
    alpha,
  });
  ops.push({
    op: "text",
    x: cx,
    y: cy + font * 0.36,
    text,
    fill: tint(color, "#ffffff", 0.55),
    size: font,
    weight: "700",
    align: "center",
    alpha,
  });
}

/** Dust motes / glass sparkle — small, cheap, and it makes the room read as 3D. */
export function motes(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  z: number,
  spread: number,
  count: number,
  seed: number,
  color: string,
  alpha = 0.25,
): void {
  for (let i = 0; i < count; i++) {
    const a = hash01(seed + i * 7) * Math.PI * 2;
    const r = hash01(seed + i * 13) * spread;
    const zz = z + hash01(seed + i * 17) * spread * 0.8;
    const [sx, sy] = pr.p(cx + Math.cos(a) * r, cy + Math.sin(a) * r, zz);
    const size = 0.8 + hash01(seed + i * 23) * 1.4;
    ops.push({
      op: "ellipse",
      cx: sx,
      cy: sy,
      rx: size,
      ry: size,
      fill: color,
      alpha: alpha * (0.4 + hash01(seed + i * 29) * 0.6),
    });
  }
}


/**
 * A speech card: name, role and what the person just said.
 *
 * Used above the cabins, where the requirement is explicit — the LLM has a
 * name and the floor has to show *why* it agreed or disagreed on this specific
 * trade. Same cheap per-character width estimate as the name plate, so the
 * offline rasteriser lays it out identically to the browser.
 */
export function speechCard(
  ops: Op[],
  pr: Projector,
  cx: number,
  cy: number,
  opts: {
    name: string;
    title?: string;
    body: string;
    accent: string;
    tone?: string;
    verdict?: string;
    confidence?: number;
    alpha?: number;
    width?: number;
    lines?: number;
    mono?: boolean;
  },
): number {
  const alpha = opts.alpha ?? 1;
  if (alpha <= 0.02) return 0;
  const s = Math.max(0.55, Math.min(1.35, pr.scale / 24));
  // floors on the type size: a card that is technically inside the frame but
  // set at 6px is not a readout, it is a smudge
  const nameSize = Math.max(12, Math.round(13 * s));
  const titleSize = Math.max(8, Math.round(8.6 * s));
  const bodySize = Math.max(9, Math.round(10.4 * s));
  const maxLines = opts.lines ?? 3;
  const width = opts.width ?? Math.max(190 * s, pr.len(13));
  const padX = 9 * s;
  const bodyChars = Math.max(18, Math.floor((width - padX * 2) / (bodySize * 0.52)));
  const bodyLines = wrapText(opts.body, bodyChars).slice(0, maxLines);
  const headH = 27 * s + (opts.title ? 12 * s : 0) + (opts.verdict ? 16 * s : 0);
  const bodyH = bodyLines.length * (bodySize + 3.4 * s);
  const h = headH + bodyH + 14 * s;
  const x = cx - width / 2;
  const y = cy - h;

  // a card that reads as a card: lighter than the room behind it, with a
  // verdict-coloured spine and enough shadow to lift it off the floor
  contactShadowish(ops, x + 4 * s, y + h + 3 * s, width - 8 * s, 12 * s, alpha);
  ops.push({
    op: "round", x, y, w: width, h, r: 7 * s,
    fill: "#121b28", alpha: 0.95 * alpha,
    stroke: rgba("#8fb2d8", 0.24 * alpha), lw: 1,
  });
  ops.push({
    op: "round", x, y, w: width, h: Math.min(h, 26 * s), r: 7 * s,
    fill: "#18232f", alpha: 0.95 * alpha,
  });
  // accent spine
  ops.push({
    op: "round", x, y: y + 3 * s, w: 3.2 * s, h: h - 6 * s, r: 1.6 * s,
    fill: rgba(opts.accent, 0.95 * alpha),
  });
  // Every line of the header owns its own row. Name and verdict sharing a row
  // meant the verdict ran through the name at small zoom, and there is no font
  // metric here that can promise otherwise.
  const chars = (px: number) => Math.max(8, Math.floor((width - padX * 2) / px));
  const clip = (text: string, size: number) => {
    const room = chars(size * 0.54);
    return text.length > room ? `${text.slice(0, Math.max(4, room - 1))}…` : text;
  };
  ops.push({
    op: "text", x: x + padX, y: y + 16 * s, text: clip(opts.name, nameSize),
    fill: rgba("#f2f7ff", 0.97 * alpha), size: nameSize, weight: "700", align: "left",
  });
  let line = y + 28 * s;
  if (opts.title) {
    ops.push({
      op: "text", x: x + padX, y: line, text: clip(opts.title.toUpperCase(), titleSize),
      fill: rgba("#8fa3bb", 0.92 * alpha), size: titleSize, weight: "600", align: "left",
    });
    line += 12 * s;
  }
  if (opts.verdict) {
    const vt = `${opts.verdict}${opts.confidence !== undefined ? `  ${Math.round(opts.confidence)}%` : ""}`;
    ops.push({
      op: "text", x: x + padX, y: line, text: vt,
      fill: rgba(opts.accent, 0.98 * alpha), size: titleSize + 1.5, weight: "800", align: "left",
    });
  }
  bodyLines.forEach((line, i) => {
    ops.push({
      op: "text", x: x + padX, y: y + headH + 4 * s + i * (bodySize + 3.4 * s),
      text: line, fill: rgba("#cfdcec", 0.95 * alpha), size: bodySize,
      weight: "400", align: "left",
    });
  });
  return h;
}

function wrapText(text: string, chars: number): string[] {
  const words = String(text ?? "").replace(/\s+/g, " ").trim().split(" ");
  const out: string[] = [];
  let line = "";
  for (const w of words) {
    if (!w) continue;
    if ((line + (line ? " " : "") + w).length <= chars) {
      line += (line ? " " : "") + w;
    } else {
      if (line) out.push(line);
      line = w.length > chars ? `${w.slice(0, chars - 1)}…` : w;
    }
  }
  if (line) out.push(line);
  return out;
}

function contactShadowish(ops: Op[], x: number, y: number, w: number, h: number, alpha: number): void {
  ops.push({ op: "ellipse", cx: x + w / 2, cy: y + h / 2, rx: w / 2, ry: h / 2, fill: "#000000", alpha: 0.28 * alpha });
}

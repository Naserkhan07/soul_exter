/**
 * SoulFloor — the machine that turns engine events into a room full of people.
 *
 * It owns three things: the state (who is on the floor and what they are doing),
 * the animation (walks, gaits, door swings, floating numbers), and the drawing
 * order (painter's algorithm from the back of the room to the front).
 *
 * The drawing is emitted as a list of ops rather than being drawn straight to a
 * canvas, so tools/render_floor.py can rasterise the exact same frame offline.
 * That offline path is how this renderer is checked without a browser.
 */
import { Projector, glow, lightPool, namePlate } from "./geom";
import { hash01, palette, rgba } from "./palette";
import {
  CABINS,
  CEO,
  DESK_SLOTS,
  DOORS,
  FLOOR,
  PLATFORM,
  PROMENADE,
  STAIR,
  busyBounds,
  pathFromEntry,
  pathToCabin,
  pathToDoor,
  sceneBounds,
  type DeskSlot,
  type Pt,
} from "./layout";
import {
  WALL_Y,
  drawCabins,
  drawDesk,
  drawFloor,
  drawNearSide,
  drawPlatform,
  drawProps,
  drawReception,
  drawWalls,
} from "./room";
import { drawTrader, facingFor, voteColor } from "./actors";
import type {
  Cabin,
  Grad,
  Destination,
  FloorState,
  Op,
  Side,
  Tick,
  TradeBrief,
  Trader,
  Verdict,
} from "./types";

/** Extra state the renderer keeps per trader beyond the wire types. */
interface RT {
  z: number;
  heading: { dx: number; dy: number };
  speed: number;
  atDesk: boolean;
}

const WALK_SPEED = 3.35; // world units per second — a working floor, not a promenade

export interface CameraFocus {
  mode: "all" | "cabins" | "desks" | "doors";
  zoom?: number;
}

export class SoulFloor {
  canvas: HTMLCanvasElement | null;
  ctx: CanvasRenderingContext2D | null;
  width = 1280;
  height = 720;
  dpr = 1;

  private pr = new Projector(20, 600, 200);
  private zoom = 1;
  private paused = false;
  private time = 0; // ms, advanced by frame()

  cabins: Cabin[] = [];
  traders = new Map<string, Trader>();
  private rt = new Map<string, RT>();
  /** cabins still to be visited, and how long the trader stays inside one */
  private visits = new Map<string, string[]>();
  private dwell = new Map<string, number>();
  private pops: Array<{ x: number; y: number; text: string; born: number; tone: string; scale?: number }> = [];
  /** the scene grew (a card, a person): the camera has to re-fit */
  private needsFit = true;
  private lastFit = -4000;
  private ticks: Tick[] = [];
  private positions = new Map<string, { pnl_pct: number }>();
  private doorActive = { entry: 0, exit: 0 };
  private focus: CameraFocus = { mode: "all" };
  private pickHandler: ((id: string, ev: { x: number; y: number }) => void) | null = null;
  private layerBack: HTMLCanvasElement | null = null;
  private layerFront: HTMLCanvasElement | null = null;
  private layerFor = "";
  private hintPoints: Array<{ id: string; x: number; y: number }> = [];
  /** the scout drone: a little glowing fly that patrols the room */
  private fly = { x: 22, y: 28, z: 4.4, tx: 22, ty: 26, tz: 4.4, wings: 0 };
  /** set by the offline harness so every op is emitted into one flat list */
  capture = false;

  constructor(canvas?: HTMLCanvasElement | null) {
    this.canvas = canvas ?? null;
    this.ctx = canvas ? canvas.getContext("2d") : null;
  }

  // ------------------------------------------------------------------
  // lifecycle
  // ------------------------------------------------------------------
  resize(width: number, height: number, dpr = 1): void {
    this.width = Math.max(320, width);
    this.height = Math.max(240, height);
    this.dpr = dpr;
    if (this.canvas) {
      this.canvas.width = Math.floor(this.width * dpr);
      this.canvas.height = Math.floor(this.height * dpr);
      this.canvas.style.width = `${this.width}px`;
      this.canvas.style.height = `${this.height}px`;
    }
    this.markFit();
    this.fitCamera();
  }

  setZoom(z: number): void {
    this.zoom = Math.max(0.28, Math.min(2.6, z));
    this.markFit();
    this.fitCamera();
  }

  focusOn(focus: CameraFocus): void {
    this.focus = focus;
    if (focus.zoom) this.zoom = focus.zoom;
    this.markFit();
    this.fitCamera();
  }

  /** Remember that the camera has just been framed, restarting the debounce. */
  private markFit(): void {
    this.needsFit = false;
    this.lastFit = this.time;
  }

  /** Re-frame the room on demand (the offline harness and the fit checker). */
  refit(): void {
    this.needsFit = false;
    this.lastFit = this.time;
    this.fitCamera();
  }

  setPaused(p: boolean): void {
    this.paused = p;
  }

  onPick(fn: ((id: string, ev: { x: number; y: number }) => void) | null): void {
    this.pickHandler = fn;
  }

  /** Hit test in CSS pixels. */
  pick(x: number, y: number): string | null {
    let best: string | null = null;
    let bestD = 26 * 26;
    for (const hp of this.hintPoints) {
      const d = (hp.x - x) ** 2 + (hp.y - y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = hp.id;
      }
    }
    if (best && this.pickHandler) this.pickHandler(best, { x, y });
    return best;
  }

  // ------------------------------------------------------------------
  // state in
  // ------------------------------------------------------------------
  setState(state: Partial<FloorState>): void {
    if (state.cabins) {
      // keep the animation flags the live events set, but take the roster
      const byKey = new Map(this.cabins.map((c) => [c.key, c]));
      this.cabins = state.cabins.map((c) => {
        const prev = byKey.get(c.key);
        return {
          ...c,
          thinking: c.thinking ?? prev?.thinking ?? false,
          since: prev?.since ?? 0,
        };
      });
    }
    if (state.ticks) this.ticks = state.ticks;
    this.needsFit = true;
    if (state.paused !== undefined) this.paused = state.paused;
    if (state.positions) {
      for (const p of state.positions) {
        const prev = this.positions.get(p.trade_id);
        this.positions.set(p.trade_id, { pnl_pct: p.pnl_pct ?? prev?.pnl_pct ?? 0 });
        if (prev && p.pnl_pct !== undefined) {
          const delta = (p.pnl_pct ?? 0) - prev.pnl_pct;
          if (Math.abs(delta) > 1.2) {
            const tr = this.traders.get(p.trade_id);
            if (tr) this.pop(tr, `${delta > 0 ? "+" : ""}${delta.toFixed(2)}%`, delta > 0 ? "good" : "bad");
          }
        }
      }
    }
  }

  /** A new trade walked in. */
  spawn(brief: TradeBrief, opts: { announce?: boolean } = {}): void {
    if (this.traders.has(brief.id)) {
      const tr = this.traders.get(brief.id)!;
      if (brief.scout) tr.scout = brief.scout;
      return;
    }
    const deskIndex = brief.desk?.index ?? this.traders.size % DESK_SLOTS.length;
    const desk = DESK_SLOTS[deskIndex % DESK_SLOTS.length];
    const tr: Trader = {
      id: brief.id,
      symbol: brief.symbol,
      side: brief.side,
      strategy: brief.strategy,
      desk: deskIndex,
      state: "walking",
      x: DOORS.entry.x + DOORS.entry.w / 2,
      y: FLOOR.d + 1.2,
      facing: 0,
      path: pathFromEntry(desk),
      legPhase: 0,
      bobPhase: hash01(deskIndex * 13) * 6,
      palette: Math.floor(hash01(deskIndex * 31 + brief.symbol.length) * 8) % 8,
      totalPnl: 0,
      votes: {},
      approvals: 0,
      rejections: 0,
      scout: brief.scout ?? null,
      spawnedAt: this.time,
      pops: [],
    };
    this.traders.set(brief.id, tr);
    this.needsFit = true;
    this.rt.set(brief.id, { z: 0, heading: { dx: 0, dy: -1 }, speed: WALK_SPEED, atDesk: false });
    this.doorActive.entry = 1.4;
    // the scout drone meets the trade at the welcome door, then leads it in
    this.fly.tx = tr.x + 1.2;
    this.fly.ty = tr.y - 0.4;
    this.fly.tz = 3.4;
    if (opts.announce !== false && brief.scout) {
      this.pop(tr, `${brief.scout.verdict} ${(brief.scout.conviction * 100).toFixed(0)}%`,
        brief.scout.verdict === "CONFIRM" ? "good" : "info");
    }
  }

  /** Send a trader somewhere. `target` matches the engine's door/cabin keys. */
  /**
   * Send someone somewhere.
   *
   * The council asks cabins in parallel waves, so three `trader_walks` events
   * can land in the same tick. A trader can only be in one place at a time, so
   * the extra legs are queued: the visitor walks into a cabin, stands there
   * while the desk is talking, then moves on to the next one — which is what
   * the brief asks for (visit every cabin, not just the first).
   */
  moveTo(id: string, target: string): void {
    const tr = this.traders.get(id);
    if (!tr) return;
    if (tr.state === "walking" && tr.path.length > 0) {
      const q = this.visits.get(id) ?? [];
      if (q[q.length - 1] !== target) q.push(target);
      this.visits.set(id, q);
      return;
    }
    this.routeTo(tr, target);
  }

  private routeTo(tr: Trader, target: string): void {
    const id = tr.id;
    const rt = this.rt.get(id);
    if (!rt) return;
    const desk = DESK_SLOTS[tr.desk % DESK_SLOTS.length];
    const from = { x: tr.x, y: tr.y, z: rt.z ?? 0, cabin: tr.cabin };
    let path: Pt[] | null = null;
    if (target === "CEO" || CABINS.some((c) => c.key === target)) {
      path = pathToCabin(desk, target, from);
      tr.destination = { kind: "cabin", cabin: target };
      tr.state = "walking";
      tr.cabin = target;
    } else if (target === "entry_door" || target === "entry") {
      path = pathToDoor(desk, "entry", from);
      tr.destination = { kind: "entry" };
      tr.cabin = undefined;
      tr.state = "walking";
      this.doorActive.entry = 1.2;
    } else if (target === "exit_door" || target === "exit") {
      path = pathToDoor(desk, "exit", from);
      tr.destination = { kind: "exit" };
      tr.cabin = undefined;
      tr.state = "walking";
      this.doorActive.exit = 1.2;
    } else if (target === "desk") {
      path = pathFromEntry(desk).slice().reverse();
      tr.destination = { kind: "desk" };
      tr.state = "walking";
    }
    if (path && path.length) {
      tr.path = path.slice();
      rt.atDesk = false;
      tr.state = "walking";
    }
  }

  cabinThinking(cabin: string): void {
    const c = this.cabins.find((x) => x.key === cabin);
    if (c) {
      c.thinking = true;
      c.lastVote = undefined;
      c.since = this.time;
    }
  }

  cabinVote(cabin: string, verdict: Verdict, confidence?: number, symbol?: string,
            reason?: string): void {
    const c = this.cabins.find((x) => x.key === cabin);
    if (c) {
      c.thinking = false;
      c.lastVote = verdict;
      c.confidence = confidence;
      c.calls = (c.calls ?? 0) + 1;
      if (symbol) c.symbol = symbol;
      if (reason) {
        // the card above the cabin answers "why did this one agree?" — it is
        // the cabin's own words, not a summary we invented here
        c.reason = reason;
        c.said = "";
        this.needsFit = true;
      }
    }
    const slot = cabin === "CEO" ? CEO : CABINS.find((x) => x.key === cabin);
    if (slot) {
      const [sx, sy] = this.pr.p(slot.x + slot.w / 2, slot.y + slot.d / 2, slot.z + 2.2);
      this.pops.push({ x: sx, y: sy, text: `${cabin} ${verdict}`, born: this.time, tone: verdict === "APPROVE" ? "good" : "bad" });
    }
  }

  /** A turn in the debate room. The cabin lights up and holds the floor. */
  cabinSpeak(cabin: string, turn: string, text: string): void {
    const c = this.cabins.find((x) => x.key === cabin);
    if (!c) return;
    c.speakingSince = this.time;
    c.turn = turn;
    const prefix =
      turn === "lesson" ? "RULE" : turn === "challenge" ? "→" : turn === "question" ? "?" : "";
    c.said = `${prefix ? prefix + " " : ""}${text}`.slice(0, 320);
    this.needsFit = true;
    this.pop(c, `${c.name ?? cabin} ${turn === "lesson" ? "sets the rule" : turn + "s"}`,
      turn === "lesson" ? "good" : "info", 1.1);
  }

  endTrade(id: string, decision: string, reason?: string): void {
    const tr = this.traders.get(id);
    if (!tr) return;
    tr.decision = decision === "ENTER" ? "ENTER" : "SKIP";
    this.moveTo(id, tr.decision === "ENTER" ? "entry_door" : "exit_door");
    if (reason) this.pop(tr, reason.slice(0, 22), tr.decision === "ENTER" ? "good" : "bad");
  }

  remove(id: string): void {
    this.visits.delete(id);
    this.dwell.delete(id);
    this.traders.delete(id);
    this.rt.delete(id);
  }

  float(id: string, text: string, tone: "good" | "bad" | "info" = "info"): void {
    const tr = this.traders.get(id);
    if (tr) this.pop(tr, text, tone);
  }

  /** Float a line of text off a trader's head, or off a cabin. */
  private pop(target: Trader | Cabin, text: string, tone: "good" | "bad" | "info",
              scale = 1): void {
    if (!("pops" in target)) {
      const key = (target as Cabin).key;
      const slot = key === "CEO" ? CEO : CABINS.find((c) => c.key === key);
      if (!slot) return;
      const [px, py] = this.pr.p(slot.x + slot.w / 2, slot.y + slot.d / 2, slot.z + 4.9);
      this.pops.push({ x: px, y: py, text, born: this.time, tone, scale });
      return;
    }
    const tr = target;
    tr.pops.push({ text, born: this.time, tone });
    if (tr.pops.length > 2) tr.pops.shift();
  }

  setBoard(ticks: Tick[]): void {
    this.ticks = ticks;
  }

  // ------------------------------------------------------------------
  // animation
  // ------------------------------------------------------------------
  frame(dtMs: number): void {
    // Cards and nameplates grow the scene as the desk works, so the "whole
    // room" view re-fits itself — debounced, because a camera that re-frames on
    // every arriving verdict is unwatchable.
    if (this.needsFit && this.focus.mode === "all" && this.time - this.lastFit > 2500) {
      this.needsFit = false;
      this.lastFit = this.time;
      this.fitCamera();
    }
    const dt = Math.max(0, Math.min(120, dtMs));
    this.time += this.paused ? dt * 0.25 : dt;
    const seconds = (this.paused ? dt * 0.25 : dt) / 1000;

    this.doorActive.entry = Math.max(0, this.doorActive.entry - seconds * 0.7);
    this.doorActive.exit = Math.max(0, this.doorActive.exit - seconds * 0.7);

    for (const tr of this.traders.values()) {
      const rt = this.rt.get(tr.id);
      if (!rt) continue;
      tr.legPhase += seconds * 7.4 * (tr.state === "walking" ? 1 : 0.06);
      tr.bobPhase += seconds * 1.6;
      tr.pops = tr.pops.filter((p) => this.time - p.born < 2400);

      if (tr.state === "walking" && tr.path.length > 0) {
        let remaining = rt.speed * seconds;
        while (remaining > 0 && tr.path.length > 0) {
          const next = tr.path[0];
          const dx = next[0] - tr.x;
          const dy = next[1] - tr.y;
          const dist = Math.hypot(dx, dy);
          if (dist < 1e-4) {
            tr.x = next[0];
            tr.y = next[1];
            if (next[2] !== undefined) rt.z = next[2];
            tr.path.shift();
            continue;
          }
          const step = Math.min(dist, remaining);
          tr.x += (dx / dist) * step;
          tr.y += (dy / dist) * step;
          rt.heading = { dx: dx / dist, dy: dy / dist };
          if (next[2] !== undefined) {
            const t0 = 1 - dist / Math.max(dist, rt.speed);
            rt.z += step * ((next[2] - rt.z) / Math.max(0.15, dist));
            void t0;
          }
          remaining -= step;
          if (step >= dist - 1e-6) {
            tr.x = next[0];
            tr.y = next[1];
            if (next[2] !== undefined) rt.z = next[2];
            tr.path.shift();
          }
        }
        if (tr.path.length === 0) {
          rt.atDesk = tr.destination?.kind === "desk" || !tr.destination;
          // stand inside the cabin while its desk talks, then move on; a desk
          // arrival sits down for a beat before the first cabin calls
          this.dwell.set(tr.id, this.time +
            (tr.destination?.kind === "cabin" ? 1200 : 900));
          tr.state = tr.destination?.kind === "cabin" ? "in_cabin"
            : tr.destination?.kind === "entry" || tr.destination?.kind === "exit" ? "at_door" : "seated";
          if (tr.destination?.kind === "cabin") {
            const key = tr.destination.cabin!;
            const slot = key === "CEO" ? CEO : CABINS.find((c) => c.key === key);
            if (slot) {
              const [px, py] = this.pr.p(slot.x + slot.w / 2, slot.y + slot.d / 2, slot.z + 2.4);
              this.pops.push({ x: px, y: py, text: tr.symbol, born: this.time, tone: "info" });
            }
          }
        }
      } else if ((tr.state === "in_cabin" || tr.state === "seated")
                 && (this.dwell.get(tr.id) ?? 0) <= this.time) {
        // the desk has had its say: on to the next cabin, or out to a door
        const q = this.visits.get(tr.id);
        if (q && q.length) {
          this.routeTo(tr, q.shift()!);
          this.dwell.set(tr.id, this.time + 400);
        }
      } else if (tr.state === "at_door") {
        // walked out: fade, then forget
        const rt2 = this.rt.get(tr.id);
        if (rt2) rt2.speed = Math.max(0.4, rt2.speed - seconds * 2.4);
      }
    }

    // the fly: drift toward its target, wander when idle
    const f = this.fly;
    f.wings += seconds * 42;
    if (Math.abs(f.x - f.tx) < 0.6 && Math.abs(f.y - f.ty) < 0.6) {
      // deterministic wander: the offline renderer must produce the same frame
      // as the browser for the same clock, so nothing here may use Math.random
      const w = Math.floor(this.time / 2600);
      if (hash01(w * 7919) < 0.5) {
        f.tx = 8 + hash01(w * 13 + 1) * 30;
        f.ty = 18 + hash01(w * 17 + 2) * 14;
        f.tz = 3.0 + hash01(w * 19 + 3) * 2.6;
      }
    }
    f.x += (f.tx - f.x) * Math.min(1, seconds * 0.9);
    f.y += (f.ty - f.y) * Math.min(1, seconds * 0.9);
    f.z += (f.tz - f.z) * Math.min(1, seconds * 0.9) + Math.sin(this.time / 400) * 0.004;
  }

  // ------------------------------------------------------------------
  // camera
  // ------------------------------------------------------------------
  /** Screen-space bounding box of a list of ops (gradients ignored: they never
   *  extend past the geometry that carries them). */
  private measure(ops: Op[]): { x0: number; y0: number; x1: number; y1: number } | null {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const acc = (x: number, y: number) => {
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      if (x < x0) x0 = x; if (y < y0) y0 = y;
      if (x > x1) x1 = x; if (y > y1) y1 = y;
    };
    for (const o of ops) {
      if ((o as { bg?: boolean }).bg) continue;
      if (o.op === "poly") {
        for (const q of o.pts) acc(q[0], q[1]);
      } else if (o.op === "ellipse") {
        const rot = Math.abs(Math.cos((o as { rot?: number }).rot ?? 0));
        acc(o.cx - o.rx * (rot + (1 - rot) * 0.6), o.cy - o.ry);
        acc(o.cx + o.rx * (rot + (1 - rot) * 0.6), o.cy + o.ry);
      } else if (o.op === "line") {
        for (const q of o.pts) acc(q[0], q[1]);
      } else if (o.op === "round") {
        acc(o.x, o.y); acc(o.x + o.w, o.y + o.h);
      } else if (o.op === "text") {
        const size = (o as { size?: number }).size ?? 12;
        acc(o.x - size * 4, o.y - size);
        acc(o.x + size * 4, o.y + size);
      } else if (o.op === "clip") {
        acc(o.x, o.y); acc(o.x + o.w, o.y + o.h);
      }
    }
    return Number.isFinite(x0) ? { x0, y0, x1, y1 } : null;
  }

  /** let the projector cull anything that is off-screen */
  private syncViewport(): void {
    this.pr.vw = this.width;
    this.pr.vh = this.height;
  }

  private fitCamera(): void {
    // The fitter measures the true scene box, so culling stays off while the
    // camera is being solved and is switched back on for the paint pass.
    this.pr.vw = 0;
    this.pr.vh = 0;
    // Frame whatever the room actually draws, measured from its own ops, rather
    // than from a hand-maintained bounding box. The hand-maintained box drifted
    // every time a wall, a ceiling beam or a cabin grew, and the scene started
    // bleeding off the top of the canvas.
    const pad = Math.max(12, Math.min(this.width, this.height) * 0.02);
    const focus = new Projector(1, 0, 0);

    // Pass 0: a rough scale, enough to have text and detail laid out sanely.
    const b = sceneBounds();
    const probe: Array<[number, number, number]> = [
      [b.x0, b.y0, 0], [b.x1, b.y0, 0], [b.x0, b.y1, 0], [b.x1, b.y1, 0],
      [b.x0, b.y0, b.zTop], [b.x1, b.y0, b.zTop], [b.x0, b.y1, b.zTop], [b.x1, b.y1, b.zTop],
    ];
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y, z] of probe) {
      const [sx, sy] = focus.p(x, y, z);
      minX = Math.min(minX, sx); maxX = Math.max(maxX, sx);
      minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);
    }
    let scale = Math.min(
      (this.width - pad * 2) / Math.max(1, maxX - minX),
      (this.height - pad * 2) / Math.max(1, maxY - minY),
    ) * this.zoom;

    // Where the camera looks: a preset world point, or the middle of the room.
    let cxWorld = (b.x0 + b.x1) / 2;
    let cyWorld = (b.y0 + b.y1) / 2;
    if (this.focus.mode === "cabins") {
      cyWorld = PLATFORM.y + PLATFORM.d / 2 + 1.5;
      cxWorld = FLOOR.w / 2;
    } else if (this.focus.mode === "doors") {
      cyWorld = FLOOR.d - 7;
      cxWorld = FLOOR.w / 2;
    } else if (this.focus.mode === "desks") {
      cyWorld = 22;
      cxWorld = FLOOR.w / 3;
    }

    // Presets are pans, not fits: the scale comes from the zoom control and the
    // measured box is deliberately allowed to leave the frame. Auto-fitting them
    // cancels the zoom (the fitter sees the whole room and shrinks it back).
    if (this.focus.mode !== "all") {
      const centre = focus.p(cxWorld, cyWorld, 2.2);
      this.pr = new Projector(scale, this.width / 2 - centre[0] * scale,
                              this.height / 2 - centre[1] * scale);
      return;
    }

    // Passes 1-2: measure, correct, repeat. Two passes converge because the only
    // thing scale feeds back into is text size. The correction is clamped
    // relative to the initial estimate, not to an absolute number: Projector's
    // scale is world-units-to-pixels through the isometric basis (about 15 px per
    // unit here), so an absolute cap silently shrinks the whole room.
    const base = scale;
    // "all" means the whole room must be inside the frame, so the measured box is
    // nudged back inside when the projection drifts. The presets are allowed to
    // crop: they exist to push the camera onto one part of the floor.
    const keepInside = this.focus.mode === "all";
    let shiftX = 0;
    let shiftY = 0;
    for (let i = 0; i < 4; i++) {
      const centre = focus.p(cxWorld, cyWorld, 2.2);
      this.pr = new Projector(scale, this.width / 2 - centre[0] * scale + shiftX,
                              this.height / 2 - centre[1] * scale + shiftY);
      const box = this.measure(this.buildFrame());
      if (!box) break;

      const fit = Math.min(
        (this.width - pad * 2) / Math.max(1, box.x1 - box.x0),
        (this.height - pad * 2) / Math.max(1, box.y1 - box.y0),
      );
      let dx = 0;
      let dy = 0;
      if (keepInside) {
        if (box.x0 < pad) dx = pad - box.x0;
        else if (box.x1 > this.width - pad) dx = this.width - pad - box.x1;
        if (box.y0 < pad) dy = pad - box.y0;
        else if (box.y1 > this.height - pad) dy = this.height - pad - box.y1;
      }
      const stepped = scale * Math.min(1.6, Math.max(0.62, fit));
      const next = Math.max(base * 0.2, Math.min(base * 5, stepped));
      const done = Math.abs(next / scale - 1) < 0.01 && dx === 0 && dy === 0;
      scale = next;
      shiftX += dx;
      shiftY += dy;
      if (done) break;
    }

  }

  // ------------------------------------------------------------------
  // drawing
  // ------------------------------------------------------------------
  buildFrame(): Op[] {
    const ops: Op[] = [];
    const pr = this.pr;
    const t = this.time;

    // backdrop: a dark hall with a soft light at the top. Tagged as background
    // so the camera auto-fit never measures the canvas frame itself.
    ops.push({
      op: "round",
      x: 0, y: 0, w: this.width, h: this.height, r: 0, bg: true,
      grad: {
        from: [this.width * 0.5, 0],
        to: [this.width * 0.5, this.height],
        stops: [
          [0, "#0a1018"],
          [0.45, "#070a10"],
          [1, "#04060a"],
        ],
      },
      fill: palette.void,
    });

    drawFloor(ops, pr, t);
    drawWalls(ops, pr, this.ticks, "council", t);
    drawPlatform(ops, pr, t);

    // who is deliberating in which cabin
    const active: Partial<Record<string, string>> = {};
    for (const c of this.cabins) {
      if (c.thinking && c.key) active[c.key] = c.symbol ?? "";
    }
    // whoever is standing inside a cabin right now, so they are drawn behind
    // the cabin glass instead of floating on top of it
    const occupants: Partial<Record<string, Trader>> = {};
    for (const tr of this.traders.values()) {
      if (tr.state === "in_cabin" && tr.cabin) occupants[tr.cabin] = tr;
    }
    drawCabins(ops, pr, this.cabins, t, active, occupants);

    // ---- desks, row by row, with the people at them ----------------------
    let deskIdx = 0;
    const rows = new Map<number, DeskSlot[]>();
    for (const d of DESK_SLOTS) {
      const arr = rows.get(d.row) ?? [];
      arr.push(d);
      rows.set(d.row, arr);
    }
    const tradersByDesk = new Map<number, Trader[]>();
    for (const tr of this.traders.values()) {
      const arr = tradersByDesk.get(tr.desk) ?? [];
      arr.push(tr);
      tradersByDesk.set(tr.desk, arr);
    }
    const sortedRows = [...rows.keys()].sort((a, b) => a - b);
    const drawn = new Set<string>();
    for (const row of sortedRows) {
      for (const d of rows.get(row)!) {
        const seatTraders = tradersByDesk.get(d.index) ?? [];
        const seated = seatTraders.filter((tr) => tr.state === "seated" || (tr.state === "walking" && tr.path.length < 2));
        target:
        for (const tr of seatTraders) {
          if (tr.state === "seated" && Math.abs(tr.x - d.seat[0]) < 0.2 && Math.abs(tr.y - d.seat[1]) < 0.2) {
            continue;
          }
          void seated;
          break target;
        }
        if (!pr.visible(d.x + 1.6, d.y + 1.0, 0, 300)) continue;
        drawDesk(ops, pr, d, t, seatTraders.length > 0);
        for (const tr of seatTraders) {
          if (tr.state === "seated") {
            this.drawOne(ops, tr, true);
            drawn.add(tr.id);
          }
        }
        deskIdx++;
      }
    }
    void deskIdx;

    drawProps(ops, pr, t);
    drawReception(ops, pr, t);
    drawNearSide(ops, pr, t, this.doorActive);

    // ---- everyone who is not sitting down --------------------------------
    const movers = [...this.traders.values()]
      .filter((tr) => !drawn.has(tr.id) && tr.state !== "in_cabin");
    movers.sort((a, b) => (a.y + a.x * 0.5) - (b.y + b.x * 0.5));
    for (const tr of movers) {
      if (pr.visible(tr.x, tr.y, 0, 240)) this.drawOne(ops, tr, false);
    }

    // ---- the scout drone --------------------------------------------------
    this.drawFly(ops);

    // ---- floating numbers -------------------------------------------------
    for (const tr of this.traders.values()) {
      const rt = this.rt.get(tr.id) ?? { z: 0 };
      const [hx, hy] = pr.p(tr.x, tr.y, (rt.z ?? 0) + 2.35);
      for (const p of tr.pops) {
        const age = (this.time - p.born) / 2400;
        const alpha = Math.max(0, 1 - age * age);
        ops.push({
          op: "text",
          x: hx,
          y: hy - age * 34,
          text: p.text,
          fill: p.tone === "good" ? palette.longColor : p.tone === "bad" ? palette.shortColor : "#cfe0f5",
          size: Math.max(9, pr.len(0.3)) * 1.05,
          weight: "800",
          align: "center",
          alpha,
        });
      }
    }

    // ---- vignette ---------------------------------------------------------
    // Four edge bands with linear falloff. A single big ellipse leaves a
    // visible circular rim inside the corners, which looks like a mistake.
    const band = Math.max(90, Math.min(this.width, this.height) * 0.2);
    const vig = (x: number, y: number, w: number, h: number, from: [number, number], to: [number, number]) =>
      ops.push({
        op: "round", x, y, w, h, r: 0,
        bg: true,                       // never counted by the camera auto-fit
        grad: {
          from, to,
          stops: [
            [0, "rgba(0,0,0,0.46)"],
            [0.55, "rgba(0,0,0,0.13)"],
            [1, "rgba(0,0,0,0)"],
          ],
        },
      });
    vig(0, 0, band, this.height, [0, 0], [band, 0]);
    vig(this.width - band, 0, band, this.height, [this.width, 0], [this.width - band, 0]);
    vig(0, 0, this.width, band, [0, 0], [0, band]);
    vig(0, this.height - band, this.width, band, [0, this.height], [0, this.height - band]);
    return ops;
  }

  private drawOne(ops: Op[], tr: Trader, seated: boolean): void {
    const rt = this.rt.get(tr.id) ?? { z: 0, heading: { dx: 0, dy: 1 } };
    (tr as Trader & { z?: number }).z = rt.z ?? 0;
    (tr as Trader & { heading?: { dx: number; dy: number } }).heading = rt.heading;
    const walking = tr.state === "walking";
    const pos = this.positions.get(tr.id);
    const pnl = pos?.pnl_pct;
    const sub = pnl !== undefined
      ? `${tr.side === "LONG" ? "LONG" : "SHORT"}  ${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%`
      : `${tr.side}  ${(tr.strategy ?? "").replace(/_/g, " ").toLowerCase()}`;
    const accent = tr.side === "SHORT" ? palette.shortColor : palette.longColor;
    // fade people out as they leave through a door
    let alpha = 1;
    if (tr.state === "at_door") {
      const desk = DESK_SLOTS[tr.desk % DESK_SLOTS.length];
      void desk;
      alpha = 0.35;
    }
    drawTrader(ops, this.pr, tr, this.time, {
      seated,
      gait: walking ? tr.legPhase : 0,
      side: tr.side,
      label: tr.symbol.replace("/USDT", ""),
      sublabel: sub,
      accent,
      alpha,
      // at neighbourhood zoom the plate is the asset and a side stripe; pulling
      // in closer adds the strategy/P&L line. Dense floors are unreadable with
      // two-line plates on every head.
      compactPlate: this.pr.scale < 19,
      badge: tr.scout && this.pr.scale > 18
        ? {
            text: `FLY ${tr.scout.verdict} ${(tr.scout.conviction * 100).toFixed(0)}%`,
            color: tr.scout.verdict === "CONFIRM" ? "#7fd6ff" : palette.abstainColor,
          }
        : undefined,
    });
    const rt2 = this.rt.get(tr.id);
    if (rt2) rt2.atDesk = seated;
  }

  private drawFly(ops: Op[]): void {
    const pr = this.pr;
    const f = this.fly;
    const [x, y] = pr.p(f.x, f.y, f.z);
    const s = Math.max(0.5, pr.len(0.16));
    const flap = Math.abs(Math.sin(f.wings));
    glow(ops, pr, f.x, f.y, 0.5, "#8fe3ff", 0.22);
    ops.push({ op: "ellipse", cx: x, cy: y, rx: s * 1.5, ry: s * 0.9, fill: "#0d1a24", alpha: 0.9 });
    // wings
    ops.push({
      op: "ellipse", cx: x - s * 1.4, cy: y - s * 0.6 * flap, rx: s * 1.5, ry: s * 0.5,
      fill: rgba("#bfe9ff", 0.5), alpha: 0.75,
    });
    ops.push({
      op: "ellipse", cx: x + s * 1.4, cy: y - s * 0.6 * flap, rx: s * 1.5, ry: s * 0.5,
      fill: rgba("#bfe9ff", 0.5), alpha: 0.75,
    });
    // body + eye glow
    ops.push({ op: "ellipse", cx: x, cy: y, rx: s * 0.7, ry: s * 0.5, fill: "#12212c" });
    ops.push({ op: "ellipse", cx: x + s * 0.5, cy: y - s * 0.1, rx: s * 0.22, ry: s * 0.22, fill: "#9ff0ff", alpha: 0.95 });
    // scan beam under it
    ops.push({
      op: "poly",
      pts: [[x - s * 0.8, y + s * 0.4], [x + s * 0.8, y + s * 0.4], [x + s * 2.4, y + s * 5.2], [x - s * 2.4, y + s * 5.2]],
      grad: {
        from: [x, y + s * 0.4],
        to: [x, y + s * 5.2],
        stops: [
          [0, rgba("#8fe3ff", 0.16)],
          [1, rgba("#8fe3ff", 0)],
        ],
      },
    });
    ops.push({
      op: "text", x, y: y - s * 2.4, text: "SCOUT", fill: rgba("#9ff0ff", 0.85),
      size: Math.max(7, pr.len(0.2)), weight: "700", align: "center",
    });
  }

  /** Rasterise an op list. Shared with the offline rasteriser's contract. */
  draw(): void {
    this.syncViewport();               // paint passes cull what is off-screen
    const ops = this.buildFrame();
    const ctx = this.ctx;
    if (!ctx) return;

    // The backdrop and the vignette only depend on the canvas size and are by
    // far the most expensive thing to fill (two full-screen gradients at the
    // device pixel ratio, four edge bands). Bake them once per size and blit.
    const isBg = (o: Op) => !!(o as { bg?: boolean }).bg;
    const bg = ops.filter(isBg);
    const rest = ops.filter((o) => !isBg(o));
    if (!bg.length) {
      paint(ctx, rest, this.dpr);
      return;
    }
    const key = `${this.width}x${this.height}@${this.dpr}`;
    if (!this.layerBack || this.layerFor !== key) {
      this.layerFor = key;
      this.layerBack = this.bake(key, bg.slice(0, 1));       // hall
      this.layerFront = this.bake(key, bg.slice(1));         // vignette, on top
    }
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    if (this.layerBack) ctx.drawImage(this.layerBack, 0, 0);
    ctx.restore();
    paint(ctx, rest, this.dpr, false);   // canvas already carries the backdrop
    if (this.layerFront) {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(this.layerFront, 0, 0);
      ctx.restore();
    }
  }

  /** Render a background layer into an offscreen canvas of the same size. */
  private bake(key: string, ops: Op[]): HTMLCanvasElement | null {
    if (!ops.length || typeof document === "undefined") return null;
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.floor(this.width * this.dpr));
    c.height = Math.max(1, Math.floor(this.height * this.dpr));
    const cx = c.getContext("2d");
    if (!cx) return null;
    paint(cx, ops, this.dpr);
    void key;
    return c;
  }

  /**
   * The op list exactly as a paint pass would build it (off-screen culling on).
   * The offline harness uses this so it renders the scene that actually ships.
   */
  paintOps(): Op[] {
    this.syncViewport();
    const ops = this.buildFrame();
    this.pr.vw = 0;                    // never leave culling on for the fitter
    this.pr.vh = 0;
    return ops;
  }

  /** True when nothing on the floor is animating — the host may paint less often. */
  get idle(): boolean {
    if (this.paused) return false;
    for (const tr of this.traders.values()) {
      if (tr.state === "walking" || tr.pops.length) return false;
    }
    for (const c of this.cabins) {
      if (c.thinking) return false;
    }
    return true;
  }

  get camera(): Projector {
    return this.pr;
  }

  get clock(): number {
    return this.time;
  }
}

// ---------------------------------------------------------------------------
// painter
// ---------------------------------------------------------------------------
function gradFor(ctx: CanvasRenderingContext2D, g: Grad): CanvasGradient {
  let grad: CanvasGradient;
  if (g.radial) {
    const [cx, cy] = g.from;
    const r = Math.hypot(g.to[0] - cx, g.to[1] - cy) || 1;
    grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
  } else {
    grad = ctx.createLinearGradient(g.from[0], g.from[1], g.to[0], g.to[1]);
  }
  for (const [stop, color] of g.stops) grad.addColorStop(Math.max(0, Math.min(1, stop)), color);
  return grad;
}

/** Draw a list of ops onto a 2D context. */
export function paint(ctx: CanvasRenderingContext2D, ops: Op[], dpr = 1, clear = true): void {
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // `clear` is false when the caller has already set the canvas up (the baked
  // backdrop is blitted first, and clearing after that would erase it).
  if (clear) ctx.clearRect(0, 0, ctx.canvas.width / dpr, ctx.canvas.height / dpr);
  let clipDepth = 0;
  for (const op of ops) {
    const prevAlpha = ctx.globalAlpha;
    const opAlpha = (op as { alpha?: number }).alpha;
    if (opAlpha !== undefined) ctx.globalAlpha = Math.max(0, Math.min(1, opAlpha)) * prevAlpha;
    switch (op.op) {
      case "poly": {
        ctx.beginPath();
        op.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.closePath();
        const style = op.grad ? gradFor(ctx, op.grad) : op.fill;
        if (style) {
          ctx.fillStyle = style;
          ctx.fill();
        }
        if (op.stroke && op.lw) {
          ctx.strokeStyle = op.stroke;
          ctx.lineWidth = op.lw;
          ctx.stroke();
        }
        break;
      }
      case "ellipse": {
        ctx.beginPath();
        ctx.ellipse(op.cx, op.cy, Math.max(0.1, op.rx), Math.max(0.1, op.ry), 0, 0, Math.PI * 2);
        const style = op.grad ? gradFor(ctx, op.grad) : op.fill;
        if (style) {
          ctx.fillStyle = style;
          ctx.fill();
        }
        if (op.stroke && op.lw) {
          ctx.strokeStyle = op.stroke;
          ctx.lineWidth = op.lw;
          ctx.stroke();
        }
        break;
      }
      case "line": {
        ctx.beginPath();
        op.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.strokeStyle = op.stroke;
        ctx.lineWidth = op.lw ?? 1;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.stroke();
        break;
      }
      case "round": {
        roundedPath(ctx, op.x, op.y, op.w, op.h, op.r);
        const style = op.grad ? gradFor(ctx, op.grad) : op.fill;
        if (style) {
          ctx.fillStyle = style;
          ctx.fill();
        }
        if (op.stroke && op.lw) {
          ctx.strokeStyle = op.stroke;
          ctx.lineWidth = op.lw;
          ctx.stroke();
        }
        break;
      }
      case "text": {
        const family = op.mono
          ? '"SF Mono", ui-monospace, Menlo, Consolas, monospace'
          : '"Inter", "Segoe UI", system-ui, -apple-system, sans-serif';
        ctx.font = `${op.weight ?? "400"} ${op.size}px ${family}`;
        ctx.fillStyle = op.fill;
        ctx.textAlign = op.align ?? "left";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(op.text, op.x, op.y);
        break;
      }
      case "clip": {
        ctx.save();
        ctx.beginPath();
        ctx.rect(op.x, op.y, op.w, op.h);
        ctx.clip();
        clipDepth++;
        break;
      }
      case "restore": {
        if (clipDepth > 0) {
          ctx.restore();
          clipDepth--;
        }
        break;
      }
    }
    ctx.globalAlpha = prevAlpha;
  }
  ctx.restore();
}

function roundedPath(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  const rr = Math.max(0, Math.min(r, Math.min(w, h) / 2));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

/** Convenience for the React layer: a scene of one trade arriving at the door. */
export function demoBrief(i: number): TradeBrief {
  const symbols = ["SOL/USDT", "XRP/USDT", "ADA/USDT", "INJ/USDT", "TIA/USDT", "ARB/USDT", "TON/USDT", "SUI/USDT"];
  return {
    id: `DEMO-${i}`,
    symbol: symbols[i % symbols.length],
    side: i % 2 ? "SHORT" : "LONG",
    strategy: i % 3 === 0 ? "VOLATILITY_SQUEEZE" : "MOMENTUM_BREAKOUT",
    score: 0.4 + ((i * 7) % 5) / 10,
    desk: { index: i % 24, row: Math.floor((i % 24) / 10), col: i % 10 },
    scout: { verdict: i % 5 === 3 ? "WAIT" : "CONFIRM", conviction: 0.4 + ((i * 3) % 5) / 10, salience: 0.5, z_margin: 1.8 },
  };
}

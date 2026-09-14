/**
 * Types for the trading floor.
 *
 * These deliberately mirror the event payloads the FastAPI engine publishes
 * (see soul/api.py and soul/engine.py) so the renderer can be driven either by
 * the live WebSocket or by a synthetic scene in the offline smoke test.
 */

export type Side = "LONG" | "SHORT";

/** A world-space waypoint; the third element is the height for stairs. */
export type PathPoint = [number, number, number?];
export type Verdict = "APPROVE" | "REJECT" | "ABSTAIN";
export type Decision = "ENTER" | "SKIP" | "PENDING";
export type FlyVerdict = "CONFIRM" | "CONTRADICT" | "WAIT";

/** Where a trader is in its little life. */
export type TraderState =
  | "seated"
  | "walking"
  | "in_cabin"
  | "at_door"
  | "gone";

/** A destination the walk planner understands. */
export type Destination =
  | { kind: "desk" }
  | { kind: "cabin"; cabin: string }
  | { kind: "entry" }
  | { kind: "exit" };

export interface TradeBrief {
  id: string;
  symbol: string;
  side: Side;
  strategy?: string;
  entry?: number;
  stop?: number;
  target?: number;
  rr?: number;
  score?: number;
  desk?: { index?: number; row?: number; col?: number } | null;
  /** the fly scout's read, when the candidate came through it */
  scout?: { verdict: FlyVerdict; conviction: number; salience: number; z_margin?: number } | null;
}

export interface Trader {
  id: string;
  symbol: string;
  side: Side;
  strategy?: string;
  desk: number;
  state: TraderState;
  /** current position in floor space (x, y) and facing (radians in screen space) */
  x: number;
  y: number;
  facing: number;
  /** remaining path in world coordinates */
  path: PathPoint[];
  legPhase: number;
  bobPhase: number;
  palette: number;
  totalPnl: number;
  votes: Partial<Record<string, Verdict>>;
  approvals: number;
  rejections: number;
  cabin?: string;
  destination?: Destination;
  decision?: Decision;
  scout?: TradeBrief["scout"];
  spawnedAt: number;
  /** floats rising off this trader's head (P&L pops) */
  pops: Array<{ text: string; born: number; tone: "good" | "bad" | "info" }>;
}

export interface Cabin {
  key: string;
  label: string;
  /** the person at the desk: LLMs have names, titles and a house style */
  name?: string;
  title?: string;
  expertise?: string[];
  /** why they voted the way they did on the trade in front of them */
  reason?: string;
  /** what they are saying in the debate room right now */
  said?: string;
  turn?: string;
  speakingSince?: number;
  model?: string;
  role?: string;
  isCeo?: boolean;
  thinking: boolean;
  since: number;
  lastVote?: Verdict;
  confidence?: number;
  calls: number;
  latency?: number;
  symbol?: string;
  approvals?: number;
  rejections?: number;
}

export interface PositionView {
  trade_id: string;
  symbol: string;
  side: Side;
  entry: number;
  price?: number;
  stop: number;
  target: number;
  qty?: number;
  pnl?: number;
  pnl_pct?: number;
  dollar_risk?: number;
}

export interface Tick {
  symbol: string;
  price: number;
  change_pct: number;
}

export interface FloorState {
  cabins: Cabin[];
  traders: Trader[];
  positions: PositionView[];
  ticks: Tick[];
  equity: number;
  startedEquity: number;
  paused: boolean;
  llmMode: string;
}

/** One drawing op. Both the browser canvas and the Python rasteriser consume
 *  these, which is what lets the offline tool render exactly what ships. */
export type Op =
  | {
      op: "poly";
      pts: Array<[number, number]>;
      fill?: string;
      alpha?: number;
      grad?: Grad;
      stroke?: string;
      lw?: number;
    }
  | {
      op: "ellipse";
      cx: number;
      cy: number;
      rx: number;
      ry: number;
      fill?: string;
      alpha?: number;
      grad?: Grad;
      stroke?: string;
      lw?: number;
    }
  | { op: "line"; pts: Array<[number, number]>; stroke: string; lw?: number; alpha?: number }
  | {
      op: "round";
      /** background furniture (backdrop, vignette): never measured by the camera fit */
      bg?: boolean;
      x: number;
      y: number;
      w: number;
      h: number;
      r: number;
      fill?: string;
      alpha?: number;
      grad?: Grad;
      stroke?: string;
      lw?: number;
    }
  | {
      op: "text";
      x: number;
      y: number;
      text: string;
      fill: string;
      size: number;
      alpha?: number;
      weight?: string;
      align?: "left" | "center" | "right";
      mono?: boolean;
    }
  | { op: "clip"; x: number; y: number; w: number; h: number }
  | { op: "restore" };

export interface Grad {
  from: [number, number];
  to: [number, number];
  stops: Array<[number, string]>;
  radial?: boolean;
}

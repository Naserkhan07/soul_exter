/**
 * The connection to the engine.
 *
 * One hook owns everything the UI needs: a full state snapshot, a rolling event
 * log, and the live decisions. It prefers the WebSocket (which is what a real
 * session uses), falls back to Server-Sent Events, and finally to plain polling,
 * so the dashboard still works behind a proxy that blocks upgrades — which is
 * exactly what happens on a Kaggle tunnel.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Cabin, PositionView, Tick, Trader } from "../floor/types";

export interface RegistryEntry {
  key: string;
  label: string;
  model: string;
  role: string;
  is_ceo: boolean;
  kind?: string;
  params?: string;
}

export interface VerdictRow {
  cabin: string;
  verdict: "APPROVE" | "REJECT" | "ABSTAIN";
  confidence: number;
  reason: string;
  model?: string;
  latency_ms?: number;
  stage?: number;
  risk_flags?: string[];
}

export interface TradeRow {
  id: string;
  trade_id?: string;
  symbol: string;
  side: "LONG" | "SHORT";
  strategy?: string;
  entry?: number;
  stop?: number;
  target?: number;
  rr?: number;
  score?: number;
  approvals?: number;
  rejections?: number;
  route?: string;
  decision?: string;
  confidence?: number;
  duration_s?: number;
  ts?: number;
  verdicts?: VerdictRow[];
  ceo?: VerdictRow | null;
  opened?: boolean;
  blocked?: string | null;
  desk?: { index?: number; row?: number; col?: number } | null;
  scout?: ScoutRead | null;
  pnl_pct?: number;
}

export interface ScoutRead {
  trade_id?: string;
  symbol: string;
  side: "LONG" | "SHORT";
  strategy?: string;
  verdict: "CONFIRM" | "CONTRADICT" | "WAIT";
  conviction: number;
  salience: number;
  z_margin?: number;
  z_confirm?: number;
  z_contradict?: number;
  kc_sparsity?: number;
  score?: number;
  rank?: number;
  admitted?: boolean;
  ts?: number;
}

export interface ScoutStats {
  enabled: boolean;
  engine?: string;
  neurons?: Record<string, number>;
  synapses?: number;
  judged: number;
  confirmed: number;
  waited: number;
  contradicted: number;
  admitted: number;
  admit_rate: number;
  min_z: number;
  top_n: number;
  rewards: number;
  mean_reward: number;
  plasticity_events: number;
  calibration?: Record<string, unknown>;
  last_batch?: ScoutRead[];
}


// ---------------------------------------------------------------------------
// wire shapes -> UI shapes
//
// The engine's payload is written for the cabins, not for the screen: a council
// record nests its trade, a closed position carries dollars but no percentage,
// and the desk's realised P&L is `realised_pnl`. Everything the components need
// is derived here, once, so no component has to know about both spellings.
// ---------------------------------------------------------------------------
function pnlPct(row: any): number {
  const size = Number(row?.size ?? 0);
  const pnl = Number(row?.pnl ?? 0);
  if (size > 0) return (pnl / size) * 100;
  const qty = Number(row?.qty ?? 0);
  const entry = Number(row?.entry ?? 0);
  if (qty > 0 && entry > 0) return ((pnl / (qty * entry)) * 100);
  return 0;
}

function winRate(closed: any): number | undefined {
  if (!Array.isArray(closed) || !closed.length) return undefined;
  const wins = closed.filter((c) => Number(c?.pnl ?? 0) > 0).length;
  return Math.round((wins / closed.length) * 100);
}

function markOf(row: any): number {
  const qty = Number(row?.qty ?? 0);
  if (qty > 0) {
    const dir = String(row?.side ?? "LONG") === "LONG" ? 1 : -1;
    return Number(row?.entry ?? 0) + (Number(row?.pnl ?? 0) / qty) * dir;
  }
  return Number(row?.exit_price ?? row?.entry ?? 0);
}

function positionView(row: any): PositionView {
  return {
    ...row,
    trade_id: row?.trade_id ?? row?.id ?? "",
    price: row?.price ?? markOf(row),
    pnl_pct: row?.pnl_pct ?? pnlPct(row),
  };
}

/** recent_councils entries nest their trade: {trade, verdicts, ceo, route, ...} */
function councilRow(entry: any): TradeRow {
  const t = entry?.trade ?? entry;
  return {
    id: t?.id ?? entry?.id ?? "",
    trade_id: t?.id ?? entry?.id ?? "",
    symbol: t?.symbol ?? "—",
    side: t?.side ?? "LONG",
    strategy: t?.strategy,
    entry: t?.entry, stop: t?.stop, target: t?.target,
    rr: t?.rr, score: t?.score ?? entry?.score,
    desk: t?.desk ?? null,
    approvals: entry?.approvals ?? 0,
    rejections: entry?.rejections ?? 0,
    route: entry?.route ?? "PENDING",
    decision: entry?.decision ?? "PENDING",
    confidence: entry?.confidence,
    duration_s: entry?.duration_s,
    ts: t?.created_at ?? entry?.ts,
    verdicts: entry?.verdicts ?? [],
    ceo: entry?.ceo ?? null,
    scout: entry?.scout ?? null,
    opened: entry?.opened,
    blocked: entry?.blocked,
  };
}

export interface SoulState {
  connected: boolean;
  transport: "ws" | "sse" | "poll" | "none";
  engine: Record<string, any>;
  council: Record<string, any>;
  desk: Record<string, any>;
  market: Record<string, any>;
  cabins: Cabin[];
  ceo?: Cabin | null;
  positions: PositionView[];
  closed: PositionView[];
  traders: Trader[];
  tradeLog: TradeRow[];
  recentCouncils: TradeRow[];
  equityCurve: Array<{ t: number; equity: number; realised: number }>;
  ticks: Tick[];
  scout?: ScoutStats;
  registry: RegistryEntry[];
  debate: DebateSnapshot;
  instruments: InstrumentState;
}

/** One turn of the debate room, exactly as the engine publishes it. */
export interface DebateTurn {
  room: string;
  topic: string;
  speaker: string;
  name: string;
  label: string;
  model: string;
  turn: string;
  text: string;
  round: number;
  trade_id?: string | null;
  /** who this turn was addressed to — the room is a conversation, not a log */
  to?: string;
  to_name?: string;
  ts: number;
}

export interface DebateSnapshot {
  room?: string;
  rounds?: number;
  topic?: string | null;
  transcript?: DebateTurn[];
  lessons?: Array<{ topic: string; speaker: string; speaker_label: string; text: string; ts: number; round: number }>;
  speakers?: Array<{ key: string; name: string; title: string }>;
  queued?: number;
  enabled?: boolean;
}

export interface InstrumentState {
  selected?: string[];
  count?: number;
  classes?: string[];
}

const EMPTY: SoulState = {
  connected: false,
  transport: "none",
  engine: {},
  council: {},
  desk: {},
  market: {},
  cabins: [],
  ceo: null,
  positions: [],
  closed: [],
  traders: [],
  tradeLog: [],
  recentCouncils: [],
  equityCurve: [],
  ticks: [],
  registry: [],
  debate: { transcript: [], lessons: [] },
  instruments: { selected: [] },
};

/** A new trade seen on the wire, ready for the renderer. */
export interface SpawnEvent {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  strategy?: string;
  desk?: { index?: number; row?: number; col?: number } | null;
  scout?: { verdict: "CONFIRM" | "CONTRADICT" | "WAIT"; conviction: number; salience: number; z_margin?: number } | null;
}

export interface SoulEvents {
  spawns: SpawnEvent[];
  moves: Array<{ id: string; target: string }>;
  cabinThinking: Array<{ cabin: string }>;
  cabinVerdicts: Array<{
    cabin: string; verdict: "APPROVE" | "REJECT" | "ABSTAIN"; confidence: number;
    symbol?: string; reason?: string;
  }>;

  ends: Array<{ id: string; decision: string; reason?: string }>;
  floats: Array<{ id: string; text: string; tone: "good" | "bad" | "info" }>;
  /** turns as they are spoken, for the live debate panel and the cabins */
  debate: Array<{ cabin: string; name: string; turn: string; text: string; topic: string;
                  to?: string; to_name?: string }>;
}

export function useSoul(pollMs = 4000): {
  state: SoulState;
  events: SoulEvents;
  /** bumps on every event, so components can drain the buffers in an effect */
  seq: number;
  refresh: () => void;
  send: (path: string, body?: unknown) => Promise<void>;
} {
  const [state, setState] = useState<SoulState>(EMPTY);
  const eventsRef = useRef<SoulEvents>({
    spawns: [], moves: [], cabinThinking: [], cabinVerdicts: [], ends: [], floats: [], debate: [],
  });
  const [seq, setSeq] = useState(0);
  const firstState = useRef(true);
  const seenTrades = useRef(new Set<string>());
  const transportRef = useRef<SoulState["transport"]>("none");

  const push = useCallback(<K extends keyof SoulEvents>(kind: K, value: SoulEvents[K][number]) => {
    const bag = eventsRef.current[kind];
    bag.push(value as never);
    if (bag.length > 64) bag.shift();
    setSeq((n) => n + 1);
  }, []);

  const adopt = useCallback((raw: any, source: SoulState["transport"]) => {
    if (!raw || typeof raw !== "object") return;
    const next: SoulState = {
      ...EMPTY,
      connected: true,
      transport: source,
      engine: raw.engine ?? {},
      council: raw.council ?? {},
      desk: {
        ...(raw.desk ?? {}),
        // the API spells these differently to the way the panels read them
        realised: raw.desk?.realised ?? raw.desk?.realised_pnl ?? 0,
        win_rate: raw.desk?.win_rate ?? winRate(raw.closed),
      },
      market: raw.market ?? {},
      cabins: raw.cabins ?? [],
      ceo: raw.ceo ?? null,
      positions: (raw.positions ?? []).map(positionView),
      closed: (raw.closed ?? []).map(positionView),
      tradeLog: (raw.trade_log ?? []).map((r: any) => ({ ...r, id: r.trade_id ?? r.id ?? "" })),
      recentCouncils: (raw.recent_councils ?? []).map(councilRow),
      equityCurve: raw.equity_curve ?? [],
      ticks: (raw.market?.board ?? []).map((b: any) => ({
        symbol: b.symbol, price: b.price, change_pct: b.change_pct ?? 0,
      })),
      scout: raw.scout,
      registry: raw.registry ? Object.values(raw.registry) as RegistryEntry[] : [],
      debate: (raw.debate ?? { transcript: [], lessons: [], speakers: [] }) as DebateSnapshot,
      instruments: (raw.instruments ?? { selected: [] }) as SoulState["instruments"],
      traders: [],
    };
    setState(next);
    transportRef.current = source;

    // On the first snapshot, walk in every trade that is still live so a
    // refresh does not leave an empty floor.
    if (firstState.current) {
      firstState.current = false;
      for (const row of [...next.recentCouncils].reverse()) {
        if (row.id && row.decision === "PENDING" && !seenTrades.current.has(row.id)) {
          seenTrades.current.add(row.id);
          push("spawns", { id: row.id, symbol: row.symbol, side: row.side,
                           strategy: row.strategy, desk: row.desk });
        }
      }
    }
  }, [push]);

  const handleEvent = useCallback((ev: any) => {
    const kind: string = ev?.type ?? ev?.kind ?? "";
    const p = ev?.payload ?? ev;
    switch (kind) {
      case "trader_spawned": {
        // payload is {trade: <brief>, source, session_reviews}
        const t = p?.trade ?? p;
        if (t?.id && !seenTrades.current.has(t.id)) {
          seenTrades.current.add(t.id);
          push("spawns", {
            id: t.id, symbol: t.symbol, side: t.side, strategy: t.strategy,
            desk: t.desk ?? null, scout: t.scout ?? p?.scout ?? null,
          });
        }
        break;
      }
      case "trader_walks":
        if (p?.trade_id) push("moves", { id: p.trade_id, target: String(p.to ?? "desk") });
        break;
      case "cabin_verdict": {
        if (p?.cabin) {
          // a walk event lands first; by the time a verdict arrives the cabin
          // has been thinking, so the card flips straight to the answer
          push("cabinVerdicts", {
            cabin: p.cabin, verdict: p.verdict ?? "ABSTAIN",
            confidence: p.confidence ?? 0, symbol: p.symbol,
            reason: p.reason ?? p.why ?? "",
          });
        }
        break;
      }
      case "entry_door":
      case "exit_door":
        if (p?.trade_id) {
          push("ends", {
            id: p.trade_id,
            decision: kind === "entry_door" ? "ENTER" : "SKIP",
            reason: p.reason,
          });
          seenTrades.current.delete(p.trade_id);
        }
        break;
      case "position_closed":
        if (p?.trade_id) {
          push("floats", {
            id: p.trade_id,
            text: `${(p.pnl_pct ?? 0) >= 0 ? "+" : ""}${Number(p.pnl_pct ?? 0).toFixed(2)}%`,
            tone: (p.pnl_pct ?? 0) >= 0 ? "good" : "bad",
          });
        }
        break;
      case "debate_round":
        push("debate", {
          cabin: "__round__", name: "The desk", turn: "round",
          text: String(p?.topic ?? ""), topic: String(p?.topic ?? ""),
        });
        break;
      case "debate_message": {
        if (p?.speaker && p?.text) {
          push("debate", {
            cabin: String(p.speaker), name: String(p.name ?? p.speaker),
            turn: String(p.turn ?? "claim"), text: String(p.text),
            topic: String(p.topic ?? ""),
            to: String(p.to ?? ""), to_name: String(p.to_name ?? ""),
          });
        }
        break;
      }
      case "state":
        adopt(p, transportRef.current === "none" ? "ws" : transportRef.current);
        break;
      case "hello": {
        if (p?.state) adopt(p.state, transportRef.current === "none" ? "ws" : transportRef.current);
        // replay what just happened, so a fresh page shows the room as it is
        const recent = Array.isArray(p?.recent) ? p.recent.slice(-40) : [];
        for (const ev of recent) {
          const kind2 = ev?.type;
          if (kind2 === "trader_spawned" || kind2 === "trader_walks" || kind2 === "cabin_verdict"
              || kind2 === "entry_door" || kind2 === "exit_door") {
            try {
              handleEvent(ev);
            } catch {
              /* a message we cannot replay is not worth failing over */
            }
          }
        }
        break;
      }
      default:
        break;
    }
    setSeq((n) => n + 1);
  }, [adopt, push]);

  // ---- transport: websocket, then SSE, then polling ----------------------
  useEffect(() => {
    let ws: WebSocket | null = null;
    let es: EventSource | null = null;
    let timer: number | undefined;
    let stopped = false;

    const poll = async () => {
      try {
        const r = await fetch("/api/state");
        if (r.ok) adopt(await r.json(), "poll");
      } catch {
        /* the server is starting up */
      }
    };

    const openSse = () => {
      try {
        es = new EventSource("/api/stream");
        es.onmessage = (m) => {
          try {
            handleEvent(JSON.parse(m.data));
          } catch {
            /* ignore malformed frames */
          }
        };
        es.onerror = () => {
          es?.close();
          es = null;
        };
      } catch {
        /* not available */
      }
      void poll();
      timer = window.setInterval(() => {
        if (transportRef.current !== "ws" && transportRef.current !== "sse") void poll();
      }, pollMs);
    };

    const start = () => {
      try {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${proto}//${location.host}/ws`);
        ws.onmessage = (m) => {
          try {
            handleEvent(JSON.parse(m.data));
          } catch {
            /* ignore */
          }
        };
        ws.onopen = () => {
          transportRef.current = "ws";
          setState((s) => ({ ...s, connected: true, transport: "ws" }));
        };
        ws.onerror = () => {
          ws?.close();
        };
        ws.onclose = () => {
          if (stopped) return;
          ws = null;
          transportRef.current = "none";
          setState((s) => ({ ...s, connected: false }));
          openSse();
        };
      } catch {
        openSse();
      }
    };

    void poll();
    start();
    return () => {
      stopped = true;
      ws?.close();
      es?.close();
      if (timer) window.clearInterval(timer);
    };
  }, [adopt, handleEvent, pollMs]);

  const send = useCallback(async (path: string, body?: unknown) => {
    try {
      await fetch(path, {
        method: "POST",
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      setSeq((n) => n + 1);
    } catch {
      /* the controls are best-effort */
    }
  }, []);

  const refresh = useCallback(() => {
    void fetch("/api/state").then((r) => (r.ok ? r.json() : null)).then((j) => j && adopt(j, transportRef.current === "none" ? "poll" : transportRef.current));
  }, [adopt]);

  // ---- derive the live cabin cards from roster + events ------------------
  const withCabins = useMemo(() => {
    const map = new Map(state.cabins.map((c) => [c.key, { ...c }]));
    for (const r of state.registry) {
      if (!map.has(r.key)) {
        map.set(r.key, {
          key: r.key, label: r.label ?? r.key, model: r.model, role: r.role,
          isCeo: r.is_ceo, thinking: false, since: 0, calls: 0,
        });
      }
    }
    for (const r of state.registry) {
      const c = map.get(r.key);
      if (c) {
        c.model = r.model;
        c.role = r.role;
        c.label = r.label ?? r.key;
      }
    }
    const stat = state.council as any;
    if (stat?.cabins) {
      for (const [key, v] of Object.entries(stat.cabins as Record<string, any>)) {
        const c = map.get(key);
        if (c) {
          c.calls = v.calls ?? c.calls;
          c.latency = v.last_latency_ms ?? c.latency;
          if (v.last_verdict) c.lastVote = v.last_verdict;
        }
      }
    }
    return {
      ...state,
      cabins: [...map.values()].filter((c) => !c.isCeo),
      ceo: map.get("CEO") ?? state.ceo,
    } as SoulState;
  }, [state]);

  return { state: withCabins, events: eventsRef.current, seq, refresh, send };
}

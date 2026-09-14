/** Shared types + helpers for the floor client. */

export type Vec2 = [number, number]

export interface Layout {
  hall: { x0: number; z0: number; x1: number; z1: number; h: number; south: number }
  walk_speed: number
  rooms: RoomDef[]
  walls: WallDef[]
  doors: DoorDef[]
  props: PropDef[]
  desks: DeskDef[]
  signs: SignDef[]
  nodes: Record<string, Vec2>
  floor_zones: { kind: string; rect: [number, number, number, number] }[]
  fly_loop: [number, number, number][]
  nav: { cell: number; x0: number; z0: number; cols: number; rows: number }
}

export interface RoomDef {
  id: string; label: string; subtitle: string; kind: string
  rect: [number, number, number, number]; accent: string
}
export interface WallDef {
  x0: number; z0: number; x1: number; z1: number; h: number; kind: string; y: number
}
export interface DoorDef {
  id: string; label: string; x: number; z: number; width: number; axis: string
  kind: string; room?: string | null; facing: string
}
export interface PropDef {
  kind: string; x: number; z: number; rot: number; w: number; d: number; h: number; y: number
  meta: Record<string, any>
}
export interface DeskDef {
  id: string; index: number; x: number; z: number; block: string; row: number; col: number
  seat: [number, number]
}
export interface SignDef {
  text: string; x: number; z: number; y: number; kind: string; sub: string
  accent: string; width: number; rot: number
}

export interface WalkerFrame {
  id: string
  kind: string
  x: number; z: number; yaw: number
  seated: boolean
  carrying: boolean
  stride: number
  label: string
  sub: string
  accent: string
  trade_id: string | null
  state: string
  confidence: number
  trail: Vec2[]
}

export interface TradeFrame {
  id: string
  symbol: string
  asset_class: string
  direction: string
  desk_id: string
  desk_index: number
  confidence: number
  state: string
  outcome: string
  votes_for: number
  votes_against: number
  avg_confidence: number
  thesis: string
  exec_note: string
  pnl_r: number
  cf_r: number
  label: string
  rr: number
  position: { x: number; z: number; yaw: number }
  stages: StageFrame[]
  verdicts: VerdictFrame[]
  signal: any
}

export interface VerdictFrame {
  judge_id: string; judge_name: string; verdict: string; confidence: number
  score: number; reasoning: string; key_points: string[]; risks: string[]
  engine: string; model: string; latency_ms: number
}

export interface StageFrame {
  id: string; kind: string; cabin_index: number; judge_name: string; stage_index: number
  state: string; verdict?: string | null; confidence?: number | null; summary?: string
}

export interface SeatFrame {
  id: string; name: string; role: string; specialty: string; model: string
  provider: string; cabin: number | null; accent: string; enabled: boolean; live: boolean
  has_key: boolean; open_source_family: string; api_key: string; base_url: string
  api_key_env: string; temperature: number
  /** the key this desk is actually running with, resolved on the host */
  active_key?: string
  active_key_masked?: string
  key_source?: string
  engine?: string
}

export interface ProviderKey {
  env: string; set: boolean; value: string; seats: string[]
}

export interface SeatsResponse {
  seats: SeatFrame[]
  providers: Record<string, ProviderKey>
  engine: { mode: string; hosted: string[]; builtin: string[]; note: string }
}

export interface FlyFrame {
  symbol: string
  state: string
  pos: { x: number; y: number; z: number }
  yaw: number
  strike_flash: number
  inspected: string[]
  cooling: number
  stats: Record<string, number>
  brain: {
    state: any
    trace: { al: number[]; pn: number[]; kc: number[]; mbon: number[] }
    spike_history: number[]
    stats: Record<string, number>
  }
}

export interface FrameMsg {
  type: 'frame'
  t: number
  clock: number
  stats: Record<string, any>
  fly: FlyFrame
  walkers: WalkerFrame[]
  trades: TradeFrame[]
  markets: MarketRow[]
  events: EventMsg[]
  paused: boolean
  speed: number
}

export interface MarketRow {
  symbol: string; name: string; asset_class: string; venue: string
  price: number; change_pct: number; spark: number[]; tick_rate: number; spread: number
}

export interface EventMsg {
  kind: string
  ts: number
  clock: number
  [k: string]: any
}

export interface DebateMsg {
  id: string
  ts: number
  seat_id: string
  name: string
  role: string
  kind: string
  text: string
  accent: string
  lesson?: { id: string; text: string } | null
  topic: string
}

export const CLASS_META: Record<string, { label: string; icon: string; color: string }> = {
  forex: { label: 'Forex', icon: 'FX', color: '#38bdf8' },
  stocks: { label: 'Stocks', icon: 'EQ', color: '#34d399' },
  indices: { label: 'Indices', icon: 'IDX', color: '#a78bfa' },
  futures: { label: 'Futures', icon: 'FUT', color: '#fbbf24' },
  options: { label: 'Options', icon: 'OPT', color: '#f472b6' },
  crypto: { label: 'Crypto', icon: 'CRY', color: '#fb923c' }
}

export const STATE_LABEL: Record<string, string> = {
  discovered: 'DISCOVERED',
  entering: 'ENTERING FLOOR',
  seated: 'AT DESK',
  walking_to_cabin: 'WALKING TO CABIN',
  in_cabin: 'HEARING',
  deliberating: 'DELIBERATING',
  to_executive: 'ESCALATED TO CEO',
  in_executive: 'CEO CHAMBER',
  final_review: 'FINAL REVIEW',
  accepted: 'ACCEPTED · GOING LIVE',
  rejected: 'REJECTED',
  exiting: 'EXITING',
  exited: 'EXITED'
}

export function fmtPrice(p: number): string {
  if (!isFinite(p)) return '—'
  const a = Math.abs(p)
  if (a >= 1000) return p.toLocaleString(undefined, { maximumFractionDigits: 1 })
  if (a >= 10) return p.toFixed(2)
  if (a >= 1) return p.toFixed(4)
  return p.toFixed(5)
}

export function pct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

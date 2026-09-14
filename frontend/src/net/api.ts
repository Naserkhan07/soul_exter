/** REST + WebSocket client for the SOUL EXTER floor. */
import type { DebateMsg, DeskReply, FlyFrame, FrameMsg, Layout, SeatFrame, SeatsResponse, TradeFrame } from '../three/types'

export interface Snapshot {
  clock: number
  stats: Record<string, any>
  fly: FlyFrame & { funnel?: Record<string, number>; recent?: any[]; signals?: any[] }
  walkers: any[]
  trades: TradeFrame[]
  debate: DebateMsg[]
  playbook: any
  outcomes: any[]
  seats: SeatFrame[]
  live: { enabled: boolean; ok: boolean; error: string; count?: number; updated?: number }
  enabled: string[]
  markets: any[]
  counts: Record<string, number>
  paused: boolean
  speed: number
}

async function jget<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${url} -> ${r.status}`)
  return (await r.json()) as T
}

async function jpost<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {})
  })
  if (!r.ok) throw new Error(`${url} -> ${r.status}`)
  return (await r.json()) as T
}

export const api = {
  layout: () => jget<Layout>('/api/layout'),
  state: () => jget<Snapshot>('/api/state'),
  trade: (id: string) => jget<any>(`/api/trades/${id}`),
  chat: (id: string, seatId: string, question: string) =>
    jpost<any>(`/api/trades/${id}/chat`, { seat_id: seatId, question }),
  seats: () => jget<{ seats: SeatFrame[]; llm: Record<string, any> }>('/api/seats'),
  desks: () => jget<{ desks: { seat: SeatFrame; ruling: any }[] }>('/api/desks'),
  /** Ask any desk anything — no ticket required, always answers. */
  askDesk: (seatId: string, question: string, tradeId?: string) =>
    jpost<DeskReply>('/api/chat', { seat_id: seatId, question, trade_id: tradeId }),
  updateSeat: (id: string, patch: Record<string, unknown>) =>
    jpost<SeatFrame>(`/api/seats/${id}`, patch),
  testSeat: (id: string) => jpost<any>(`/api/seats/${id}/test`, {}),
  placeTrade: (id: string, lots?: number) => jpost<any>(`/api/trades/${id}/place`, lots ? { lots } : {}),
  bookTrade: (id: string, lots?: number) => jpost<any>(`/api/trades/${id}/book`, lots ? { lots } : {}),
  broker: () => jget<any>('/api/broker'),
  saveBroker: (patch: Record<string, unknown>) => jpost<any>('/api/broker', patch),
  seatsFull: () => jget<SeatsResponse>('/api/seats'),
  universe: () => jget<{ groups: Record<string, any[]>; enabled: string[]; total: number }>('/api/universe'),
  markets: () => jget<any>('/api/markets'),
  fly: () => jget<any>('/api/fly'),
  playbook: () => jget<any>('/api/playbook'),
  debate: (limit = 90) => jget<{ messages: DebateMsg[]; lessons: any[] }>(`/api/debate?limit=${limit}`),
  debateAsk: (question: string, seatId = 'ceo') => jpost<DebateMsg>('/api/debate/ask', { question, seat_id: seatId }),
  settings: () => jget<any>('/api/settings'),
  saveSettings: (patch: Record<string, unknown>) => jpost<any>('/api/settings', patch),
  control: (action: string, extra: Record<string, unknown> = {}) =>
    jpost<any>('/api/control', { action, ...extra }),
  analytics: () => jget<any>('/api/analytics'),
  health: () => jget<any>('/api/health')
}

export type WsHandler = (msg: any) => void

export class FloorSocket {
  private ws: WebSocket | null = null
  private handlers = new Set<WsHandler>()
  private retry = 0
  private closed = false
  connected = false
  onStatus: ((ok: boolean) => void) | null = null

  constructor(private url?: string) {}

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = this.url || `${proto}://${location.host}/ws`
    this.closed = false
    try {
      this.ws = new WebSocket(url)
    } catch {
      this.scheduleRetry()
      return
    }
    this.ws.onopen = () => {
      this.connected = true
      this.retry = 0
      this.onStatus?.(true)
    }
    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        this.handlers.forEach((h) => h(data))
      } catch {
        /* ignore malformed frame */
      }
    }
    this.ws.onclose = () => {
      this.connected = false
      this.onStatus?.(false)
      this.scheduleRetry()
    }
    this.ws.onerror = () => {
      this.connected = false
      this.onStatus?.(false)
    }
  }

  private scheduleRetry() {
    if (this.closed) return
    this.retry = Math.min(this.retry + 1, 8)
    setTimeout(() => this.connect(), 400 * this.retry)
  }

  send(payload: unknown) {
    if (this.ws && this.connected) this.ws.send(JSON.stringify(payload))
  }

  on(h: WsHandler) {
    this.handlers.add(h)
    return () => this.handlers.delete(h)
  }

  close() {
    this.closed = true
    this.ws?.close()
  }
}

export type { FrameMsg, TradeFrame, SeatFrame, DebateMsg, Layout }

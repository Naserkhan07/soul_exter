import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../net/api'
import { onThought } from '../state/brainBus'
import type { ChatMsg, ChatRoomState, DebateMsg, DeskReply, FrameMsg, SeatFrame, TradeFrame } from '../three/types'
import { CLASS_META, STATE_LABEL, fmtPrice, pct } from '../three/types'

/* ------------------------------------------------------------------ shared */
export function Tag({ children, color, dim }: { children: React.ReactNode; color?: string; dim?: boolean }) {
  return <span className={`tag${dim ? ' tag-dim' : ''}`} style={color ? { ['--tag' as any]: color } : undefined}>{children}</span>
}

export function Bar({ value, color, height = 6 }: { value: number; color?: string; height?: number }) {
  return (
    <div className="bar" style={{ height }}>
      <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color || 'var(--accent)' }} />
    </div>
  )
}

function VerdictPill({ v }: { v: string }) {
  const cls = v === 'approve' ? 'ok' : v === 'reject' ? 'bad' : 'mid'
  return <span className={`verdict verdict-${cls}`}>{v?.toUpperCase() || 'PENDING'}</span>
}

/* ------------------------------------------------------------- trade dock */
export function TradeDock({ trades, selected, onSelect, onPlace, onBook, busy }: {
  trades: TradeFrame[]; selected: string | null; onSelect: (id: string | null) => void
  onPlace: (id: string) => void
  onBook: (id: string) => void
  busy?: Record<string, string>
}) {
  const live = trades.filter((t) => t.state !== 'exited')
  const done = trades.filter((t) => t.state === 'exited').slice(0, 14)
  return (
    <div className="dock">
      <div className="dock-head">
        <span>TRADE PIPELINE</span>
        <span className="muted">{live.length} in flight</span>
      </div>
      <div className="dock-list">
        {live.map((t) => (
          <div key={t.id} className={`tcard${selected === t.id ? ' sel' : ''}`}
               onClick={() => onSelect(t.id)}>
            <div className="tcard-top">
              <span className="tsym">{t.symbol}</span>
              <span className={`tdir ${t.direction}`}>{t.direction.toUpperCase()}</span>
              <span className="tconf">{Math.round(t.confidence * 100)}%</span>
            </div>
            <div className="tcard-mid">
              <span className="tstate">{STATE_LABEL[t.state] || t.state}</span>
              {t.desk_id && <span className="muted">· {t.desk_id.replace('desk_', 'DSK ')}</span>}
            </div>
            <div className="tcard-votes">
              {t.verdicts?.length
                ? t.verdicts.map((v, i) => (
                    <span key={i} className={`vote ${v.verdict}`} title={`${v.judge_name}: ${v.verdict}`}>
                      {v.judge_name[0]}
                    </span>
                  ))
                : <span className="muted small">awaiting cabins…</span>}
              {t.outcome !== 'pending' && <span className={`outcome ${t.outcome}`}>{t.outcome.toUpperCase()}</span>}
            </div>
            <div className="tcard-actions">
              <button className="act place" disabled={!!busy?.[t.id] || !!t.broker_ticket}
                      onClick={(e) => { e.stopPropagation(); onPlace(t.id) }}
                      title={t.broker_ticket ? `already placed (${t.broker_ticket})`
                                             : 'Send this ticket to the broker now — instant'}>
                {busy?.[t.id] === 'place' ? '…' : '⇪ PLACE TRADE'}
              </button>
              <button className="act book" disabled={!!busy?.[t.id]}
                      onClick={(e) => { e.stopPropagation(); onBook(t.id) }}
                      title="Close the position at the current price — instant">
                {busy?.[t.id] === 'book' ? '…' : '✕ BOOK TRADE'}
              </button>
              {t.broker_ticket && (
                <span className={`tk ${t.broker_mode === 'mt5' ? 'mt5' : ''}`}
                      title={`${String(t.broker_mode || '').toUpperCase()} order ${t.broker_ticket}`
                        + (t.place_price ? ` · fill ${fmtPrice(t.place_price)}` : '')}>
                  {t.broker_mode === 'mt5' ? 'MT5 ' : ''}{t.broker_ticket.slice(0, 12)}
                </span>
              )}
            </div>
            <Bar value={t.state === 'in_cabin' ? 0.6 : t.state === 'exited' ? 1 : 0.25}
                 color={t.direction === 'long' ? 'var(--up)' : 'var(--down)'} height={3} />
          </div>
        ))}
        {!live.length && <div className="empty">No tickets on the floor.<br />The fly is hunting…</div>}
      </div>
      {!!done.length && (
        <>
          <div className="dock-sub">CLOSED</div>
          <div className="closed-list">
            {done.map((t) => (
              <div key={t.id} className="closed-row" onClick={() => onSelect(t.id)}>
                <span>{t.symbol}</span>
                <span className={`muted small ${t.direction}`}>{t.direction}</span>
                <span className={t.outcome === 'accepted' ? 'up' : 'down'}>
                  {t.outcome === 'accepted' ? `${t.pnl_r >= 0 ? '+' : ''}${t.pnl_r.toFixed(2)}R`
                    : `veto ${t.cf_r >= 0 ? '+' : ''}${t.cf_r.toFixed(2)}R`}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* ----------------------------------------------------------- trade detail */
export function TradeDetail({ trade, seats, onClose, onAsk, focusSeat, onPlace, onBook, busy }: {
  trade: TradeFrame | null
  seats: SeatFrame[]
  onClose: () => void
  onAsk: (seatId: string, q: string) => Promise<any>
  focusSeat?: string | null
  onPlace?: (id: string) => void
  onBook?: (id: string) => void
  busy?: string
}) {
  const [detail, setDetail] = useState<any>(null)
  const [tab, setTab] = useState<'journey' | 'chat'>('journey')
  const [seatId, setSeatId] = useState<string>('ceo')
  const [q, setQ] = useState('')
  const [chat, setChat] = useState<any[]>([])
  const [sending, setSending] = useState(false)
  const scroll = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!trade) return
    let alive = true
    api.trade(trade.id).then((d) => alive && setDetail(d)).catch(() => {})
    const id = setInterval(() => {
      api.trade(trade.id!).then((d) => alive && setDetail(d)).catch(() => {})
    }, 4000)
    setChat([])
    setTab('journey')
    return () => { alive = false; clearInterval(id) }
  }, [trade?.id])

  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
  }, [chat.length])

  useEffect(() => {
    if (!focusSeat) return
    setSeatId(focusSeat)
    setTab('chat')
  }, [focusSeat, trade?.id])

  if (!trade) return null
  const sig = trade.signal || {}
  const f = sig.features || {}
  const judges = seats.filter((s) => s.cabin !== null)
  const ceo = seats.find((s) => s.id === 'ceo')

  async function send() {
    if (!trade || !q.trim()) return
    setSending(true)
    const question = q.trim()
    setQ('')
    setChat((c) => [...c, { role: 'you', text: question }])
    try {
      const res = await onAsk(seatId, question)
      setChat((c) => [...c, { role: 'llm', name: res.name || seatId, text: res.answer,
        engine: res.engine }])
    } catch (e: any) {
      setChat((c) => [...c, { role: 'llm', name: 'system', text: `Chat failed: ${e.message}` }])
    }
    setSending(false)
  }

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">
            {trade.symbol}
            <span className={`tdir ${trade.direction}`}>{trade.direction.toUpperCase()}</span>
            <span className="muted">{trade.asset_class.toUpperCase()} · {trade.id}</span>
          </div>
          <div className="detail-sub">
            {fmtPrice(sig.entry)} → TP {fmtPrice(sig.take_profit)} · SL {fmtPrice(sig.stop_loss)} ·{' '}
            <span className="up">{sig.rr?.toFixed?.(2) ?? trade.rr}R</span> · horizon {sig.horizon}
          </div>
        </div>
        <button className="ghost" onClick={onClose}>✕</button>
      </div>
      {onPlace && onBook && (
        <div className="detail-actions">
          <button className="act place" disabled={trade.state === 'exited' || !!busy}
                  onClick={() => onPlace(trade.id)}>
            {busy === 'place' ? '…' : '⇪ PLACE TRADE'}
          </button>
          <button className="act book" disabled={trade.state === 'exited' || !!busy}
                  onClick={() => onBook!(trade.id)}>
            {busy === 'book' ? '…' : '✕ BOOK TRADE'}
          </button>
          {trade.broker_ticket && <span className="tk">{trade.broker_mode?.toUpperCase()} · {trade.broker_ticket}</span>}
        </div>
      )}

      <div className="tabs">
        <button className={tab === 'journey' ? 'on' : ''} onClick={() => setTab('journey')}>JOURNEY</button>
        <button className={tab === 'chat' ? 'on' : ''} onClick={() => setTab('chat')}>ASK THE COUNCIL</button>
      </div>

      {tab === 'journey' && (
        <div className="journey">
          <div className="ticket-grid">
            <Stat label="Fly score" value={`${(trade.confidence * 100).toFixed(0)}%`} />
            <Stat label="ATR %" value={`${((f.atr_pct || 0) * 100).toFixed(3)}%`} />
            <Stat label="RSI" value={(f.rsi ?? 0).toFixed(1)} />
            <Stat label="Efficiency" value={(f.efficiency ?? 0).toFixed(2)} />
            <Stat label="Vol pct" value={`${((f.atr_rank || 0) * 100).toFixed(0)}`} />
            <Stat label="Session" value={(f.session ?? 0).toFixed(2)} />
          </div>
          <div className="thesis">{trade.thesis}</div>
          <div className="steps">
            <Step icon="🚪" title="Welcome gate" body="Ticket admitted to the floor" done />
            <Step icon="💺" title={`Desk ${trade.desk_index}`} body="Fly brought it to a trading desk" done />
            {(detail?.stages || []).filter((s: any) => s.kind === 'cabin').map((s: any) => (
              <Step key={s.id} icon="🏛"
                title={`Cabin ${String(s.cabin_index).padStart(2, '0')} · ${s.judge_name}`}
                body={s.verdict ? `${s.verdict.verdict.toUpperCase()} (${(s.verdict.confidence * 100).toFixed(0)}%) — ${s.verdict.reasoning}` : 'hearing…'}
                tone={s.verdict?.verdict}
                transcript={s.transcript} />
            ))}
            {detail?.stages?.filter((s: any) => s.kind === 'executive').map((s: any) => (
              <Step key={s.id} icon="🎩" title={`Executive · ${s.judge_name}`}
                body={s.verdict ? `${s.verdict.verdict.toUpperCase()} — ${s.verdict.reasoning}` : 'ruling…'}
                tone={s.verdict?.verdict} transcript={s.transcript} />
            ))}
            <Step icon={trade.outcome === 'accepted' ? '✅' : trade.outcome === 'rejected' ? '⛔' : '…'}
              title={trade.outcome === 'accepted' ? 'Accepted · walks to market entry'
                : trade.outcome === 'rejected' ? 'Rejected · walks to the exit door' : 'In council'}
              body={trade.exec_note || ''}
              done={trade.outcome !== 'pending'} />
          </div>
          {trade.outcome !== 'pending' && (
            <div className="outcome-box">
              <div>
                <span className="muted">Realised</span>{' '}
                <b className={trade.pnl_r >= 0 ? 'up' : 'down'}>{trade.pnl_r.toFixed(2)}R</b>
              </div>
              {trade.outcome === 'rejected' && (
                <div><span className="muted">Counterfactual</span>{' '}
                  <b className={trade.cf_r >= 0 ? 'up' : 'down'}>{trade.cf_r.toFixed(2)}R</b></div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'chat' && (
        <div className="chat">
          <div className="chat-roles">
            {judges.map((s) => (
              <button key={s.id} className={`chip${seatId === s.id ? ' on' : ''}`}
                      style={{ ['--chip' as any]: s.accent }}
                      onClick={() => setSeatId(s.id)}>
                {s.name}
              </button>
            ))}
            {ceo && (
              <button className={`chip${seatId === 'ceo' ? ' on' : ''}`}
                      style={{ ['--chip' as any]: ceo.accent }} onClick={() => setSeatId('ceo')}>
                {ceo.name} · CEO
              </button>
            )}
          </div>
          <div className="chat-scroll" ref={scroll}>
            <div className="chat-hint">
              Ask any judge why it voted the way it did, what would invalidate the trade,
              or how it would size it. Answers are grounded in this ticket's numbers.
            </div>
            {chat.map((m, i) => (
              <div key={i} className={`bubble ${m.role}`}>
                <div className="bubble-name">{m.name}{m.engine ? ` · ${m.engine}` : ''}</div>
                <div className="bubble-text">{m.text}</div>
              </div>
            ))}
          </div>
          <div className="chat-input">
            <input value={q} placeholder="Why did you approve this? What would make you flip?"
                   onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && send()} />
            <button disabled={sending} onClick={send}>{sending ? '…' : 'SEND'}</button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Copy helper that also works on plain-http origins (localhost / LAN). */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* fall through to the legacy path */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export function CopyButton({ value, label = 'COPY', onDone, className = 'mini' }: {
  value: string; label?: string; onDone?: (ok: boolean) => void; className?: string
}) {
  const [state, setState] = useState<'idle' | 'ok' | 'fail'>('idle')
  return (
    <button className={className} disabled={!value}
            title={value ? 'Copy to clipboard' : 'nothing to copy'}
            onClick={async () => {
              const ok = await copyText(value)
              setState(ok ? 'ok' : 'fail')
              onDone?.(ok)
              setTimeout(() => setState('idle'), 1600)
            }}>
      {state === 'ok' ? '✓ COPIED' : state === 'fail' ? '✗ FAILED' : label}
    </button>
  )
}

export function maskKey(key: string): string {
  if (!key) return ''
  if (key.length <= 10) return '•'.repeat(key.length)
  return `${key.slice(0, 6)}${'•'.repeat(Math.min(14, key.length - 10))}${key.slice(-4)}`
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  )
}

function Step({ icon, title, body, tone, done, transcript }: any) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`step${tone ? ` step-${tone}` : ''}`}>
      <div className="step-icon">{icon}</div>
      <div className="step-body">
        <div className="step-title" onClick={() => transcript && setOpen(!open)}>
          {title} {transcript ? <span className="muted small">{open ? '▾' : '▸'} transcript</span> : null}
        </div>
        <div className="step-text">{body}</div>
        {open && transcript && (
          <div className="transcript">
            {transcript.map((t: any, i: number) => (
              <div key={i} className={`tr ${t.kind}`}>
                <b>{t.name}</b>: {t.text}
                {t.points?.length ? (
                  <ul>{t.points.slice(0, 4).map((p: string, k: number) => <li key={k}>{p}</li>)}</ul>
                ) : null}
                {t.risks?.length ? (
                  <ul className="risk">{t.risks.slice(0, 3).map((p: string, k: number) => <li key={k}>{p}</li>)}</ul>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


/* ---------------------------------------------------------------- orders */
/**
 * Execution desk: what is ready to be routed, what is working at the venue, and
 * what has been booked. PLACE TRADE fires on click; BOOK TRADE closes instantly.
 */
export function OrdersPanel({ onPlace, onBook, onToast, focusTicket }: {
  onPlace: (id: string) => Promise<any>
  onBook: (id: string) => Promise<any>
  onToast?: (msg: string) => void
  focusTicket?: string | null
}) {
  const [book, setBook] = useState<any>(null)
  const [busy, setBusy] = useState<Record<string, string>>({})
  const [showVetoed, setShowVetoed] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const [diag, setDiag] = useState<any[] | null>(null)

  async function refresh() {
    try { setBook(await api.orders()) } catch { /* keep last */ }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3500)
    return () => clearInterval(id)
  }, [])

  useEffect(() => { if (focusTicket) setFlash(focusTicket) }, [focusTicket])

  const broker = book?.broker || {}
  const ready: any[] = book?.ready || []
  const open: any[] = book?.open || []
  const closed: any[] = book?.closed || []
  const vetoed: any[] = book?.vetoed || []
  const positions: any[] = book?.positions || []
  const queued: any[] = book?.queued || []
  const bridge = book?.bridge || {}
  const counts = book?.counts || {}

  async function place(id: string) {
    setBusy((b) => ({ ...b, [id]: 'place' }))
    try {
      await onPlace(id)
      setFlash(id)
    } catch (e: any) {
      onToast?.(`place failed: ${e.message}`)
    }
    setBusy((b) => { const n = { ...b }; delete n[id]; return n })
    refresh()
  }

  async function bookIt(id: string) {
    setBusy((b) => ({ ...b, [id]: 'book' }))
    try {
      await onBook(id)
      setFlash(id)
    } catch (e: any) {
      onToast?.(`book failed: ${e.message}`)
    }
    setBusy((b) => { const n = { ...b }; delete n[id]; return n })
    refresh()
  }

  async function placeAll() {
    const res = await api.placeReady().catch(() => null)
    if (res) onToast?.(`placed ${res.placed} of ${ready.length} ready tickets`)
    refresh()
  }

  async function diagnose() {
    setDiag(null)
    const res = await api.diagnose().catch((e) => ({ steps: [{ step: 'diagnostics', ok: false,
      detail: e.message }] }))
    setDiag((res as any).steps || [])
  }

  async function connect() {
    const res = await api.brokerConnect().catch((e) => ({ broker: { message: e.message } }))
    const b = res?.broker || {}
    onToast?.(`broker ${b.mode}: ${b.message}`)
    refresh()
  }

  const tCard = (t: any, mode: 'ready' | 'open' | 'closed') => {
    const hot = flash === t.id
    const isBusy = !!busy[t.id]
    return (
      <div key={`${mode}-${t.id}`} className={`ocard ${mode}${hot ? ' hot' : ''}`}>
        <div className="ocard-top">
          <span className={`dir ${t.direction}`}>{t.direction === 'long' ? '▲' : '▼'}</span>
          <b>{t.symbol}</b>
          <Tag dim>{t.asset_class}</Tag>
          <span className="ocard-ticket mono">{t.id}</span>
        </div>
        <div className="ocard-grid">
          <span><i>Entry</i>{fmtPrice(t.signal?.entry)}</span>
          <span><i>Stop</i>{fmtPrice(t.signal?.stop_loss)}</span>
          <span><i>Target</i>{fmtPrice(t.signal?.take_profit)}</span>
          <span><i>Fly</i>{Math.round((t.confidence || 0) * 100)}%</span>
          <span><i>Votes</i>{t.votes_for}/5</span>
          <span><i>Lots</i>{t.lots || 0}</span>
        </div>
        {mode === 'ready' && (
          <div className="ocard-foot">
            <span className="muted small">{t.manual ? 'operator-cleared' : 'council-cleared'} ·{' '}
              {t.state === 'exited' ? 'finished walking' : t.state.replace(/_/g, ' ')}</span>
            <button className="act place big" disabled={isBusy} onClick={() => place(t.id)}>
              {isBusy ? 'PLACING…' : '⇪ PLACE TRADE'}
            </button>
          </div>
        )}
        {mode === 'open' && (
          <>
            <div className="ocard-grid">
              <span><i>Ticket</i><b className="mono">{t.broker_ticket}</b></span>
              <span><i>Mode</i><b className={t.broker_mode === 'mt5' ? 'mt5' : ''}>
                {String(t.broker_mode || '').toUpperCase()}</b></span>
              <span><i>Fill</i>{fmtPrice(t.place_price)}</span>
              <span><i>Now</i>{fmtPrice(t.price)}</span>
              <span><i>Unrealised</i>
                <b className={(t.unrealised_r || 0) >= 0 ? 'up' : 'down'}>
                  {Number(t.unrealised_r || 0).toFixed(2)}R</b></span>
              <span><i>USD</i>
                <b className={(t.pnl_usd || 0) >= 0 ? 'up' : 'down'}>
                  {Number(t.pnl_usd || 0).toFixed(2)}</b></span>
            </div>
            <div className="ocard-foot">
              <span className="muted small">{t.broker_message}</span>
              <button className="act book big" disabled={isBusy} onClick={() => bookIt(t.id)}>
                {isBusy ? 'CLOSING…' : '✕ BOOK TRADE'}
              </button>
            </div>
          </>
        )}
        {mode === 'closed' && (
          <div className="ocard-grid">
            <span><i>Ticket</i><b className="mono">{t.broker_ticket}</b></span>
            <span><i>Mode</i>{String(t.broker_mode || '').toUpperCase()}</span>
            <span><i>Fill</i>{fmtPrice(t.place_price)}</span>
            <span><i>Booked</i>{fmtPrice(t.book_price)}</span>
            <span><i>Result</i>
              <b className={(t.pnl_r || 0) >= 0 ? 'up' : 'down'}>{Number(t.pnl_r || 0).toFixed(2)}R</b></span>
            <span><i>USD</i>
              <b className={(t.pnl_usd || 0) >= 0 ? 'up' : 'down'}>{Number(t.pnl_usd || 0).toFixed(2)}</b></span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="panel-body orders">
      <div className={`broker-strip ${broker.mode === 'mt5' && broker.connected ? 'live' : 'paper'}`}>
        <div className="bs-row">
          <span className={`bs-badge ${broker.mode}`}>{String(broker.mode || 'paper').toUpperCase()}</span>
          <b>{broker.mode === 'mt5' && broker.connected ? 'MT5 connected — orders go to the terminal'
            : broker.want_mode === 'mt5-bridge'
              ? (book?.bridge?.linked ? 'MT5 bridge linked — orders go to your PC terminal'
                 : 'MT5 bridge mode · waiting for the bridge to connect')
            : broker.want_mode === 'mt5' ? 'MT5 configured · falling back to paper fills'
            : 'paper routing'}</b>
          <button className="mini" onClick={connect}>TEST / CONNECT</button>
          <button className="mini" onClick={diagnose}>DIAGNOSE</button>
        </div>
        <div className="bs-msg">{broker.message}</div>
        {broker.want_mode === 'mt5' && broker.mode !== 'mt5' && (
          <div className="bs-warn">configured for MT5 — {broker.note}</div>
        )}
        {broker.account && (
          <div className="bs-acct">
            {broker.account.login} · {broker.account.server} · {broker.account.currency}{' '}
            {broker.account.balance} · equity {broker.account.equity} ·{' '}
            {broker.account.demo ? 'DEMO' : 'LIVE'} · leverage 1:{broker.account.leverage}
          </div>
        )}
        <div className="bs-row small muted">
          <span>clip {broker.lots} lots</span>
          <span>auto-place {String(!!broker.auto_place)}</span>
          <span>{counts.live_positions || 0} venue positions</span>
          <span>{counts.open_lots || 0} lots working</span>
          <span>realised {Number(counts.realised_r || 0).toFixed(2)}R</span>
        </div>
        {broker.want_mode !== 'mt5' && (
          <div className="bs-note">
            Orders are simulated. Switch <b>Broker → MT5</b> in Settings, paste your account /
            server / password, press TEST / CONNECT, and every PLACE TRADE goes to your MetaTrader 5
            terminal (forex pairs included, symbol suffix respected).
          </div>
        )}
      </div>

      {diag && (
        <div className="diag">
          {diag.map((s: any, i: number) => (
            <div key={i} className={`diag-row ${s.ok ? 'ok' : 'bad'}`}>
              <span className="diag-mark">{s.ok ? '✓' : '✕'}</span>
              <b>{s.step}</b>
              <span className="diag-detail">{s.detail}</span>
            </div>
          ))}
        </div>
      )}

      <div className="sec-head">
        <span className="sec-title">READY TO PLACE</span>
        <span className="muted small">{ready.length} cleared, unfilled</span>
        {ready.length > 1 && <button className="act place" onClick={placeAll}>⇪ PLACE ALL</button>}
      </div>
      {ready.length === 0 && (
        <div className="muted small pad">
          Nothing waiting. Tickets land here the moment the council clears them, before they are
          routed to the venue.
        </div>
      )}
      {ready.map((t) => tCard(t, 'ready'))}

      {(bridge.enabled || queued.length > 0) && (
        <>
          <div className="sec-head">
            <span className="sec-title">QUEUED FOR THE MT5 BRIDGE</span>
            <span className={`bs-badge ${bridge.linked ? 'mt5' : ''}`}>
              {bridge.linked ? 'BRIDGE LINKED' : 'BRIDGE OFFLINE'}</span>
            <span className="muted small">{queued.length} instruction(s) waiting</span>
          </div>
          <div className={`bs-warn${bridge.linked ? ' ok' : ''}`}>
            {bridge.linked
              ? `The bridge is running${bridge.info?.account ? ` on account ${bridge.info.account}` : ''} — `
                + 'instructions below are being executed in the MT5 terminal right now.'
              : 'No bridge has polled yet. On the machine with MetaTrader 5 run: '
                + 'python3 tools/mt5_bridge.py --floor <this floor url> --login … --server …'}
          </div>
          {queued.map((t) => (
            <div key={`q-${t.id}`} className="ocard queued">
              <div className="ocard-top">
                <span className={`dir ${t.direction}`}>{t.direction === 'long' ? '▲' : '▼'}</span>
                <b>{t.symbol}</b>
                <Tag dim>{t.exec_state === 'book_queued' ? 'CLOSE' : 'PLACE'}</Tag>
                <span className="ocard-ticket mono">{t.exec_id}</span>
              </div>
              <div className="ocard-grid">
                <span><i>Lots</i>{t.lots}</span>
                <span><i>Ref price</i>{fmtPrice(t.signal?.entry)}</span>
                <span><i>Tries</i>{t.exec_state}</span>
              </div>
              <div className="ocard-foot">
                <span className="muted small">{t.broker_message}</span>
                <button className="act book big" disabled={!!busy[t.id]}
                        onClick={() => bookIt(t.id)}>
                  {t.exec_state === 'book_queued' ? 'CANCEL CLOSE' : 'CANCEL PLACEMENT'}
                </button>
              </div>
            </div>
          ))}
        </>
      )}

      <div className="sec-head">
        <span className="sec-title">PLACED · OPEN</span>
        <span className="muted small">{open.length} working at the venue</span>
      </div>
      {open.length === 0 && (
        <div className="muted small pad">No open positions. Hit PLACE TRADE on a ready ticket.</div>
      )}
      {open.map((t) => tCard(t, 'open'))}

      {(positions.length > 0) && (
        <>
          <div className="sec-head">
            <span className="sec-title">VENUE POSITIONS</span>
            <span className="muted small">
              {broker.mode === 'mt5' ? 'read from the MT5 terminal' : 'paper book'}
            </span>
          </div>
          <div className="vtable">
            <div className="vrow head">
              <span>Ticket</span><span>Symbol</span><span>Side</span><span>Lots</span>
              <span>Entry</span><span>Now</span><span>P&L</span>
            </div>
            {positions.slice(0, 18).map((p: any) => (
              <div className="vrow" key={p.ticket}>
                <span className="mono">{p.ticket}</span>
                <span>{p.symbol}</span>
                <span className={p.direction === 'long' ? 'up' : 'down'}>
                  {p.direction === 'long' ? '▲' : '▼'}</span>
                <span>{p.lots}</span>
                <span>{fmtPrice(p.entry)}</span>
                <span>{fmtPrice(p.price)}</span>
                <span className={(p.pnl_usd || 0) >= 0 ? 'up' : 'down'}>
                  {Number(p.pnl_usd || 0).toFixed(2)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="sec-head">
        <span className="sec-title">BOOKED · CLOSED</span>
        <span className="muted small">{closed.length} realised</span>
        <span className={(counts.realised_r || 0) >= 0 ? 'up small' : 'down small'}>
          {Number(counts.realised_r || 0).toFixed(2)}R banked
        </span>
      </div>
      {closed.length === 0 && (
        <div className="muted small pad">Nothing booked yet.</div>
      )}
      {closed.slice(0, 12).map((t) => tCard(t, 'closed'))}

      {vetoed.length > 0 && (
        <>
          <div className="sec-head">
            <span className="sec-title">VETOED BY THE CABINS</span>
            <button className="mini" onClick={() => setShowVetoed(!showVetoed)}>
              {showVetoed ? 'HIDE' : `SHOW ${vetoed.length}`}
            </button>
          </div>
          {showVetoed && vetoed.slice(0, 12).map((t) => (
            <div key={t.id} className="ocard vetoed">
              <div className="ocard-top">
                <span className={`dir ${t.direction}`}>{t.direction === 'long' ? '▲' : '▼'}</span>
                <b>{t.symbol}</b>
                <Tag dim>{t.id}</Tag>
                <span className="muted small">{t.votes_for}/5 approved</span>
              </div>
              <div className="ocard-grid">
                <span><i>Counterfactual</i>
                  <b className={(t.cf_r || 0) >= 0 ? 'down' : 'up'}>{Number(t.cf_r || 0).toFixed(2)}R</b></span>
                <span><i>Exec note</i>{t.exec_note}</span>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------- open desk channel (comms) */
/**
 * Every desk answers anything here: tickets, markets, risk, the floor itself or a
 * plain question. No ticket is required, and no key is required — the built-in
 * analyst engine answers whenever a hosted model is not configured.
 */
export function CommsPanel({ seats, onAsk, focusSeat, onConsumeFocus }: {
  seats: SeatFrame[]
  onAsk: (seatId: string, question: string, tradeId?: string) => Promise<DeskReply>
  focusSeat?: string | null
  onConsumeFocus?: () => void
}) {
  const [seatId, setSeatId] = useState<string>('ceo')
  const [thread, setThread] = useState<Record<string, any[]>>({})
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const scroll = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (focusSeat) { setSeatId(focusSeat); onConsumeFocus?.() }
  }, [focusSeat])

  const desk = seats.find((s) => s.id === seatId) || seats[0]
  const msgs = thread[desk?.id || 'ceo'] || []

  useEffect(() => {
    scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' })
  }, [msgs.length, seatId, busy])

  async function send(text?: string) {
    const question = (text ?? q).trim()
    if (!question || !desk || busy) return
    setQ('')
    setThread((t) => ({ ...t, [desk.id]: [...(t[desk.id] || []), { role: 'you', text: question }] }))
    setBusy(true)
    try {
      const res = await onAsk(desk.id, question)
      setThread((t) => ({ ...t, [desk.id]: [...(t[desk.id] || []), { role: 'desk', ...res }] }))
    } catch (e: any) {
      setThread((t) => ({ ...t, [desk.id]: [...(t[desk.id] || []),
        { role: 'desk', name: desk.name, answer: `The channel dropped: ${e.message}`, engine: 'error' }] }))
    }
    setBusy(false)
  }

  const SUGGESTIONS = [
    'Why did you pass or reject the last ticket?',
    'What is your read on gold?',
    'How would you size with a 1 ATR stop?',
    'Are we net profitable, and why?',
  ]

  return (
    <div className="panel-body comms">
      <div className="comms-head">
        <div className="comms-title">ASK ANY DESK</div>
        <div className="muted small">
          All six desks answer anything — a ticket, a market, risk, process or a plain question.
          No API key needed: each desk falls back to the built-in analyst engine and still answers
          with its own reasoning.
        </div>
      </div>

      <div className="comms-roles">
        {seats.map((s) => (
          <button key={s.id} className={`chip${desk?.id === s.id ? ' on' : ''}`}
                  style={{ ['--chip' as any]: s.accent }}
                  title={`${s.role}${s.specialty ? ' · ' + s.specialty : ''}`}
                  onClick={() => setSeatId(s.id)}>
            {s.name}{s.cabin ? ` · C${String(s.cabin).padStart(2, '0')}` : s.id === 'ceo' ? ' · CEO' : ' · HUNTER'}
          </button>
        ))}
      </div>

      {desk && (
        <div className="comms-desk" style={{ ['--accent' as any]: desk.accent }}>
          <div className="comms-desk-line">
            <b>{desk.name}</b> · {desk.role} · {desk.specialty}
          </div>
          <div className="comms-desk-line muted small">
            {desk.model} · {desk.live ? 'hosted model answering' : 'built-in analyst engine'}
          </div>
          {desk.ruling && (
            <div className={`comms-ruling ${desk.ruling.verdict}`}>
              <span className="cr-badge">{String(desk.ruling.verdict || '').toUpperCase()}</span>
              <span className="cr-sym">{desk.ruling.symbol} {String(desk.ruling.direction || '').toUpperCase()}</span>
              <span className="cr-conf">{Math.round((desk.ruling.confidence || 0) * 100)}%</span>
              <div className="cr-why">{desk.ruling.reasoning}</div>
            </div>
          )}
          {!desk.ruling && (
            <div className="muted small pad">No ruling recorded yet — the first ticket through a cabin lands here.</div>
          )}
        </div>
      )}

      <div className="comms-scroll" ref={scroll}>
        {msgs.length === 0 && (
          <div className="chat-hint">
            Ask {desk?.name} anything — “why did you refuse the last ticket?”, “what’s your read on
            EURUSD?”, “explain expectancy”, “how much should we risk per trade?”, or just say hello.
          </div>
        )}
        {msgs.map((m, i) => (
          m.role === 'you' ? (
            <div key={i} className="bubble you"><div className="bubble-text">{m.text}</div></div>
          ) : (
            <div key={i} className="bubble llm comms-reply">
              <div className="bubble-name">
                {m.name || desk?.name}
                <span className={`eng-badge${m.live ? ' live' : ''}`}>
                  {m.live ? (m.model || 'hosted') : 'built-in engine'}
                </span>
              </div>
              <div className="bubble-text">{m.answer}</div>
              {!!(m.evidence || []).length && (
                <div className="ev-chips">
                  {(m.evidence || []).slice(0, 6).map((e: string, k: number) =>
                    <span key={k} className="ev-chip">{e}</span>)}
                </div>
              )}
            </div>
          )
        ))}
        {busy && <div className="bubble llm"><div className="bubble-text muted">{desk?.name} is thinking…</div></div>}
      </div>

      {msgs.length === 0 && (
        <div className="comms-suggest">
          {SUGGESTIONS.map((s) => <button key={s} className="ghost small" onClick={() => send(s)}>{s}</button>)}
        </div>
      )}

      <div className="chat-input">
        <input value={q} placeholder={`Ask ${desk?.name || 'the desk'} anything…`}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && send()} />
        <button disabled={busy || !q.trim()} onClick={() => send()}>SEND</button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- council view */
export function CouncilPanel({ seats, trades, selected, onSeatClick }: {
  seats: SeatFrame[]; trades: TradeFrame[]; selected: string | null
  onSeatClick: (id: string) => void
}) {
  const trade = trades.find((t) => t.id === selected)
  const judges = seats.filter((s) => s.cabin !== null).sort((a, b) => (a.cabin! - b.cabin!))
  const ceo = seats.find((s) => s.id === 'ceo')
  return (
    <div className="panel-body">
      {trade && (
        <div className="council-ticket">
          Live ticket <b>{trade.symbol} {trade.direction}</b> · {STATE_LABEL[trade.state]}
        </div>
      )}
      {judges.map((s) => {
        const v = trade?.verdicts?.find((x) => x.judge_id === s.id)
        return (
          <div className="seatcard" key={s.id} style={{ ['--chip' as any]: s.accent }}>
            <div className="seat-head">
              <div>
                <div className="seat-name">{s.name}</div>
                <div className="muted small">CABIN {String(s.cabin).padStart(2, '0')} · {s.role}</div>
              </div>
              <span className={`dot ${s.live ? 'live' : 'builtin'}`} title={s.live ? 'hosted model' : 'built-in analyst'} />
            </div>
            <div className="seat-spec">{s.specialty}</div>
            <div className="seat-model">{s.open_source_family || s.model}</div>
            {v && (
              <div className="seat-verdict">
                <VerdictPill v={v.verdict} />
                <span className="muted small">{Math.round(v.confidence * 100)}%</span>
                <span className="muted small">{v.engine}</span>
              </div>
            )}
            {v && <div className="seat-reason">{v.reasoning}</div>}
            {!v && s.ruling && (
              <>
                <div className="seat-verdict">
                  <VerdictPill v={s.ruling.verdict} />
                  <span className="muted small">{Math.round((s.ruling.confidence || 0) * 100)}%</span>
                  <span className="muted small">
                    {s.ruling.live_read
                      ? `live read · ${s.ruling.symbol} ${String(s.ruling.direction || '').toUpperCase()}`
                      : `last ruling · ${s.ruling.symbol} ${String(s.ruling.direction || '').toUpperCase()}`}
                  </span>
                </div>
                <div className="seat-reason">{s.ruling.reasoning}</div>
              </>
            )}
            {!v && !s.ruling && (
              <div className="seat-reason muted small">
                No ticket has reached this cabin yet — ask and I will rule on any live ticket.
              </div>
            )}
            <button className="mini" onClick={() => onSeatClick(s.id)}>ASK {s.name} ANYTHING</button>
          </div>
        )
      })}
      {ceo && (
        <div className="seatcard ceo" style={{ ['--chip' as any]: ceo.accent }}>
          <div className="seat-head">
            <div>
              <div className="seat-name">{ceo.name} · CEO</div>
              <div className="muted small">{ceo.role}</div>
            </div>
            <span className={`dot ${ceo.live ? 'live' : 'builtin'}`} />
          </div>
          <div className="seat-spec">{ceo.specialty}</div>
          <div className="seat-model">{ceo.open_source_family || ceo.model}</div>
          {(() => {
            const v = trade?.verdicts?.find((x) => x.judge_id === ceo.id)
            const r = v || ceo.ruling
            if (!r) return (
              <div className="seat-reason muted small">
                No split ticket has reached the chamber yet — ask me anything and I will answer.
              </div>
            )
            return (
              <>
                <div className="seat-verdict">
                  <VerdictPill v={r.verdict} />
                  <span className="muted small">{Math.round((r.confidence || 0) * 100)}%</span>
                  <span className="muted small">
                    {v ? 'final ruling' : 'live read on the freshest ticket'}
                  </span>
                </div>
                <div className="seat-reason">{r.reasoning}</div>
              </>
            )
          })()}
          <button className="mini" onClick={() => onSeatClick(ceo.id)}>ASK {ceo.name} ANYTHING</button>
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- fly panel */
export function FlyPanel({ fly, stats }: { fly: any; stats: any }) {
  const brain = fly?.brain || {}
  const st = brain.state || {}
  const trace = brain.trace || { al: [], pn: [], kc: [], mbon: [] }
  const mbons = st.mbon || {}
  const hostRef = useRef<HTMLDivElement>(null)
  const vizRef = useRef<import('../three/flybrain3d').FlyBrainViz | null>(null)
  useEffect(() => {
    if (!hostRef.current) return
    let off: (() => void) | null = null
    import('../three/flybrain3d').then(({ FlyBrainViz }) => {
      if (!hostRef.current) return
      vizRef.current = new FlyBrainViz(hostRef.current)
      vizRef.current.setActivity(fly)
      /* every thinking / questioning event on the floor sends light racing
       * ~3 cm down the veins, in the thinker's colour */
      off = onThought((t) => vizRef.current?.think(t.color, t.strength))
    })
    return () => { off?.(); vizRef.current?.dispose(); vizRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => { vizRef.current?.setActivity(fly) }, [fly])
  return (
    <div className="panel-body">
      <div className="fly-head">
        <div className="fly-orb" data-state={fly?.state} />
        <div>
          <div className="fly-title">DROSOPHILA · FLY SCOUT</div>
          <div className="muted small">
            inspecting <b>{fly?.symbol}</b> · {fly?.state} · strike flash{' '}
            {((fly?.strike_flash || 0) * 100).toFixed(0)}%
          </div>
        </div>
      </div>
      <div className="brain3d-host" ref={hostRef} />
      <div className="brain3d-caption">
        <span className="brain3d-pulse" /> fluorescence connectome — hot-pink left lobe,
        neon-green right lobe, red/orange upper-left, cyan/blue upper-right, thick primary
        tracts, luminous synapses. ONE line of light races the veins; it takes a desk's
        colour when that desk thinks.
      </div>
      <div className="ticket-grid">
        <Stat label="Brain state" value={st.state || '—'} />
        <Stat label="Score" value={((st.score ?? 0) * 100).toFixed(1)} />
        <Stat label="Heading" value={(st.heading ?? 0).toFixed(2)} />
        <Stat label="Hungry" value={(st.hungry ?? 0).toFixed(2)} />
        <Stat label="Threshold" value={(st.threshold ?? 0).toFixed(2)} />
        <Stat label="Dopamine" value={(st.dopamine ?? 0).toFixed(2)} />
        <Stat label="Fatigue" value={(st.fatigue ?? 0).toFixed(2)} />
        <Stat label="Strikes" value={String(brain.stats?.strikes ?? 0)} />
      </div>
      <div className="layers">
        <Layer title="Antennal lobe · glomeruli" values={trace.al} color="#38bdf8" />
        <Layer title="Projection neurons" values={trace.pn} color="#a78bfa" />
        <Layer title="Kenyon cells (sparse spikes)" values={trace.kc} color="#34d399" spike />
        <Layer title="Decision output · MBON" values={trace.mbon} color="#facc15" />
      </div>
      <div className="mbon-grid">
        {Object.entries(mbons).map(([k, v]: any) => (
          <div key={k} className="mbon">
            <span>{k}</span>
            <Bar value={(Number(v) + 1) / 2} color={Number(v) > 0 ? 'var(--up)' : 'var(--down)'} />
            <b>{Number(v).toFixed(2)}</b>
          </div>
        ))}
      </div>
      <div className="fly-foot">
        <div>inspected: {fly?.inspected?.slice(-6).join(', ') || '—'}</div>
        <div>hunt funnel: {stats?.funnel ? Object.entries(stats.funnel).map(([k, v]) => `${k} ${v}`).join(' · ') : '—'}</div>
      </div>
    </div>
  )
}

function Layer({ title, values, color, spike }: { title: string; values: number[]; color: string; spike?: boolean }) {
  const bars = useMemo(() => (values || []).slice(0, 48), [values])
  return (
    <div className="layer">
      <div className="layer-title">{title}</div>
      <div className={`layer-bars${spike ? ' spike' : ''}`}>
        {bars.map((v, i) => (
          <span key={i} style={{ height: `${Math.max(3, Math.min(100, (v || 0) * 100))}%`,
            background: color }} />
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ debate room */
export function DebatePanel({ messages, lessons, seats, onAsk }: {
  messages: DebateMsg[]; lessons: any[]; seats: SeatFrame[]
  onAsk: (q: string, seatId: string) => Promise<any>
}) {
  const [q, setQ] = useState('')
  const [seatId, setSeatId] = useState('ceo')
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [messages.length])
  return (
    <div className="panel-body debate">
      <div className="debate-head">
        <span>COUNCIL DEBATE CHAMBER · self-training loop</span>
        <span className="muted small">{messages.length} messages · {lessons.length} ratified lessons</span>
      </div>
      <div className="debate-scroll" ref={ref}>
        {messages.map((m) => (
          <div className="debate-msg" key={m.id} style={{ ['--chip' as any]: m.accent }}>
            <div className="dm-head">
              <span className="dm-name">{m.name}</span>
              <span className={`dm-kind ${m.kind}`}>{m.kind.replace('_', ' ')}</span>
              <span className="muted small">{new Date(m.ts * 1000).toLocaleTimeString()}</span>
            </div>
            <div className="dm-text">{m.text}</div>
            {m.lesson && <div className="dm-lesson">📘 lesson ratified: {m.lesson.text}</div>}
          </div>
        ))}
      </div>
      <div className="chat-input">
        <select value={seatId} onChange={(e) => setSeatId(e.target.value)}>
          {seats.map((s) => <option key={s.id} value={s.id}>{s.name}{s.cabin ? ` · Cabin ${s.cabin}` : ''}</option>)}
        </select>
        <input value={q} placeholder="Put a question to the chamber — it answers with live floor context"
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={async (e) => {
                 if (e.key === 'Enter' && q.trim()) {
                   setBusy(true)
                   await onAsk(q.trim(), seatId).catch(() => {})
                   setQ('')
                   setBusy(false)
                 }
               }} />
        <button disabled={busy} onClick={async () => {
          if (!q.trim()) return
          setBusy(true)
          await onAsk(q.trim(), seatId).catch(() => {})
          setQ('')
          setBusy(false)
        }}>ASK</button>
      </div>
      {!!lessons.length && (
        <div className="lessons">
          <div className="dock-sub">RATIFIED LESSONS</div>
          {lessons.slice(-5).reverse().map((l) => (
            <div key={l.id} className="lesson"><b>{l.id}</b> {l.text}</div>
          ))}
        </div>
      )}
    </div>
  )
}

/* --------------------------------------------------------- council chat room */
const CHAT_KIND_LABEL: Record<string, string> = {
  question: '❓ asks', answer: '💬 answers', remark: 'observes',
  agree: '🤝 agrees', pushback: '⚔️ pushes back', react: 'reacts', lesson: '🎓 trains the floor'
}

export function ChatRoomPanel({ room, seats, onSay }: {
  room: ChatRoomState | null; seats: SeatFrame[]
  onSay: (text: string, seatId?: string) => Promise<any>
}) {
  const [q, setQ] = useState('')
  const [seatId, setSeatId] = useState('')
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const msgs = room?.messages || []
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [msgs.length])
  const byId = useMemo(() => Object.fromEntries(msgs.map((m) => [m.id, m])), [msgs])
  const send = async () => {
    if (!q.trim() || busy) return
    setBusy(true)
    await onSay(q.trim(), seatId || undefined).catch(() => {})
    setQ('')
    setBusy(false)
  }
  return (
    <div className="panel-body chatroom">
      <div className="chatroom-head">
        <span><span className="chatroom-live" /> COUNCIL CHAT ROOM · the desks train each other</span>
        <span className="muted small">turn {room?.turn ?? 0} · {room?.total_messages ?? 0} messages
          {room?.pending ? ' · answering…' : ''}</span>
      </div>
      <div className="chatroom-scroll" ref={ref}>
        {msgs.length === 0 && (
          <div className="muted small" style={{ padding: 14 }}>
            The desks are warming up — the first message lands within a few seconds…
          </div>
        )}
        {msgs.map((m) => {
          const replySrc = m.reply_to ? byId[m.reply_to] : null
          const targetName = m.target ? seats.find((s) => s.id === m.target)?.name : null
          const isOp = m.seat_id === 'operator'
          return (
            <div key={m.id} className={`chat-msg ${m.kind}${isOp ? ' op' : ''}`}
                 style={{ ['--chip' as any]: m.accent }}>
              <div className="cm-head">
                <span className="cm-name">{m.name}</span>
                <span className={`cm-kind ${m.kind}`}>{CHAT_KIND_LABEL[m.kind] || m.kind}</span>
                {targetName && m.kind === 'question' && <span className="cm-target">@{targetName}</span>}
                {m.live && <span className="cm-live">LIVE MODEL</span>}
                <span className="muted small">{new Date(m.ts * 1000).toLocaleTimeString()}</span>
              </div>
              {replySrc && (
                <div className="cm-reply">↳ answering <b>{replySrc.name}</b>:
                  “{replySrc.text.slice(0, 72)}{replySrc.text.length > 72 ? '…' : ''}”</div>
              )}
              <div className="cm-text">{m.text}</div>
              {m.kind === 'lesson' && (
                <div className="cm-lesson">📘 ratified into the playbook
                  {m.lesson ? ` · ${m.lesson.id}` : ''} — desks now consult this in hearings</div>
              )}
            </div>
          )
        })}
      </div>
      <div className="chat-input">
        <select value={seatId} onChange={(e) => setSeatId(e.target.value)}>
          <option value="">any desk answers</option>
          {seats.map((s) => <option key={s.id} value={s.id}>@{s.name}</option>)}
        </select>
        <input value={q} placeholder="Join the room — ask the desks anything, they answer like colleagues"
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') void send() }} />
        <button disabled={busy} onClick={() => void send()}>{busy ? '…' : 'SAY'}</button>
      </div>
      {!!room?.training?.length && (
        <div className="chatroom-training">
          <div className="dock-sub">TRAINING RECORD — talk sharp, earn XP, level up</div>
          {room.training.map((r) => (
            <div className="train-row" key={r.seat_id}>
              <span className="train-name" style={{ color: r.accent }}>{r.name}</span>
              <span className="train-level">{r.level}</span>
              {r.pretrained && <span className="cm-live"
                                     title={r.trained_on || 'trained on the advanced trading curriculum'}>ADV-TRAINED</span>}
              <span className="train-bar"><span style={{ width: `${Math.round(r.progress * 100)}%`,
                                                          background: r.accent }} /></span>
              <span className="train-xp">{r.xp} xp</span>
              <span className="muted small">❓{r.asked} · 💬{r.answered} · 🎓{r.lessons}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ market panel */
export function MarketsPanel({ markets, enabled, counts }: {
  markets: any[]; enabled: string[]; counts: Record<string, number>
}) {
  const [filter, setFilter] = useState('all')
  const rows = markets.filter((m) => filter === 'all' || m.asset_class === filter).slice(0, 40)
  return (
    <div className="panel-body">
      <div className="filters">
        {['all', ...Object.keys(CLASS_META)].map((k) => (
          <button key={k} className={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>
            {k === 'all' ? 'ALL' : CLASS_META[k]?.label || k}
          </button>
        ))}
      </div>
      <div className="mkt-table">
        <div className="mkt-row head">
          <span>Symbol</span><span>Price</span><span>Chg</span><span>Class</span><span>Flow</span>
        </div>
        {rows.map((m) => (
          <div className="mkt-row" key={m.symbol}>
            <span className="mono">{m.symbol}</span>
            <span className="mono">{fmtPrice(m.price)}</span>
            <span className={m.change_pct >= 0 ? 'up' : 'down'}>{pct(m.change_pct)}</span>
            <span className="muted small">{m.asset_class}</span>
            <span className="muted small">{m.tick_rate?.toFixed?.(1) ?? '-'} t/s</span>
          </div>
        ))}
      </div>
      <div className="muted small pad">
        {enabled.length} symbols enabled out of the full universe · live:{' '}
        {markets.length ? 'anchored to venue prints when reachable' : 'synthetic tape'}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------- settings panel */
export function SettingsPanel({ seats, settings, universe, onSeat, onSettings, onTest, engine, providers }: {
  seats: SeatFrame[]
  settings: any
  universe: { groups: Record<string, any[]>; enabled: string[]; total: number } | null
  onSeat: (id: string, patch: Record<string, unknown>) => Promise<void>
  onSettings: (patch: Record<string, unknown>) => Promise<void>
  onTest: (id: string) => Promise<any>
  engine?: { mode: string; hosted: string[]; builtin: string[]; note: string; env_files?: string[] } | null
  providers?: Record<string, { env: string; set: boolean; value: string; seats: string[] }>
}) {
  const [tab, setTab] = useState<'markets' | 'models' | 'engine' | 'broker'>('markets')
  const [local, setLocal] = useState<any>(settings || {})
  const [testResult, setTestResult] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
  const [reveal, setReveal] = useState<Record<string, boolean>>({})
  const [showAllKeys, setShowAllKeys] = useState(true)
  const [copied, setCopied] = useState<Record<string, boolean>>({})
  const [broker, setBroker] = useState<any>(null)
  const [brokerEdit, setBrokerEdit] = useState<any>(null)
  const [showPw, setShowPw] = useState(false)

  useEffect(() => {
    api.broker().then((d) => {
      setBroker(d)
      setBrokerEdit({ ...d.settings, mt5_login: d.settings.login, mt5_password: d.settings.password })
    }).catch(() => {})
  }, [])
  const enabled = useMemo(() => new Set(settings?.enabled_symbols || []), [settings?.enabled_symbols])

  useEffect(() => { setLocal(settings || {}) }, [settings])

  if (!settings) return <div className="panel-body">loading…</div>

  async function toggleSymbol(sym: string) {
    const set = new Set(local.enabled_symbols || [])
    set.has(sym) ? set.delete(sym) : set.add(sym)
    const next = { ...local, enabled_symbols: [...set] }
    setLocal(next)
    setDirty(true)
    await onSettings({ enabled_symbols: [...set] })
  }

  async function bulkToggle(list: string[], on: boolean) {
    const set = new Set(local.enabled_symbols || [])
    list.forEach((s) => (on ? set.add(s) : set.delete(s)))
    setLocal({ ...local, enabled_symbols: [...set] })
    await onSettings({ enabled_symbols: [...set] })
  }

  return (
    <div className="panel-body">
      <div className="tabs">
        <button className={tab === 'markets' ? 'on' : ''} onClick={() => setTab('markets')}>MARKETS</button>
        <button className={tab === 'models' ? 'on' : ''} onClick={() => setTab('models')}>LLM COUNCIL</button>
        <button className={tab === 'broker' ? 'on' : ''} onClick={() => setTab('broker')}>BROKER</button>
        <button className={tab === 'engine' ? 'on' : ''} onClick={() => setTab('engine')}>ENGINE</button>
      </div>

      {tab === 'markets' && universe && (
        <div className="settings-block">
          <div className="muted small pad">
            Tick the instruments the fly is allowed to hunt — every pair, every asset class.
            {dirty ? ' · saved' : ''}
          </div>
          {Object.entries(universe.groups).map(([cls, list]) => {
            const on = list.filter((i) => enabled.has(i.symbol)).length
            return (
              <div className="acblock" key={cls}>
                <div className="achead">
                  <span className="acname" style={{ color: CLASS_META[cls]?.color }}>
                    {CLASS_META[cls]?.icon} {CLASS_META[cls]?.label || cls}
                  </span>
                  <span className="muted small">{on}/{list.length} enabled</span>
                  <button className="mini" onClick={() => bulkToggle(list.map((i) => i.symbol), true)}>ALL</button>
                  <button className="mini" onClick={() => bulkToggle(list.map((i) => i.symbol), false)}>NONE</button>
                </div>
                <div className="symbol-grid">
                  {list.map((i) => (
                    <label key={i.symbol} className={`symbox${enabled.has(i.symbol) ? ' on' : ''}`}>
                      <input type="checkbox" checked={enabled.has(i.symbol)}
                             onChange={() => toggleSymbol(i.symbol)} />
                      <span className="symbox-sym">{i.symbol}</span>
                      <span className="symbox-name">{i.name}</span>
                    </label>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {tab === 'models' && (
        <div className="settings-block">
          <div className={`engine-banner ${engine?.mode === 'hosted' ? 'hosted' : 'builtin'}`}>
            <div className="eb-head">
              <span className="eb-dot" />
              {engine?.mode === 'hosted'
                ? `Hosted models answering: ${engine?.hosted?.join(', ')}`
                : 'All desks running the built-in analyst engine'}
            </div>
            <div className="eb-note">{engine?.note}</div>
            <div className="eb-note">
              Reading keys from: <code>{engine?.env_files?.length
                ? engine.env_files.join(' · ')
                : 'host environment only — add a .env with OPENROUTER_API_KEY to run hosted models'}</code>
            </div>
            <div className="model-actions">
              <CopyButton className="mini" label="COPY ALL RUNNING KEYS"
                value={seats.map((x) => `${x.name}\t${x.engine}\t${x.active_key || '(built-in engine — no key)'}`)
                  .join('\n')} />
              <CopyButton className="mini" label="COPY SEAT REPORT"
                value={seats.map((x) => `${x.name} · ${x.role} · ${x.specialty} · ` +
                    `${x.provider}:${x.model} · ${x.live ? 'hosted' : 'built-in'} · ` +
                    `${x.active_key ? x.key_source : 'no key'}`).join('\n')} />
            </div>
            <div className="eb-keys">
              <b>Keys on this host:</b>{' '}
              {providers && Object.values(providers).some((p) => p.set)
                ? Object.entries(providers).filter(([, p]) => p.set).map(([name, p]) => (
                    <span key={name} className="keychip">
                      {p.env} = {showAllKeys ? p.value : maskKey(p.value)}
                      <button className="eye" onClick={() => setShowAllKeys(!showAllKeys)}>
                        {showAllKeys ? 'HIDE' : 'SHOW'}
                      </button>
                      <CopyButton className="eye" label="COPY" value={p.value} />
                    </span>
                  ))
                : <span className="muted">none set — the built-in engine needs no key. Export e.g.
                    OPENROUTER_API_KEY on the host (or paste below) to promote a desk.</span>}
            </div>
          </div>

          {seats.map((s) => {
            const active = s.active_key || ''
            const shown = reveal[s.id] ?? true
            return (
              <div className={`model-card${s.cabin ? '' : ' head'}`} key={s.id}
                   style={{ ['--chip' as any]: s.accent }}>
                <div className="model-head">
                  <span className="model-name">{s.name}</span>
                  <span className="muted small">{s.cabin ? `CABIN ${String(s.cabin).padStart(2, '0')}` : s.role}</span>
                  <span className={`dot ${s.live ? 'live' : 'builtin'}`} />
                  <span className={`mode-tag ${s.live ? 'live' : 'builtin'}`}>
                    {s.live ? 'HOSTED' : 'BUILT-IN'}
                  </span>
                </div>

                <div className="running-key">
                  <span className="rk-label">Running with</span>
                  <span className="rk-engine">{s.engine}</span>
                </div>
                <div className="running-key">
                  <span className="rk-label">API key</span>
                  {active ? (
                    <>
                      <code className="rk-key">{shown ? active : maskKey(active)}</code>
                      <span className="rk-src">
                        {s.key_source === 'seat' ? 'set in this panel'
                          : s.key_source?.startsWith('env:') ? `from host env ${s.key_source.slice(4)}`
                          : 'local engine token (generated on this host)'}
                      </span>
                      <button className="eye" onClick={() => setReveal((r) => ({ ...r, [s.id]: !shown }))}>
                        {shown ? 'HIDE' : 'SHOW'}
                      </button>
                      <CopyButton value={active} label="COPY KEY"
                        onDone={(ok) => setCopied((c) => ({ ...c, [s.id]: ok }))} />
                      {copied[s.id] && <span className="rk-src">copied to clipboard</span>}
                    </>
                  ) : (
                    <span className="rk-none">
                      none — the built-in analyst engine answers this desk (no key required)
                    </span>
                  )}
                </div>

                <div className="model-grid">
                  <label>
                    <span>Model</span>
                    <input value={s.model} onChange={(e) => onSeat(s.id, { model: e.target.value })} />
                  </label>
                  <label>
                    <span>Provider</span>
                    <select value={s.provider}
                            onChange={(e) => onSeat(s.id, { provider: e.target.value })}>
                      {['builtin', 'openrouter', 'together', 'groq', 'deepseek', 'mistral', 'ollama', 'openai', 'custom']
                        .map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>Override key (optional)</span>
                    <input type="password" value={s.api_key || ''}
                           placeholder={s.has_key ? 'using the key shown above' : 'paste to promote this desk'}
                           onChange={(e) => onSeat(s.id, { api_key: e.target.value })} />
                  </label>
                  <label>
                    <span>Base URL</span>
                    <input value={s.base_url} placeholder="auto from provider" 
                           onChange={(e) => onSeat(s.id, { base_url: e.target.value })} />
                  </label>
                  <label>
                    <span>Temperature</span>
                    <input type="number" step="0.05" min="0" max="1" value={s.temperature}
                           onChange={(e) => onSeat(s.id, { temperature: Number(e.target.value) })} />
                  </label>
                  <label className="inline">
                    <span>Enabled</span>
                    <input type="checkbox" checked={s.enabled}
                           onChange={(e) => onSeat(s.id, { enabled: e.target.checked })} />
                  </label>
                </div>
                <div className="model-actions">
                  <button className="mini" onClick={async () => {
                    const r = await onTest(s.id)
                    setTestResult((t) => ({ ...t, [s.id]: `${r.ok ? '✅' : '⚠️'} ${r.message?.slice(0, 200)}` }))
                  }}>TEST SEAT</button>
                  <span className="muted small">{s.specialty}</span>
                </div>
                {testResult[s.id] && <div className="model-test">{testResult[s.id]}</div>}
              </div>
            )
          })}
        </div>
      )}

      {tab === 'broker' && brokerEdit && (
        <div className="settings-block">
          <div className={`engine-banner ${broker?.broker?.mode === 'mt5' ? 'hosted' : 'builtin'}`}>
            <div className="eb-head">
              <span className="eb-dot" />
              {broker?.broker?.mode === 'mt5'
                ? (broker.broker.connected ? 'MetaTrader 5 connected' : 'MetaTrader 5 configured — not connected')
                : 'Paper broker (no venue orders)'}
            </div>
            <div className="eb-note">{broker?.broker?.message}</div>
            {broker?.broker?.account && (
              <div className="eb-keys">
                <span className="keychip">
                  {broker.broker.account.login} · {broker.broker.account.server} ·{' '}
                  {broker.broker.account.currency} {broker.broker.account.balance}
                  {broker.broker.account.demo ? ' · DEMO' : ' · LIVE'}
                </span>
              </div>
            )}
          </div>

          <div className="grid2">
            <label>
              <span>Broker</span>
              <select value={brokerEdit.mode || 'paper'}
                      onChange={(e) => setBrokerEdit({ ...brokerEdit, mode: e.target.value })}>
                <option value="paper">paper — simulate fills</option>
                <option value="mt5">mt5 — terminal on this machine</option>
                <option value="mt5-bridge">mt5-bridge — terminal on your PC (bridge)</option>
              </select>
            </label>
            <label>
              <span>Clip size (lots)</span>
              <input type="number" step="0.01" min="0.01" value={brokerEdit.lots ?? 0.1}
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, lots: Number(e.target.value) })} />
            </label>
            <label>
              <span>MT5 account (login)</span>
              <input value={brokerEdit.login ?? ''} placeholder="112594843"
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, login: Number(e.target.value) || 0 })} />
            </label>
            <label>
              <span>MT5 server</span>
              <input value={brokerEdit.server ?? ''} placeholder="MetaQuotes-Demo"
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, server: e.target.value })} />
            </label>
            <label className="wide">
              <span>MT5 password{' '}
                <button className="eye" type="button" onClick={() => setShowPw(!showPw)}>
                  {showPw ? 'HIDE' : 'SHOW'}
                </button>
                <CopyButton className="eye" label="COPY" value={brokerEdit.mt5_password || ''} />
              </span>
              <input type={showPw ? 'text' : 'password'} value={brokerEdit.mt5_password || ''}
                     placeholder="stored locally in soul_exter_settings.json only"
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, mt5_password: e.target.value })} />
            </label>
            <label>
              <span>Symbol suffix</span>
              <input value={brokerEdit.suffix ?? ''} placeholder="e.g. .m for EURUSD.m"
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, suffix: e.target.value })} />
            </label>
            <label>
              <span>terminal64.exe path (optional)</span>
              <input value={brokerEdit.path ?? ''} placeholder="auto-detected"
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, path: e.target.value })} />
            </label>
            <label className="inline">
              <span>Auto-place approved trades</span>
              <input type="checkbox" checked={!!brokerEdit.auto_place}
                     onChange={(e) => setBrokerEdit({ ...brokerEdit, auto_place: e.target.checked })} />
            </label>
          </div>
          {brokerEdit.mode === 'mt5-bridge' && (
            <div className="bridge-cmd">
              <div className="bc-title">Run this on the machine with MetaTrader 5</div>
              <code>
                python3 tools/mt5_bridge.py --floor {window.location.origin} \<br />
                &nbsp;&nbsp;--login {brokerEdit.login || '…'} --password '{brokerEdit.mt5_password ? '…' : '…'}' \<br />
                &nbsp;&nbsp;--server {brokerEdit.server || 'MetaQuotes-Demo'}
                {brokerEdit.suffix ? ` --suffix ${brokerEdit.suffix}` : ''}
              </code>
              <CopyButton label="COPY COMMAND"
                          value={`python3 tools/mt5_bridge.py --floor ${window.location.origin} `
                            + `--login ${brokerEdit.login || ''} --password 'your-password' `
                            + `--server ${brokerEdit.server || 'MetaQuotes-Demo'}`
                            + (brokerEdit.suffix ? ` --suffix ${brokerEdit.suffix}` : '')} />
              <div className="muted small">
                The bridge polls this floor, sends the orders to your terminal and reports the
                real MT5 ticket back — so PLACE TRADE fills on your account even when the floor
                itself is running on Kaggle.
              </div>
            </div>
          )}

          <div className="model-actions">
            <button className="mini" onClick={async () => {
              const r = await api.saveBroker({
                broker_mode: brokerEdit.mode, mt5_login: Number(brokerEdit.login) || 0,
                mt5_password: brokerEdit.mt5_password, mt5_server: brokerEdit.server,
                mt5_path: brokerEdit.path, mt5_symbol_suffix: brokerEdit.suffix,
                lots: Number(brokerEdit.lots) || 0.1, auto_place: !!brokerEdit.auto_place,
              })
              setBroker({ ...broker, ...r })
            }}>SAVE & CONNECT</button>
            <span className="muted small">
              MT5 needs the terminal installed and running on the same machine
              (Windows, or Linux via Wine). Credentials never leave this host.
            </span>
          </div>
        </div>
      )}

      {tab === 'engine' && (
        <div className="settings-block">
          <div className="grid2">
            <label>
              <span>Fly strike threshold</span>
              <input type="number" step="0.02" value={local.strike_score ?? 0.62}
                     onChange={(e) => setLocal({ ...local, strike_score: Number(e.target.value) })}
                     onBlur={() => onSettings({ strike_score: Number(local.strike_score) })} />
            </label>
            <label>
              <span>Scan interval (s)</span>
              <input type="number" step="0.1" value={local.scan_interval ?? 1.6}
                     onChange={(e) => setLocal({ ...local, scan_interval: Number(e.target.value) })}
                     onBlur={() => onSettings({ scan_interval: Number(local.scan_interval) })} />
            </label>
            <label>
              <span>Symbols per scan burst</span>
              <input type="number" step="1" value={local.scan_batch ?? 12}
                     onChange={(e) => setLocal({ ...local, scan_batch: Number(e.target.value) })}
                     onBlur={() => onSettings({ scan_batch: Number(local.scan_batch) })} />
            </label>
            <label>
              <span>Per-symbol cooldown (s)</span>
              <input type="number" step="1" value={local.cooldown_s ?? 40}
                     onChange={(e) => setLocal({ ...local, cooldown_s: Number(e.target.value) })}
                     onBlur={() => onSettings({ cooldown_s: Number(local.cooldown_s) })} />
            </label>
            <label>
              <span>Max tickets on the floor</span>
              <input type="number" step="1" value={local.max_trades_in_pipe ?? 9}
                     onChange={(e) => setLocal({ ...local, max_trades_in_pipe: Number(e.target.value) })}
                     onBlur={() => onSettings({ max_trades_in_pipe: Number(local.max_trades_in_pipe) })} />
            </label>
            <label>
              <span>Ambient floor traders</span>
              <input type="number" step="1" value={local.ambient_traders ?? 12}
                     onChange={(e) => setLocal({ ...local, ambient_traders: Number(e.target.value) })}
                     onBlur={() => onSettings({ ambient_traders: Number(local.ambient_traders) })} />
            </label>
            <label className="inline">
              <span>Merge live venue prices</span>
              <input type="checkbox" checked={!!local.live_venues}
                     onChange={(e) => onSettings({ live_venues: e.target.checked })} />
            </label>
            <label className="inline">
              <span>Paper-evaluate accepted trades</span>
              <input type="checkbox" checked={!!local.auto_trade_eval}
                     onChange={(e) => onSettings({ auto_trade_eval: e.target.checked })} />
            </label>
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------- analytics */
export function AnalyticsPanel({ stats, playbook, outcomes, fly, book, model }: any) {
  const rows = (playbook?.buckets || []).slice(0, 10)
  return (
    <div className="panel-body">
      <div className="ticket-grid">
        <Stat label="Spawned" value={String(stats?.spawned ?? 0)} />
        <Stat label="Accepted" value={String(stats?.accepted ?? 0)} />
        <Stat label="Vetoed" value={String(stats?.rejected ?? 0)} />
        <Stat label="Wins / Losses" value={`${stats?.wins ?? 0} / ${stats?.losses ?? 0}`} />
        <Stat label="Realised R" value={(stats?.pnl_r ?? 0).toFixed(2)} />
        <Stat label="Fly strikes" value={String(fly?.stats?.strikes ?? 0)} />
      </div>
      <div className="ticket-grid">
        <Stat label="Filled book" value={`${book?.accepted ?? 0}`} />
        <Stat label="Realised" value={`${(book?.accepted_r ?? 0) >= 0 ? '+' : ''}${(book?.accepted_r ?? 0).toFixed(2)}R`} />
        <Stat label="Mean / fill" value={`${(book?.accepted_mean ?? 0) >= 0 ? '+' : ''}${(book?.accepted_mean ?? 0).toFixed(3)}R`} />
        <Stat label="Vetoed" value={`${book?.vetoed ?? 0}`} />
        <Stat label="Veto saved" value={`${(book?.veto_saved_r ?? 0) >= 0 ? '+' : ''}${(book?.veto_saved_r ?? 0).toFixed(2)}R`} />
        <Stat label="Mean / veto" value={`${(book?.veto_mean ?? 0) >= 0 ? '+' : ''}${(book?.veto_mean ?? 0).toFixed(3)}R`} />
      </div>
      <div className="muted small pad">
        {model?.ready
          ? `Expectancy model trained on ${model.samples} settled tickets · tape mean ${model.mean_r >= 0 ? '+' : ''}${model.mean_r}R · baseline win ${Math.round((model.baseline_win || 0) * 100)}%`
          : 'Expectancy model not trained — desks are using their hand-written scorecards.'}
      </div>
      <div className="dock-sub">PLAYBOOK BY BUCKET (asset class · session)</div>
      <div className="pb-table">
        {rows.map((b: any) => (
          <div className="pb-row" key={b.key}>
            <span className="mono">{b.key}</span>
            <span>{b.hit_rate !== null ? `${Math.round(b.hit_rate * 100)}%` : '—'}</span>
            <span className="muted small">{b.sample} trades</span>
            <span className={b.pnl_r >= 0 ? 'up' : 'down'}>{b.pnl_r >= 0 ? '+' : ''}{b.pnl_r}R</span>
          </div>
        ))}
        {!rows.length && <div className="muted small pad">No closed trades yet — the council is still opening the session.</div>}
      </div>
      <div className="dock-sub">RECENT OUTCOMES</div>
      <div className="pb-table">
        {(outcomes || []).slice(-12).reverse().map((o: any) => (
          <div className="pb-row" key={o.trade_id + o.ts}>
            <span className="mono">{o.symbol}</span>
            <span className={o.accepted ? 'up' : 'muted small'}>{o.accepted ? 'FILLED' : 'VETOED'}</span>
            <span className="muted small">{o.trade_id}</span>
            <span className={o.eval_pnl_r >= 0 ? 'up' : 'down'}>
              {o.eval_pnl_r >= 0 ? '+' : ''}{o.eval_pnl_r.toFixed(2)}R
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- event feed */
export function EventTicker({ events }: { events: any[] }) {
  return (
    <div className="ticker">
      {events.slice(-26).reverse().map((e, i) => (
        <span className={`tick tick-${e.kind}`} key={i}>
          <b>{e.kind.replace('_', ' ')}</b>
          {e.judge ? ` ${e.judge} → ${e.verdict}` : ''}
          {e.trade?.symbol ? ` ${e.trade.symbol}` : ''}
          {e.message ? ` ${String(e.message.text).slice(0, 90)}…` : ''}
        </span>
      ))}
    </div>
  )
}

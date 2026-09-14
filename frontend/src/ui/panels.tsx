import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../net/api'
import type { DebateMsg, FrameMsg, SeatFrame, TradeFrame } from '../three/types'
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
export function TradeDock({ trades, selected, onSelect }: {
  trades: TradeFrame[]; selected: string | null; onSelect: (id: string | null) => void
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
export function TradeDetail({ trade, seats, onClose, onAsk, focusSeat }: {
  trade: TradeFrame | null
  seats: SeatFrame[]
  onClose: () => void
  onAsk: (seatId: string, q: string) => Promise<any>
  focusSeat?: string | null
}) {
  const [detail, setDetail] = useState<any>(null)
  const [tab, setTab] = useState<'journey' | 'chat'>('journey')
  const [seatId, setSeatId] = useState<string>('ceo')
  const [q, setQ] = useState('')
  const [chat, setChat] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
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
    setBusy(true)
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
    setBusy(false)
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
            <button disabled={busy} onClick={send}>{busy ? '…' : 'SEND'}</button>
          </div>
        </div>
      )}
    </div>
  )
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
            <button className="mini" onClick={() => onSeatClick(s.id)}>ASK {s.name}</button>
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
          <button className="mini" onClick={() => onSeatClick(ceo.id)}>ASK THE HEAD</button>
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
export function SettingsPanel({ seats, settings, universe, onSeat, onSettings, onTest }: {
  seats: SeatFrame[]
  settings: any
  universe: { groups: Record<string, any[]>; enabled: string[]; total: number } | null
  onSeat: (id: string, patch: Record<string, unknown>) => Promise<void>
  onSettings: (patch: Record<string, unknown>) => Promise<void>
  onTest: (id: string) => Promise<any>
}) {
  const [tab, setTab] = useState<'markets' | 'models' | 'engine'>('markets')
  const [local, setLocal] = useState<any>(settings || {})
  const [testResult, setTestResult] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
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
          <div className="muted small pad">
            Six reasoning desks — five cabin judges plus the Head of Council. Each can run the
            built-in analyst engine (key-free, always available) or a hosted open-source model
            through any OpenAI-compatible provider.
          </div>
          {seats.map((s) => (
            <div className={`model-card${s.cabin ? '' : ' head'}`} key={s.id}
                 style={{ ['--chip' as any]: s.accent }}>
              <div className="model-head">
                <span className="model-name">{s.name}</span>
                <span className="muted small">{s.cabin ? `CABIN ${String(s.cabin).padStart(2, '0')}` : s.role}</span>
                <span className={`dot ${s.live ? 'live' : 'builtin'}`} />
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
                  <span>API key</span>
                  <input type="password" placeholder={s.has_key ? '•••••••• saved' : 'paste key'}
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
                  setTestResult((t) => ({ ...t, [s.id]: `${r.ok ? '✅' : '⚠️'} ${r.message?.slice(0, 180)}` }))
                }}>TEST SEAT</button>
                <span className="muted small">{s.specialty}</span>
              </div>
              {testResult[s.id] && <div className="model-test">{testResult[s.id]}</div>}
            </div>
          ))}
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

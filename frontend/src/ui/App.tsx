import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FloorScene } from '../three/scene'
import { api, FloorSocket, type Snapshot } from '../net/api'
import type { ChatRoomState, DebateMsg, FrameMsg, Layout, SeatFrame, TradeFrame } from '../three/types'
import { AnalyticsPanel, ChatRoomPanel, CommsPanel, CouncilPanel, DebatePanel, EventTicker, FlyPanel,
         MarketsPanel, OrdersPanel,
  SettingsPanel, TradeDetail, TradeDock } from './panels'
import { CLASS_META, fmtPrice } from '../three/types'

type Tab = 'orders' | 'chat' | 'comms' | 'council' | 'debate' | 'fly' | 'markets' | 'settings' | 'analytics'

export function App() {
  const hostRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<FloorScene | null>(null)
  const socketRef = useRef<FloorSocket | null>(null)
  const frameRef = useRef<FrameMsg | null>(null)
  const eventBuf = useRef<any[]>([])

  const [ready, setReady] = useState(false)
  const [bootError, setBootError] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [trades, setTrades] = useState<TradeFrame[]>([])
  const [walkers, setWalkers] = useState<any[]>([])
  const [markets, setMarkets] = useState<any[]>([])
  const [fly, setFly] = useState<any>(null)
  const [flyExtra, setFlyExtra] = useState<any>(null)
  const [stats, setStats] = useState<any>({})
  const [events, setEvents] = useState<any[]>([])
  const [seats, setSeats] = useState<SeatFrame[]>([])
  const [seatMeta, setSeatMeta] = useState<any>(null)
  const [settings, setSettings] = useState<any>(null)
  const [universe, setUniverse] = useState<any>(null)
  const [playbook, setPlaybook] = useState<any>(null)
  const [outcomes, setOutcomes] = useState<any[]>([])
  const [book, setBook] = useState<any>(null)
  const [model, setModel] = useState<any>(null)
  const [debate, setDebate] = useState<DebateMsg[]>([])
  const [chatroom, setChatroom] = useState<ChatRoomState | null>(null)
  const [thoughtTick, setThoughtTick] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('council')
  const [connected, setConnected] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [paused, setPaused] = useState(false)
  const [live, setLive] = useState<any>(null)
  const [cinema, setCinema] = useState(false)
  const [fps, setFps] = useState(60)
  const [chatRequest, setChatRequest] = useState<{ seatId: string; tradeId: string } | null>(null)
  const [lights, setLights] = useState<'bright' | 'moody'>('bright')
  const [orderBusy, setOrderBusy] = useState<Record<string, string>>({})
  const [commsFocus, setCommsFocus] = useState<string | null>(null)
  const [bookInfo, setBookInfo] = useState<any>(null)

  /* how many cleared tickets are still waiting for a PLACE TRADE click */
  const readyCount: number = useMemo(() => {
    const seen = new Set((bookInfo?.open || []).map((t: any) => t.id))
    return trades.filter((t) => t.outcome === 'accepted' && !t.broker_ticket && !seen.has(t.id)
      && !t.closed_manual).length
  }, [trades, bookInfo])
  const [toast, setToast] = useState<string | null>(null)

  /* ---------------------------------------------------------------- boot */
  useEffect(() => {
    let disposed = false
    ;(async () => {
      try {
        const [layout, snap, seatData, uni, book, debateData, chatData] = await Promise.all([
          api.layout(), api.state(), api.seatsFull(), api.universe(), api.playbook(), api.debate(),
          api.chatroom()
        ])
        if (disposed || !hostRef.current) return
        const scene = new FloorScene(hostRef.current, layout as Layout, {
          onSelect: (id) => { setSelected(id); if (id) scene.select(id, true) },
          onJudgeClick: (seatId, tradeId) => {
            if (!tradeId) return
            setSelected(tradeId)
            scene.select(tradeId, true)
            setChatRequest({ seatId, tradeId })
          }
        })
        scene.setSeats(seatData.seats)
        sceneRef.current = scene
        setSeats(seatData.seats)
        setSeatMeta(seatData)
        setSnapshot(snap)
        setTrades(snap.trades)
        setWalkers(snap.walkers)
        setMarkets(snap.markets)
        setFly((snap.fly as any)?.agent || snap.fly)
        setFlyExtra(snap.fly || null)
        setStats(snap.stats)
        setUniverse(uni)
        setDebate(debateData.messages)
        setChatroom(chatData)
        setPlaybook(book)
        setOutcomes(snap.outcomes)
        setSpeed(snap.speed ?? 1)
        setPaused(!!snap.paused)
        setLive(snap.live)
        const s = await api.settings()
        setSettings(s.settings)
        setReady(true)
      } catch (err: any) {
        setBootError(err?.message || String(err))
      }
    })()
    return () => { disposed = true; sceneRef.current?.dispose() }
  }, [])

  /* ------------------------------------------------------------- socket */
  useEffect(() => {
    if (!ready) return
    const sock = new FloorSocket()
    socketRef.current = sock
    sock.onStatus = (ok) => setConnected(ok)
    sock.on((msg) => {
      if (msg.type === 'hello') {
        if (msg.seats) { setSeats(msg.seats); sceneRef.current?.setSeats(msg.seats) }
        return
      }
      if (msg.type === 'frame') {
        frameRef.current = msg
        eventBuf.current.push(...(msg.events || []))
        for (const ev of msg.events || []) {
          sceneRef.current?.handleEvent(ev)
          if (ev.kind === 'chatroom' || ev.kind === 'debate' || ev.kind === 'verdict' ||
              ev.kind === 'trade_finalized' || ev.kind === 'desk_chat') {
            setThoughtTick((x) => x + 1)      /* the fly brain lights a thought */
          }
        }
      }
      if (msg.type === 'chat_reply') {
        /* handled inside the detail panel */
      }
    })
    sock.connect()
    const timer = setInterval(() => {
      const f = frameRef.current
      if (!f) return
      setTrades(f.trades)
      setWalkers(f.walkers)
      setMarkets(f.markets)
      setFly(f.fly)
      setStats(f.stats)
      setSpeed(f.speed)
      setPaused(f.paused)
      sceneRef.current?.setFrame(f)
      if (eventBuf.current.length) {
        setEvents((prev) => [...prev, ...eventBuf.current!].slice(-160))
        eventBuf.current = []
      }
    }, 120)
    const slow = setInterval(async () => {
      try {
        const [book, dbg, st, seatData, an, ob, chat] = await Promise.all([
          api.playbook(), api.debate(), api.state(), api.seatsFull(), api.analytics(), api.orders(),
          api.chatroom()
        ])
        setBookInfo(ob)
        setPlaybook(book)
        setDebate(dbg.messages)
        setChatroom(chat)
        setOutcomes(st.outcomes)
        setLive(st.live)
        setSeats((seatData as any).seats || seatData)
        setSeatMeta(seatData)
        setBook(an.book)
        setModel(an.model)
        try { setFlyExtra(await api.fly()) } catch { /* transient */ }
      } catch { /* transient */ }
    }, 6000)
    const fpsTimer = setInterval(() => setFps(sceneRef.current?.fpsValue ?? 60), 1500)
    return () => { clearInterval(timer); clearInterval(slow); clearInterval(fpsTimer); sock.close() }
  }, [ready])

  /* ------------------------------------------------------------- actions */
  const select = useCallback((id: string | null) => {
    setSelected(id)
    sceneRef.current?.select(id, true)
    if (id) setTab((t) => (t === 'settings' ? 'council' : t))
  }, [])

  const patchSettings = useCallback(async (patch: Record<string, unknown>) => {
    const res = await api.saveSettings(patch)
    setSettings(res.settings)
  }, [])

  const patchSeat = useCallback(async (id: string, patch: Record<string, unknown>) => {
    const updated = await api.updateSeat(id, patch)
    setSeats((prev) => prev.map((s) => (s.id === id ? { ...s, ...updated } : s)))
  }, [])

  const askJudge = useCallback(async (seatId: string, question: string) => {
    let tradeId = selected
    if (!tradeId) {
      const live = trades.find((t) => t.state !== 'exited') || trades[0]
      tradeId = live?.id ?? null
      if (tradeId) setSelected(tradeId)
    }
    if (!tradeId) throw new Error('no ticket on the floor yet')
    return api.chat(tradeId, seatId, question)
  }, [selected, trades])

  const askSeatFromCouncil = useCallback((seatId: string) => {
    setChatRequest(null)
    setCommsFocus(seatId)
    setTab('comms')
  }, [])

  const counts = useMemo(() => ({
    live: trades.filter((t) => t.state !== 'exited').length,
    accepted: stats?.accepted ?? 0,
    rejected: stats?.rejected ?? 0,
    pnl: stats?.pnl_r ?? 0
  }), [trades, stats])

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 7000)
  }, [])

  const placeTrade = useCallback(async (id: string) => {
    setOrderBusy((b) => ({ ...b, [id]: 'place' }))
    let res: any = null
    try {
      res = await api.placeTrade(id)
      showToast(res?.ok
        ? `${res.order?.mode === 'mt5' ? 'MT5' : 'PAPER'} ${res.order?.ticket} · ${res.trade?.symbol} `
          + `${res.order?.lots} lots @ ${res.order?.price} — placed`
        : `NOT ROUTED — ${res?.message}`)
    } catch (e: any) {
      showToast(`place failed: ${e.message}`)
    }
    setOrderBusy((b) => { const n = { ...b }; delete n[id]; return n })
    return res
  }, [showToast])

  const bookTrade = useCallback(async (id: string) => {
    setOrderBusy((b) => ({ ...b, [id]: 'book' }))
    let res: any = null
    try {
      res = await api.bookTrade(id)
      showToast(res?.ok
        ? `BOOKED ${res.trade?.symbol} @ ${res.trade?.book_price} → `
          + `${Number(res.trade?.pnl_r || 0).toFixed(2)}R`
          + (res.trade?.pnl_usd ? ` (${res.trade.pnl_usd >= 0 ? '+' : ''}${res.trade.pnl_usd} USD)` : '')
        : `BOOK FAILED — ${res?.message}`)
    } catch (e: any) {
      showToast(`book failed: ${e.message}`)
    }
    setOrderBusy((b) => { const n = { ...b }; delete n[id]; return n })
    return res
  }, [showToast])

  const selectedTrade = trades.find((t) => t.id === selected) || null

  return (
    <div className={`app${cinema ? ' cinema' : ''}`}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          <div>
            <div className="brand-name">SOUL EXTER</div>
            <div className="brand-sub">autonomous trading council · fly-brain hunter · 6 LLM desks</div>
          </div>
        </div>
        <div className="hud">
          <HudItem label="TICKETS IN FLIGHT" value={String(counts.live)} />
          <HudItem label="ACCEPTED" value={String(counts.accepted)} tone="up" />
          <HudItem label="VETOED" value={String(counts.rejected)} tone="down" />
          <HudItem label="REALISED" value={`${counts.pnl >= 0 ? '+' : ''}${counts.pnl.toFixed(2)}R`}
                   tone={counts.pnl >= 0 ? 'up' : 'down'} />
          <HudItem label="FLY" value={fly?.state || '—'} />
          <HudItem label="FPS" value={String(Math.round(fps))} />
        </div>
        <div className="top-actions">
          <div className={`conn ${connected ? 'ok' : 'bad'}`}>{connected ? 'LIVE FEED' : 'RECONNECTING'}</div>
          <button className="ghost" onClick={() => api.control('strike')} title="Force the fly to open a ticket">
            ⚡ FORCE STRIKE
          </button>
          <button className="ghost" onClick={() => {
            const next = paused
            setPaused(next)
            api.control(next ? 'resume' : 'pause')
          }}>{paused ? '▶ RESUME' : '⏸ PAUSE'}</button>
          <div className="speed">
            {[1, 2, 4, 8].map((s) => (
              <button key={s} className={speed === s ? 'on' : ''}
                      onClick={() => { setSpeed(s); api.control('speed', { value: s }) }}>{s}×</button>
            ))}
          </div>
          <button className="ghost" onClick={() => setCinema(!cinema)}>{cinema ? '◱ PANELS' : '◱ CINEMA'}</button>
        </div>
      </header>

      <div className="stage">
        <div className="canvas-host" ref={hostRef} />
        {bootError && (
          <div className="boot-error">
            <h3>Floor link error</h3>
            <p>{bootError}</p>
            <p className="muted">Start the backend (uvicorn soul_exter.api.server:app) and reload.</p>
          </div>
        )}
        {!ready && !bootError && <div className="boot">waking the floor…</div>}
        <div className="cam-presets">
          {['overview', 'pit', 'corridor', 'cabins', 'executive', 'debate', 'gates', 'tape'].map((p) => (
            <button key={p} onClick={() => sceneRef.current?.setPreset(p)}>{p.toUpperCase()}</button>
          ))}
          <button className={`light-toggle ${lights}`}
                  onClick={() => {
                    const next = lights === 'bright' ? 'moody' : 'bright'
                    setLights(next)
                    sceneRef.current?.setLighting(next)
                  }}>
            {lights === 'bright' ? '☀ LIGHTS ON' : '☾ MOODY'}
          </button>
        </div>
        {!!markets.length && (
          <div className="mini-tape">
            {markets.slice(0, 8).map((m) => (
              <span key={m.symbol}>
                <b>{m.symbol}</b> {fmtPrice(m.price)}{' '}
                <i className={m.change_pct >= 0 ? 'up' : 'down'}>
                  {m.change_pct >= 0 ? '+' : ''}{m.change_pct.toFixed(2)}%
                </i>
              </span>
            ))}
          </div>
        )}
      </div>

      {!cinema && (
        <>
          <aside className="left">
            <TradeDock trades={trades} selected={selected} onSelect={select}
                       onPlace={placeTrade} onBook={bookTrade} busy={orderBusy} />
          </aside>

          <aside className="right">
            <div className="right-tabs">
              {([['orders', 'ORDERS'], ['chat', 'CHAT ROOM'], ['comms', 'ASK ANY DESK'],
                 ['council', 'COUNCIL'],
                 ['debate', 'DEBATE'], ['fly', 'FLY BRAIN'], ['markets', 'MARKETS'],
                 ['analytics', 'ANALYTICS'], ['settings', 'SETTINGS']] as [Tab, string][])
                .map(([k, label]) => (
                  <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
                ))}
            </div>
            <div className="right-body">
              {tab === 'orders' && (
                <OrdersPanel onPlace={placeTrade} onBook={bookTrade} onToast={showToast}
                             focusTicket={selected} />
              )}
              {tab === 'chat' && (
                <ChatRoomPanel room={chatroom} seats={seats}
                               onSay={async (text, seatId) => {
                                 const res = await api.chatroomSay(text, seatId)
                                 setChatroom((c) => c
                                   ? { ...c, messages: [...c.messages, ...res.messages],
                                       total_messages: c.total_messages + res.messages.length }
                                   : c)
                                 return res
                               }} />
              )}
              {tab === 'comms' && (
                <CommsPanel seats={seats} focusSeat={commsFocus}
                            onConsumeFocus={() => setCommsFocus(null)}
                            onAsk={async (seatId, question, tradeId) =>
                              api.askDesk(seatId, question, tradeId)} />
              )}
              {tab === 'council' && <CouncilPanel seats={seats} trades={trades} selected={selected}
                                                  onSeatClick={askSeatFromCouncil} />}
              {tab === 'debate' && <DebatePanel messages={debate} lessons={playbook?.lessons || []}
                                                seats={seats}
                                                onAsk={async (q, seatId) => {
                                                  const msg = await api.debateAsk(q, seatId)
                                                  setDebate((d) => [...d, msg])
                                                  return msg
                                                }} />}
              {tab === 'fly' && <FlyPanel fly={fly} stats={flyExtra || fly} thoughtTick={thoughtTick} />}
              {tab === 'markets' && (
                <MarketsPanel markets={markets} counts={{}}
                              enabled={settings?.enabled_symbols || snapshot?.enabled || []} />
              )}
              {tab === 'analytics' && <AnalyticsPanel stats={stats} playbook={playbook}
                                                      outcomes={outcomes} fly={fly} book={book}
                                                      model={model} />}
              {tab === 'settings' && <SettingsPanel seats={seats} settings={settings} universe={universe}
                                                    onSeat={patchSeat} onSettings={patchSettings}
                                                    engine={seatMeta?.engine}
                                                    providers={seatMeta?.providers}
                                                    onTest={api.testSeat} />}
            </div>
          </aside>

          {selectedTrade && (
            <TradeDetail trade={selectedTrade} seats={seats} onClose={() => select(null)}
                         focusSeat={chatRequest?.tradeId === selectedTrade.id ? chatRequest.seatId : null}
                         onPlace={placeTrade} onBook={bookTrade} busy={orderBusy[selectedTrade.id]}
                         onAsk={async (seatId, q) => askJudge(seatId, q)} />
          )}
        </>
      )}

      {toast && <div className="toast">{toast}</div>}

      <footer className="bottombar">
        <EventTicker events={events} />
        <div className="statusline">
          <span>{live?.enabled ? (live.ok ? `venue feed live · ${live.count || 0} symbols`
            : `synthetic tape (venue unreachable: ${(live.error || 'offline').slice(0, 42)})`) : 'synthetic tape'}</span>
          <span>{(settings?.enabled_symbols || snapshot?.enabled || []).length} markets enabled</span>
          {readyCount > 0 && (
            <span className="ready-pill" onClick={() => setTab('orders')} role="button"
                  title="cleared tickets waiting to be routed — open the ORDERS desk">
              {readyCount} ready to place
            </span>
          )}
          <span>floor clock {Math.round(frameRef.current?.clock || 0)}s</span>
        </div>
      </footer>
    </div>
  )
}

function HudItem({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' }) {
  return (
    <div className="hud-item">
      <span className="hud-label">{label}</span>
      <span className={`hud-value${tone ? ` ${tone}` : ''}`}>{value}</span>
    </div>
  )
}

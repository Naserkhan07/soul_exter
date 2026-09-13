/**
 * SOUL EXTER — the trading floor.
 *
 * The canvas is the room; the interface floats over it. State comes from
 * useSoul (websocket -> SSE -> polling), events are handed to the renderer so
 * people actually move, and the trade record opens the audit drawer.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FloorCanvas, type FloorHandle } from "./components/FloorCanvas";
import {
  BookPanel, CouncilRail, EquitySpark, MarketTape, ScoutPanel, TopBar, TradeList, TraderList,
} from "./components/Panels";
import { TradeDrawer } from "./components/TradeDrawer";
import { useSoul, type ScoutRead, type TradeRow } from "./state/useSoul";
import type { Trader } from "./floor/types";
import "./styles/app.css";

export default function App() {
  const { state, events, seq, refresh, send } = useSoul(4000);
  const [zoom, setZoom] = useState(1);
  const [focusMode, setFocusMode] = useState<"all" | "cabins" | "desks" | "doors">("all");
  const [autoCamera, setAutoCamera] = useState(false);
  const [paused, setPaused] = useState(false);
  const [selected, setSelected] = useState<TradeRow | null>(null);
  const [scoutBatch, setScoutBatch] = useState<ScoutRead[]>([]);
  const handleRef = useRef<FloorHandle | null>(null);

  // the scout's last batch, newest first, for the panel and the drawer
  useEffect(() => {
    const batch = state.scout?.last_batch;
    if (batch && batch.length) setScoutBatch([...batch].reverse());
  }, [state.scout]);

  useEffect(() => {
    setPaused(Boolean(state.engine?.paused));
  }, [state.engine?.paused]);

  const onPick = useCallback((id: string | null) => {
    if (!id) return;
    const row =
      state.recentCouncils.find((t) => t.id === id) ??
      state.tradeLog.find((t) => (t.id ?? (t as { trade_id?: string }).trade_id) === id);
    if (row) setSelected(row);
  }, [state.tradeLog, state.recentCouncils]);

  const onZoom = useCallback((z: number) => {
    setZoom(z);
    handleRef.current?.zoom(z);
  }, []);

  const onFocus = useCallback((m: "all" | "cabins" | "desks" | "doors") => {
    setFocusMode(m);
    handleRef.current?.focus(m);
  }, []);

  const togglePause = useCallback(async () => {
    const next = !paused;
    setPaused(next);
    await send("/api/control", { paused: next });
    refresh();
  }, [paused, refresh, send]);

  const [traders, setTraders] = useState<Trader[]>([]);

  const tradeRows = useMemo<TradeRow[]>(() => {
    // The engine uses `trade_id` in the trade log and `id` in the council
    // records; normalise both so every row has one stable identity.
    const key = (r: TradeRow & { trade_id?: string }) => r.id ?? r.trade_id ?? "";
    const seen = new Map<string, TradeRow>();
    for (const r of state.recentCouncils) seen.set(key(r as TradeRow & { trade_id?: string }), r);
    for (const r of state.tradeLog) {
      const k = key(r as TradeRow & { trade_id?: string });
      seen.set(k, { ...seen.get(k), ...r, id: k } as TradeRow);
    }
    return [...seen.values()].filter((r) => r.id);
  }, [state.recentCouncils, state.tradeLog]);

  return (
    <div className="app">
      <FloorCanvas
        state={state}
        events={events}
        seq={seq}
        zoom={zoom}
        focusMode={focusMode}
        paused={paused}
        autoCamera={autoCamera}
        onPick={onPick}
        onHandle={(h) => { handleRef.current = h; }}
        onTraders={setTraders}
      />

      <div className="overlay">
        <TopBar
          state={state}
          paused={paused}
          onPause={togglePause}
          onScan={() => send("/api/scan")}
          onRefresh={refresh}
          zoom={zoom}
          onZoom={onZoom}
          focusMode={focusMode}
          onFocus={onFocus}
          autoCamera={autoCamera}
          onAuto={() => setAutoCamera((v) => !v)}
        />

        <div className="left-rail">
          <CouncilRail cabins={state.cabins} ceo={state.ceo} council={state.council} />
          <TraderList traders={traders} onSelect={(id) => onPick(id)} />
        </div>

        <div className="right-rail">
          <ScoutPanel scout={state.scout} batch={scoutBatch} />
          <EquitySpark curve={state.equityCurve} starting={state.desk?.starting_cash ?? 15000} />
          <BookPanel positions={state.positions} closed={state.closed} />
          <TradeList rows={tradeRows} onSelect={setSelected} selected={selected?.id} />
        </div>

        <MarketTape ticks={state.ticks} />
      </div>

      <TradeDrawer trade={selected} onClose={() => setSelected(null)} />
    </div>
  );
}


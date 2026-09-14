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
import { CabinChat } from "./components/CabinChat";
import { SettingsPanel } from "./components/SettingsPanel";
import { DebateRoomPanel, type DeskRecord } from "./components/DebateRoom";
import { TradeDrawer } from "./components/TradeDrawer";
import { useSoul, type DebateTurn, type ScoutRead, type TradeRow } from "./state/useSoul";
import type { Trader } from "./floor/types";
import "./styles/app.css";

export default function App() {
  const { state, events, seq, thinking, refresh, send } = useSoul(4000);
  const [zoom, setZoom] = useState(1);
  const [focusMode, setFocusMode] = useState<"all" | "cabins" | "desks" | "doors">("all");
  const [autoCamera, setAutoCamera] = useState(false);
  const [paused, setPaused] = useState(false);
  const [selected, setSelected] = useState<TradeRow | null>(null);
  const [scoutBatch, setScoutBatch] = useState<ScoutRead[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // The room is the point of the floor, so it opens itself the first time this
  // browser sees it — after that, closing it means closed.
  const [roomOpen, setRoomOpen] = useState<boolean>(() => {
    try {
      return !window.localStorage.getItem("soul.room.seen");
    } catch {
      return true;
    }
  });
  const closeRoom = useCallback(() => {
    setRoomOpen(false);
    try {
      window.localStorage.setItem("soul.room.seen", "1");
    } catch {
      /* a private-mode browser is not a reason to fail */
    }
  }, []);
  const [cabinChat, setCabinChat] = useState<string | null>(null);
  // what this desk's settled calls have been worth, straight from the council's
  // scoreboard: a desk with no record says so instead of implying one
  const deskRecord = (key: string) =>
    (state.council as any)?.scoreboard?.desks?.[key] ?? null;
  const [fps, setFps] = useState<number | undefined>(undefined);
  // what the room shows about each desk: its settled record (the training
  // channel's scoreboard) and whoever is composing a turn right now
  const records = useMemo<Record<string, DeskRecord>>(
    () => ((state.council as { scoreboard?: { desks?: Record<string, DeskRecord> } })?.scoreboard?.desks ?? {}),
    [state.council],
  );

  const [liveTurns, setLiveTurns] = useState<
    Array<{ cabin: string; name: string; turn: string; text: string; topic: string }>
  >([]);
  const handleRef = useRef<FloorHandle | null>(null);

  // the scout's last batch, newest first, for the panel and the drawer
  useEffect(() => {
    const batch = state.scout?.last_batch;
    if (batch && batch.length) setScoutBatch([...batch].reverse());
  }, [state.scout]);

  useEffect(() => {
    setPaused(Boolean(state.engine?.paused));
  }, [state.engine?.paused]);

  // The debate panel shows the engine's history plus whatever has been spoken
  // since the last snapshot, so a turn appears the moment it is said.
  useEffect(() => {
    const fresh = events.debate.splice(0);
    if (!fresh.length) return;
    setLiveTurns((prev) => [...prev, ...fresh].slice(-80));
  }, [seq, events.debate]);

  const debateTurns = useMemo<DebateTurn[]>(() => {
    const hist = (state.debate?.transcript ?? []) as DebateTurn[];
    const key = (speaker: string, turn: string, text: string) =>
      `${speaker}|${turn}|${text.length}`;
    // "you" is a distinct speaker on both sides of the wire, so a question asked
    // from the floor is not mistaken for a desk's line
    const seen = new Set(hist.map((t) => key(t.speaker, t.turn, t.text)));
    const extra: DebateTurn[] = liveTurns
      .filter((t) => !seen.has(key(t.cabin, t.turn, t.text)))
      .map((t) => ({
        room: "desk", topic: t.topic, speaker: t.cabin, name: t.name, label: "",
        model: "", turn: t.turn, text: t.text, round: 0,
        ts: Date.now() / 1000, trade_id: null,
      }));
    return [...hist, ...extra].slice(-80);
  }, [state.debate?.transcript, liveTurns]);

  // The cabin whose card was clicked. Both rails and the card list carry the
  // same object, so the chat is fed by whatever the floor already knows.
  const chatCabin = useMemo(() => {
    if (!cabinChat) return null;
    const all = [...state.cabins, ...(state.ceo ? [state.ceo] : [])];
    return all.find((c) => c.key === cabinChat) ?? null;
  }, [cabinChat, state.cabins, state.ceo]);

  const chatQuestion = useMemo(() => {
    if (!chatCabin) return "";
    const fromTurn = [...(state.debate?.transcript ?? [])]
      .reverse()
      .find((t) => t.speaker === chatCabin.key && t.turn !== "answer");
    if (fromTurn?.topic) return fromTurn.topic;
    return state.debate?.topic ?? "";
  }, [chatCabin, state.debate?.topic, state.debate?.transcript]);

  const askDesk = useCallback(
    async (key: string, question: string) => {
      const tradeId = tradeRowsRef.current[0]?.id ?? null;
      // the question becomes a turn on the server, so everybody in the room
      // sees it in order and a refresh keeps it; no local echo needed
      await send("/api/debate/ask", { cabin: key, question, trade_id: tradeId });
      refresh();
    },
    [refresh, send],
  );

  const convene = useCallback(async () => {
    await send("/api/debate/round", { rounds: 1 });
    refresh();
  }, [refresh, send]);

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

  const tradeRowsRef = useRef<TradeRow[]>([]);

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

  tradeRowsRef.current = tradeRows;

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
        onCabin={(key) => setCabinChat(key)}
        onStats={(s) => setFps(s.fps)}
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
          onSettings={() => setSettingsOpen(true)}
          onDebate={() => setRoomOpen(true)}
          trainingTurns={state.debate?.training_turns ?? 0}
          fps={fps}
        />

        <div className="left-rail">
          <CouncilRail
            cabins={state.cabins}
            ceo={state.ceo}
            council={state.council}
            onPick={(key) => setCabinChat(key)}
          />
          <DebateRoomPanel
            transcript={debateTurns}
            lessons={state.debate?.lessons ?? []}
            speakers={state.debate?.speakers ?? []}
            rounds={state.debate?.rounds ?? 0}
            topic={state.debate?.topic ?? null}
            onConvene={convene}
            onOpenRoom={() => setRoomOpen(true)}
            records={records}
            thinking={thinking}
            training={state.training ?? null}
            hours24
          />
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

      {chatCabin && (
        <CabinChat
          cabin={chatCabin}
          turns={debateTurns}
          question={chatQuestion}
          record={deskRecord(chatCabin.key)}
          onAsk={askDesk}
          onClose={() => setCabinChat(null)}
        />
      )}

      {roomOpen && (
        <div className="room-overlay" onMouseDown={closeRoom}>
          <div className="room-shell" onMouseDown={(e) => e.stopPropagation()}>
            <DebateRoomPanel
              variant="room"
              transcript={debateTurns}
              lessons={state.debate?.lessons ?? []}
              speakers={state.debate?.speakers ?? []}
              rounds={state.debate?.rounds ?? 0}
              topic={state.debate?.topic ?? null}
              onConvene={convene}
              onAsk={askDesk}
              records={records}
              thinking={thinking}
              training={state.training ?? null}
              hours24
              onClose={closeRoom}
            />
          </div>
        </div>
      )}

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onApplied={() => refresh()}
      />
    </div>
  );
}


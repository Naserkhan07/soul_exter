/**
 * The canvas host.
 *
 * Owns the SoulFloor instance, drives it from the live state and event stream,
 * and keeps the animation loop going. Everything the engine emits is applied
 * here, in order: people walk in through the welcome door, get called up to the
 * cabins, and leave by the door their verdict sent them to.
 */
import { useEffect, useRef } from "react";
import { SoulFloor } from "../floor/renderer";
import type { Trader } from "../floor/types";
import type { SoulEvents, SoulState } from "../state/useSoul";

export interface FloorHandle {
  focus: (mode: "all" | "cabins" | "desks" | "doors") => void;
  zoom: (z: number) => void;
}

interface Props {
  state: SoulState;
  events: SoulEvents;
  seq: number;
  zoom: number;
  focusMode: "all" | "cabins" | "desks" | "doors";
  paused: boolean;
  autoCamera: boolean;
  onPick: (tradeId: string | null) => void;
  onHandle?: (h: FloorHandle) => void;
  /** a throttled snapshot of everyone on the floor, for the side panel */
  onTraders?: (traders: Trader[]) => void;
}

export function FloorCanvas({
  state, events, seq, zoom, focusMode, paused, autoCamera, onPick, onHandle, onTraders,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const floorRef = useRef<SoulFloor | null>(null);
  const autoRef = useRef<{ lastFocus: number; mode: "all" | "cabins" | "desks" | "doors" }>({
    lastFocus: 0, mode: "all",
  });
  const onTradersRef = useRef(onTraders);
  onTradersRef.current = onTraders;

  // ---- create the renderer, size it, and run the frame loop --------------
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const floor = new SoulFloor(canvas);
    floorRef.current = floor;
    onHandle?.({
      focus: (mode) => floor.focusOn({ mode }),
      zoom: (z) => floor.setZoom(z),
    });

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      floor.resize(rect.width, rect.height, Math.min(2, window.devicePixelRatio || 1));
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    let raf = 0;
    let last = performance.now();
    let reportAt = 0;
    let painted = 0;
    const loop = (now: number) => {
      const dt = now - last;
      last = now;
      floor.frame(dt);
      // Filling the floor is the expensive half of a frame. When nobody is
      // walking and no cabin is deliberating, 30 fps is indistinguishable from
      // 60 and costs half as much.
      if (!floor.idle || now - painted > 32) {
        painted = now;
        floor.draw();
      }
      if (onTradersRef.current && now - reportAt > 1000) {
        reportAt = now;
        onTradersRef.current([...floor.traders.values()]);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    const onClick = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const id = floor.pick(ev.clientX - rect.left, ev.clientY - rect.top);
      onPick(id);
    };
    canvas.addEventListener("click", onClick);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("click", onClick);
      floorRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- state in ----------------------------------------------------------
  useEffect(() => {
    floorRef.current?.setState({
      cabins: state.cabins.length || state.ceo ? [...state.cabins, ...(state.ceo ? [state.ceo] : [])] : state.cabins,
      positions: state.positions,
      ticks: state.ticks,
      paused: state.engine?.paused ?? paused,
    });
  }, [state, paused]);

  useEffect(() => {
    floorRef.current?.setZoom(zoom);
  }, [zoom]);

  useEffect(() => {
    floorRef.current?.focusOn({ mode: focusMode });
  }, [focusMode]);

  useEffect(() => {
    floorRef.current?.setPaused(paused);
  }, [paused]);

  // ---- events in ---------------------------------------------------------
  useEffect(() => {
    const floor = floorRef.current;
    if (!floor) return;
    for (const s of events.spawns.splice(0)) floor.spawn(s);
    for (const m of events.moves.splice(0)) floor.moveTo(m.id, m.target);
    for (const c of events.cabinThinking.splice(0)) floor.cabinThinking(c.cabin);
    for (const v of events.cabinVerdicts.splice(0)) {
      floor.cabinVote(v.cabin, v.verdict, v.confidence, v.symbol, v.reason);
    }
    for (const d of events.debate.splice(0)) {
      floor.cabinSpeak(d.cabin, d.turn, d.text);
    }
    for (const e of events.ends.splice(0)) floor.endTrade(e.id, e.decision, e.reason);
    for (const f of events.floats.splice(0)) floor.float(f.id, f.text, f.tone);

    // Optional camera: follow the action — to the cabins while the council is
    // deliberating, back to the doors when trades are leaving.
    if (autoCamera) {
      const now = performance.now();
      if (now - autoRef.current.lastFocus > 7000) {
        autoRef.current.lastFocus = now;
        const next =
          events.cabinVerdicts.length || events.cabinThinking.length || events.debate.length ? "cabins"
            : events.ends.length ? "doors" : "desks";
        if (next !== autoRef.current.mode) {
          autoRef.current.mode = next;
          floor.focusOn({ mode: next });
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seq]);

  return (
    <div className="floor-wrap" ref={wrapRef}>
      <canvas ref={canvasRef} className="floor-canvas" />
    </div>
  );
}

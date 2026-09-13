/**
 * The interface around the floor: the roster of brains, the scout's ledger, the
 * book, the tape, and the trade record.
 *
 * Each panel is a small dumb component; the App owns the state.
 */
import { useMemo } from "react";
import type { Cabin, PositionView, Tick, Trader } from "../floor/types";
import type { ScoutRead, ScoutStats, TradeRow } from "../state/useSoul";

const money = (v: number) =>
  v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const short = (s?: string, n = 22) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s ?? "");

export const VERDICT_TONE: Record<string, string> = {
  APPROVE: "good",
  REJECT: "bad",
  ABSTAIN: "warn",
  CONFIRM: "good",
  CONTRADICT: "bad",
  WAIT: "warn",
  ENTER: "good",
  SKIP: "bad",
};

export function Chip({ text, tone }: { text: string; tone?: string }) {
  return <span className={`chip ${tone ?? ""}`}>{text}</span>;
}

// ---------------------------------------------------------------------------
export function TopBar({
  state, paused, onPause, onScan, onRefresh, zoom, onZoom, focusMode, onFocus, autoCamera, onAuto,
  onSettings, onDebate, fps,
}: {
  state: ReturnType<typeof import("../state/useSoul").useSoul>["state"];
  paused: boolean;
  onPause: () => void;
  onScan: () => void;
  onRefresh: () => void;
  zoom: number;
  onZoom: (z: number) => void;
  focusMode: "all" | "cabins" | "desks" | "doors";
  onFocus: (m: "all" | "cabins" | "desks" | "doors") => void;
  autoCamera: boolean;
  onAuto: () => void;
  onSettings: () => void;
  onDebate: () => void;
  /** frames per second, as measured by the canvas host */
  fps?: number;
}) {
  const desk = state.desk as any;
  const engine = state.engine as any;
  const equity = desk?.equity ?? 0;
  const starting = desk?.starting_cash ?? 15000;
  const realised = desk?.realised ?? 0;
  const pnlPct = starting ? ((equity - starting) / starting) * 100 : 0;
  return (
    <header className="topbar panel">
      <div className="brand">
        <div className="mark">SE</div>
        <div>
          <div className="brand-name">SOUL EXTER</div>
          <div className="brand-sub">
            council trading floor
            <span className={`dot ${state.connected ? "on" : "off"}`} />
            {state.connected ? state.transport.toUpperCase() : "OFFLINE"}
          </div>
        </div>
      </div>

      <div className="stats">
        <Stat label="Equity" value={money(equity)} tone={equity - starting >= 0 ? "good" : "bad"} />
        <Stat label="Session" value={pct(pnlPct)} tone={pnlPct >= 0 ? "good" : "bad"} />
        <Stat label="Realised" value={money(realised)} tone={realised >= 0 ? "good" : "bad"} />
        <Stat label="Open" value={String(state.positions.length)} />
        <Stat label="Win rate" value={desk?.win_rate !== undefined ? `${desk.win_rate}%` : "—"} />
        <Stat label="Mode" value={String(engine?.llm_mode ?? "—")} sub={engine?.cuda ? "GPU" : "CPU"} />
      </div>

      <div className="controls">
        <div className="seg">
          {(["all", "cabins", "desks", "doors"] as const).map((m) => (
            <button key={m} className={focusMode === m ? "active" : ""} onClick={() => onFocus(m)}>
              {m === "all" ? "Floor" : m[0].toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        <label className="zoom">
          <span>Zoom</span>
          <input type="range" min={0.5} max={2.2} step={0.05} value={zoom}
            onChange={(e) => onZoom(parseFloat(e.target.value))} />
        </label>
        <button className={`ghost ${autoCamera ? "active" : ""}`} onClick={onAuto} title="Follow the action">
          Auto-cam
        </button>
        <button className={`ghost ${paused ? "active" : ""}`} onClick={onPause}>
          {paused ? "Resume" : "Pause"}
        </button>
        <button className="ghost" onClick={onScan} title="Force a market scan">
          Scan now
        </button>
        <button className="ghost" onClick={onRefresh}>Sync</button>
        <button className="ghost" onClick={onDebate} title="Hold a debate round now">
          Debate
        </button>
        {fps !== undefined && (
          <span className={`fps ${fps >= 45 ? "good" : fps >= 24 ? "mid" : "bad"}`} title="painted frames per second">
            {fps} fps
          </span>
        )}
        <button className="ghost accent" onClick={onSettings} title="Models and markets">
          Settings
        </button>
      </div>
    </header>
  );
}

function Stat({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ""}`}>{value}{sub ? <em>{sub}</em> : null}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function CouncilRail({ cabins, ceo, council, onPick }: {
  cabins: Cabin[];
  ceo?: Cabin | null;
  council: Record<string, any>;
  /** open that desk's chat — the same thing a click on its card does */
  onPick?: (key: string) => void;
}) {
  const rows = useMemo(() => [...cabins].sort((a, b) => a.key.localeCompare(b.key)), [cabins]);
  return (
    <aside className="rail panel">
      <PanelHead title="Council" sub={`${council?.reviews ?? 0} reviews · ${council?.escalations ?? 0} escalated`} />
      <div className="cabins">
        {rows.map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={() => onPick?.(c.key)}
            title={`${c.name ?? c.key} — open the desk chat`}
            className={`cabin-card ${c.thinking ? "thinking" : ""} ${c.lastVote ? `v-${c.lastVote.toLowerCase()}` : ""}`}
          >
            <div className="cabin-top">
              <span className="cabin-key">{c.key}</span>
              {c.thinking
                ? <Chip text="thinking" tone="warn" />
                : c.lastVote
                  ? <Chip text={c.lastVote} tone={VERDICT_TONE[c.lastVote]} />
                  : <Chip text="idle" />}
            </div>
            <div className="cabin-model" title={c.model}>{short(c.model?.split("/").pop() ?? "—", 26)}</div>
            <div className="cabin-meta">
              {c.symbol ? <span className="sym">{c.symbol.replace("/USDT", "")}</span> : <span className="dim">—</span>}
              <span>{c.calls ?? 0} calls</span>
              <span>{c.latency ? `${Math.round(c.latency)}ms` : "—"}</span>
              {c.confidence !== undefined ? <span>{Math.round(c.confidence)}%</span> : null}
            </div>
          </button>
        ))}
        {ceo ? (
          <button
            type="button"
            onClick={() => onPick?.("CEO")}
            title={`${ceo.name ?? "CEO"} — open the desk chat`}
            className={`cabin-card ceo ${ceo.thinking ? "thinking" : ""}`}
          >
            <div className="cabin-top">
              <span className="cabin-key">CEO</span>
              {ceo.thinking ? <Chip text="reasoning" tone="warn" /> : <Chip text="on call" tone="warn" />}
            </div>
            <div className="cabin-model" title={ceo.model}>{short(ceo.model?.split("/").pop() ?? "—", 26)}</div>
            <div className="cabin-meta">
              <span className="dim">breaks split councils</span>
              <span>{ceo.calls ?? 0} calls</span>
            </div>
          </button>
        ) : null}
      </div>
      <div className="legend">
        <div><i className="sw good" /> approved → welcome door</div>
        <div><i className="sw bad" /> rejected → exit door</div>
        <div><i className="sw warn" /> 1–4 votes → escalates to CEO</div>
      </div>
    </aside>
  );
}

function PanelHead({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <div className="panel-head">
      <div>
        <h2>{title}</h2>
        {sub ? <p>{sub}</p> : null}
      </div>
      {right}
    </div>
  );
}

// ---------------------------------------------------------------------------
export function ScoutPanel({ scout, batch }: { scout?: ScoutStats; batch: ScoutRead[] }) {
  const on = scout?.enabled !== false;
  return (
    <section className="panel scout">
      <PanelHead
        title="Fly scout"
        sub={on
          ? `${scout?.neurons ? Object.values(scout.neurons).reduce((a, b) => a + b, 0) : 0} neurons · ${scout?.synapses ?? 0} synapses`
          : "disabled"}
        right={<Chip text={on ? "screening" : "off"} tone={on ? "good" : "bad"} />}
      />
      {on ? (
        <>
          <div className="scout-grid">
            <Mini label="judged" value={scout?.judged ?? 0} />
            <Mini label="confirmed" value={scout?.confirmed ?? 0} tone="good" />
            <Mini label="waited" value={scout?.waited ?? 0} tone="warn" />
            <Mini label="contradicted" value={scout?.contradicted ?? 0} tone="bad" />
            <Mini label="to council" value={scout?.admitted ?? 0} />
            <Mini label="learned" value={scout?.rewards ?? 0} />
          </div>
          <div className="scout-note">
            A FlyWire-inspired spiking network reads the same features the cabins get and decides
            which setups are worth the council's GPU time. Only those walk in through the welcome door.
          </div>
          <div className="scout-batch">
            {batch.slice(0, 7).map((r, i) => (
              <div key={`${r.trade_id ?? r.symbol}-${i}`} className={`scout-row ${r.verdict.toLowerCase()}`}>
                <span className="sym">{r.symbol.replace("/USDT", "")}</span>
                <span className={`side ${r.side.toLowerCase()}`}>{r.side === "LONG" ? "L" : "S"}</span>
                <span className={`vb ${VERDICT_TONE[r.verdict]}`}>{r.verdict}</span>
                <span className="num">{(r.conviction * 100).toFixed(0)}%</span>
                <span className="num dim">z{(r.z_margin ?? 0).toFixed(1)}</span>
              </div>
            ))}
            {batch.length === 0 ? <div className="empty">waiting for the next scan…</div> : null}
          </div>
        </>
      ) : <div className="empty">Set SOUL_SCOUT=1 to screen trades before the council.</div>}
    </section>
  );
}

function Mini({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="mini">
      <div className={`mini-value ${tone ?? ""}`}>{value}</div>
      <div className="mini-label">{label}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function BookPanel({ positions, closed }: { positions: PositionView[]; closed: PositionView[] }) {
  return (
    <section className="panel book">
      <PanelHead title="Book" sub={`${positions.length} open · ${closed.length} closed`} />
      <div className="book-list">
        {positions.map((p) => (
          <div key={p.trade_id} className="book-row">
            <span className="sym">{p.symbol.replace("/USDT", "")}</span>
            <span className={`side ${p.side.toLowerCase()}`}>{p.side === "LONG" ? "L" : "S"}</span>
            <span className="num">{p.entry?.toFixed(p.entry && p.entry > 100 ? 1 : 4)}</span>
            <span className={`num ${(p.pnl_pct ?? 0) >= 0 ? "good" : "bad"}`}>{pct(p.pnl_pct ?? 0)}</span>
          </div>
        ))}
        {positions.length === 0 ? <div className="empty">no open risk</div> : null}
      </div>
      {closed.length ? (
        <div className="book-list closed">
          {closed.slice(0, 5).map((p) => (
            <div key={`c-${p.trade_id}`} className="book-row dim">
              <span className="sym">{p.symbol.replace("/USDT", "")}</span>
              <span className={`side ${p.side.toLowerCase()}`}>{p.side === "LONG" ? "L" : "S"}</span>
              <span className="num">{money(p.pnl ?? 0)}</span>
              <span className={`num ${(p.pnl_pct ?? 0) >= 0 ? "good" : "bad"}`}>{pct(p.pnl_pct ?? 0)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
export function MarketTape({ ticks, book }: { ticks: Tick[]; book?: string[] }) {
  void book;
  if (!ticks.length) return null;
  const loop = [...ticks, ...ticks];
  return (
    <div className="tape panel">
      <div className="tape-track">
        {loop.map((t, i) => (
          <span key={`${t.symbol}-${i}`} className="tape-cell">
            <b>{t.symbol}</b>
            <span className="num">{t.price.toFixed(t.price > 100 ? 2 : 4)}</span>
            <span className={`num ${t.change_pct >= 0 ? "good" : "bad"}`}>{pct(t.change_pct)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function TradeList({ rows, onSelect, selected }: {
  rows: TradeRow[];
  onSelect: (row: TradeRow) => void;
  selected?: string | null;
}) {
  return (
    <section className="panel trades">
      <PanelHead title="Trade record" sub={`${rows.length} in this session`} />
      <div className="trade-rows">
        {rows.slice().reverse().map((r) => (
            <button key={r.id} className={`trade-row ${selected === r.id ? "sel" : ""}`} onClick={() => onSelect(r)}>
              <span className="sym">{r.symbol.replace("/USDT", "")}</span>
              <span className={`side ${(r.side ?? "LONG").toLowerCase()}`}>{(r.side ?? "L")[0]}</span>
              <span className="num">{r.approvals ?? 0}/{(r.approvals ?? 0) + (r.rejections ?? 0)}</span>
              <span className={`vb ${VERDICT_TONE[r.decision ?? "PENDING"] ?? "warn"}`}>{r.decision ?? "…"}</span>
              <span className="dim route">{r.route ?? ""}</span>
              {r.opened ? <Chip text="filled" tone="good" /> : r.blocked ? <Chip text="blocked" tone="warn" /> : null}
            </button>
          ))}
        {rows.length === 0 ? <div className="empty">no trades yet — the scanner is watching the tape</div> : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
export function EquitySpark({ curve, starting }: { curve: Array<{ t: number; equity: number }>; starting: number }) {
  const path = useMemo(() => {
    if (curve.length < 2) return null;
    const xs = curve.map((p) => p.t);
    const ys = curve.map((p) => p.equity);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs) || 1;
    const minY = Math.min(...ys, starting);
    const maxY = Math.max(...ys, starting);
    const w = 260;
    const h = 56;
    const points = curve.map((p) => {
      const x = ((p.t - minX) / Math.max(1, maxX - minX)) * w;
      const y = h - ((p.equity - minY) / Math.max(1e-6, maxY - minY)) * (h - 6) - 3;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const baseY = h - ((starting - minY) / Math.max(1e-6, maxY - minY)) * (h - 6) - 3;
    return { points: points.join(" "), w, h, baseY, up: ys[ys.length - 1] >= starting };
  }, [curve, starting]);

  return (
    <div className="spark panel">
      <div className="spark-head">
        <span>Equity</span>
        <span className={`num ${path?.up ? "good" : "bad"}`}>
          {curve.length ? money(curve[curve.length - 1].equity) : "—"}
        </span>
      </div>
      {path ? (
        <svg viewBox={`0 0 ${path.w} ${path.h}`} preserveAspectRatio="none">
          <line x1="0" y1={path.baseY} x2={path.w} y2={path.baseY} className="baseline" />
          <polyline points={path.points} className={path.up ? "up" : "down"} />
        </svg>
      ) : <div className="empty">collecting…</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
export function TraderList({ traders, onSelect }: { traders: Trader[]; onSelect: (id: string) => void }) {
  return (
    <section className="panel traders">
      <PanelHead title="On the floor" sub={`${traders.length} carrying a trade`} />
      <div className="trader-rows">
        {traders.slice(0, 10).map((t) => (
          <button key={t.id} className="trader-row" onClick={() => onSelect(t.id)}>
            <span className="sym">{t.symbol.replace("/USDT", "")}</span>
            <span className={`side ${t.side.toLowerCase()}`}>{t.side[0]}</span>
            <span className="state">{t.state.replace("_", " ")}</span>
            {t.scout ? <Chip text={t.scout.verdict} tone={VERDICT_TONE[t.scout.verdict]} /> : null}
          </button>
        ))}
        {traders.length === 0 ? <div className="empty">the floor is quiet</div> : null}
      </div>
    </section>
  );
}

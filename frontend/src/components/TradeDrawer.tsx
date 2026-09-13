/**
 * The trade drawer: everything the council saw and decided, for one trade.
 *
 * This is the audit trail the whole project exists to produce — the fly's read,
 * every cabin's verdict with its reason, and what the CEO did with a split
 * council.
 */
import type { TradeRow, VerdictRow } from "../state/useSoul";
import { Chip, VERDICT_TONE } from "./Panels";

const STAGES = ["QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE"];

export function TradeDrawer({ trade, onClose }: { trade: TradeRow | null; onClose: () => void }) {
  if (!trade) return null;
  const verdicts = trade.verdicts ?? [];
  const byCabin = new Map(verdicts.map((v) => [v.cabin, v]));
  const approved = trade.approvals ?? verdicts.filter((v) => v.verdict === "APPROVE").length;
  const rejected = trade.rejections ?? verdicts.filter((v) => v.verdict === "REJECT").length;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>
              {trade.symbol}
              <span className={`side ${ (trade.side ?? "LONG").toLowerCase() }`}>{trade.side}</span>
            </h2>
            <p>
              {trade.strategy?.replace(/_/g, " ").toLowerCase()} · ID {trade.id} ·{" "}
              {trade.ts ? new Date(trade.ts * 1000).toLocaleTimeString() : ""}
            </p>
          </div>
          <div className="drawer-decision">
            <Chip text={trade.decision ?? "PENDING"} tone={VERDICT_TONE[trade.decision ?? "PENDING"] ?? "warn"} />
            <span className="votes">{approved} for · {rejected} against</span>
            <button className="ghost" onClick={onClose}>Close</button>
          </div>
        </div>

        {trade.scout ? (
          <div className="drawer-section scout-read">
            <h3>Fly scout</h3>
            <div className="verdict-row">
              <span className={`vb ${VERDICT_TONE[trade.scout.verdict]}`}>{trade.scout.verdict}</span>
              <span className="num">conviction {(trade.scout.conviction * 100).toFixed(0)}%</span>
              <span className="num">salience {(trade.scout.salience * 100).toFixed(0)}%</span>
              <span className="num">kc {((trade.scout.kc_sparsity ?? 0) * 100).toFixed(0)}% active</span>
            </div>
            <p className="reason">
              Screened before the council: a FlyWire-inspired spiking network read the same features the
              cabins get, in the frame of this proposal, and confirmed it. Only confirmed setups reach a desk.
            </p>
          </div>
        ) : null}

        <div className="drawer-section">
          <h3>Market</h3>
          <div className="kv">
            <div><span>Entry</span><b>{fmt(trade.entry)}</b></div>
            <div><span>Stop</span><b>{fmt(trade.stop)}</b></div>
            <div><span>Target</span><b>{fmt(trade.target)}</b></div>
            <div><span>R:R</span><b>{trade.rr?.toFixed(2) ?? "—"}</b></div>
            <div><span>Score</span><b>{trade.score?.toFixed(2) ?? "—"}</b></div>
            <div><span>Confidence</span><b>{trade.confidence ? `${Math.round(trade.confidence)}%` : "—"}</b></div>
          </div>
        </div>

        <div className="drawer-section">
          <h3>Stage by stage</h3>
          <div className="stages">
            {STAGES.map((key, i) => {
              const v = byCabin.get(key);
              return <Stage key={key} index={i} cabin={key} verdict={v} />;
            })}
          </div>
          {trade.ceo ? <Stage index={5} cabin="CEO" verdict={trade.ceo} ceo /> : (
            <div className="stage skipped">
              <span className="stage-dot skipped" />
              <div>
                <div className="stage-head"><b>CEO</b><Chip text="not needed" /></div>
                <p>{approved === 5 ? "The council was unanimous — no escalation." : "No split to resolve."}</p>
              </div>
            </div>
          )}
        </div>

        {trade.blocked ? (
          <div className="drawer-section warn">
            <h3>Risk desk</h3>
            <p className="reason">Approved, but the paper desk refused to size it: {trade.blocked}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Stage({ index, cabin, verdict, ceo }: { index: number; cabin: string; verdict?: VerdictRow; ceo?: boolean }) {
  if (!verdict) {
    return (
      <div className="stage skipped">
        <span className="stage-dot skipped" />
        <div>
          <div className="stage-head"><b>{cabin}</b><Chip text="pending" /></div>
          <p>Has not seen this trade yet.</p>
        </div>
      </div>
    );
  }
  return (
    <div className={`stage ${ceo ? "ceo" : ""} ${verdict.verdict.toLowerCase()}`}>
      <span className={`stage-dot ${VERDICT_TONE[verdict.verdict] ?? ""}`}>{index + 1}</span>
      <div>
        <div className="stage-head">
          <b>{cabin}</b>
          <Chip text={verdict.verdict} tone={VERDICT_TONE[verdict.verdict]} />
          <span className="num">{Math.round(verdict.confidence)}%</span>
          {verdict.latency_ms ? <span className="num dim">{Math.round(verdict.latency_ms)}ms</span> : null}
          {verdict.model ? <span className="model">{verdict.model.split("/").pop()}</span> : null}
        </div>
        <p className="reason">{verdict.reason}</p>
        {verdict.risk_flags?.length ? (
          <div className="flags">{verdict.risk_flags.map((f) => <Chip key={f} text={f} tone="warn" />)}</div>
        ) : null}
      </div>
    </div>
  );
}

function fmt(v?: number): string {
  if (v === undefined || v === null) return "—";
  return v >= 100 ? v.toFixed(2) : v.toFixed(4);
}

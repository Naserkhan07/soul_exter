/**
 * Execution: the scanned book on the left, the placed book on the right.
 *
 * Left half — every trade the six desks have ruled on: the signal, the vote
 * split, the stop, the size it would take, and where it would go. One click
 * sends it to that venue.
 *
 * Right half — what is actually live at the broker: the asset/pair name, the
 * side, the entry and the live P&L, and a Close trade button that books the
 * position immediately.
 *
 * Nothing here decides anything: this is the operator's hand on the order flow,
 * and every row says which venue will take it (MT5 or paper) so a fill is never
 * mistaken for something it is not.
 */
import { useMemo, useState } from "react";
import type { BrokerOrder, BrokerStatus, ScannedSignal } from "../state/useSoul";

const money = (v: number | undefined | null, ccy = "USD") =>
  `${v == null ? "—" : v < 0 ? "-" : ""}$${Math.abs(Number(v)).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}${ccy && ccy !== "USD" ? ` ${ccy}` : ""}`;

const num = (v: number | undefined | null, digits = 5) =>
  v == null ? "—" : Number(v).toLocaleString(undefined, {
    minimumFractionDigits: digits, maximumFractionDigits: digits });

const venueTag = (venue?: string) => (venue === "mt5" ? "MT5" : venue === "paper" ? "PAPER" : "—");

export function ExecutionPanel({
  signals, orders, broker, onPlace, onClose, onCloseAll, onRefresh, wide, onExpand,
}: {
  signals: ScannedSignal[];
  orders: { open: BrokerOrder[]; closed: BrokerOrder[] };
  broker: BrokerStatus | null;
  onPlace: (signalId: string, riskPct: number) => Promise<void>;
  onClose: (ticket: string) => Promise<void>;
  onCloseAll: () => Promise<void>;
  onRefresh: () => void;
  /** the same panel rendered large, over the floor */
  wide?: boolean;
  onExpand?: () => void;
}) {
  const [riskPct, setRiskPct] = useState(broker?.autotrade?.risk_pct ?? 0.5);
  const [armed, setArmed] = useState(Boolean(broker?.autotrade?.on));
  const [classes, setClasses] = useState<string[]>(broker?.autotrade?.classes ?? ["forex"]);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const openCount = orders.open.length;
  const placeable = useMemo(() => signals.filter((s) => s.placeable), [signals]);

  const say = (tone: "good" | "bad", text: string) => {
    setFlash({ tone, text });
    window.setTimeout(() => setFlash(null), 6000);
  };

  const place = async (s: ScannedSignal) => {
    setBusy(s.id);
    try {
      await onPlace(s.id, riskPct);
      setFlash({ tone: "good", text: `sent ${s.symbol} ${s.side} to ${venueTag(s.venue)}` });
      window.setTimeout(() => setFlash(null), 6000);
    } catch (err: any) {
      setFlash({ tone: "bad",
        text: `${s.symbol}: ${err?.detail?.message ?? err?.message ?? "the broker refused it"}` });
      window.setTimeout(() => setFlash(null), 9000);
    } finally {
      setBusy(null);
    }
  };

  const close = async (o: BrokerOrder) => {
    setBusy(o.ticket);
    try {
      await onClose(o.ticket);
      setFlash({ tone: "good", text: `booked ${o.symbol} ${o.side} for ${money(o.pnl, o.currency)}` });
      window.setTimeout(() => setFlash(null), 6000);
    } catch (err: any) {
      setFlash({ tone: "bad",
        text: `${o.symbol}: ${err?.detail?.message ?? err?.message ?? "could not close it"}` });
      window.setTimeout(() => setFlash(null), 9000);
    } finally {
      setBusy(null);
    }
  };

  const arm = async (next: boolean, nextClasses = classes) => {
    setArmed(next);
    setClasses(nextClasses);
    await fetch("/api/broker/autotrade", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ on: next, classes: nextClasses, risk_pct: riskPct }),
    });
    setFlash(next
      ? { tone: "good", text: `auto-trade armed for ${nextClasses.join(", ") || "nothing"}` }
      : { tone: "bad", text: "auto-trade disarmed — you place every order by hand" });
    window.setTimeout(() => setFlash(null), 6000);
  };

  return (
    <section className={`panel exec-panel${wide ? " wide" : ""}`}>
      <header className="panel-head">
        <div className="panel-title">
          <span className="dot" data-live={broker?.connected ? "1" : "0"} />
          Execution
        </div>
        <div className="panel-head-right">
          <span className={`venue-pill ${broker?.connected ? "live" : "paper"}`}>
            {broker?.connected
              ? `MT5 · ${broker?.creds?.server ?? broker?.account?.server ?? ""}`
              : "paper venue"}
          </span>
          <button className="icon-btn" onClick={onRefresh} title="refresh the scanned list">⟳</button>
          {onExpand && (
            <button className="icon-btn" onClick={onExpand}
                    title={wide ? "back to the rail" : "open the order desk large"}>
              {wide ? "✕" : "⤢"}
            </button>
          )}
        </div>
      </header>

      <div className="exec-bar">
        <div className="exec-risk" title="risk per order, as a share of the account's equity">
          <label>risk / trade</label>
          <input
            type="number" min={0.05} max={5} step={0.05} value={riskPct}
            onChange={(e) => setRiskPct(Math.max(0.05, Math.min(5, Number(e.target.value) || 0.5)))}
          />
          <span>%</span>
        </div>
        <label className="switch" title="place every trade the council approves, without a click">
          <input type="checkbox" checked={armed} onChange={(e) => arm(e.target.checked)} />
          <span>auto-place approved</span>
        </label>
        <div className="arm-classes">
          {(broker?.routing ? Object.entries(broker.routing) : []).map(([key, meta]) => (
            <button
              key={key}
              className={classes.includes(key) ? "on" : ""}
              disabled={!armed}
              title={meta.detail}
              onClick={() => arm(armed, classes.includes(key)
                ? classes.filter((c) => c !== key)
                : [...classes, key])}
            >
              {meta.label}
              <em className={meta.venue === "mt5" ? "mt5" : "paper"}>{venueTag(meta.venue)}</em>
            </button>
          ))}
        </div>
      </div>

      {flash && <div className={`exec-flash ${flash.tone}`}>{flash.text}</div>}

      <div className="exec-split">
        <div className="exec-col">
          <h4 className="exec-col-head">
            Scanned by the six desks <b>{signals.length}</b>
            <span className="muted">{placeable.length} ready</span>
          </h4>
          <div className="exec-scroll">
            {signals.length === 0 && (
              <p className="muted pad">No verdict yet — the desks are reading the tape.</p>
            )}
            {signals.map((s) => (
              <article key={s.id} className={`exec-row ${s.placeable ? "" : "blocked"}`}>
                <div className="exec-row-top">
                  <span className="sym">{s.symbol}</span>
                  <span className={`side ${s.side === "LONG" ? "long" : "short"}`}>{s.side}</span>
                  <span className={`verdict ${s.decision === "ENTER" ? "ok" : "no"}`}>
                    {s.decision === "ENTER" ? "APPROVED" : "REJECTED"}
                  </span>
                  <span className={`venue-tiny ${s.venue}`}>{venueTag(s.venue)}</span>
                  <span className="grow" />
                  <span className="votes" title="approvals / votes cast">
                    {s.approvals ?? 0}
                    <i>/</i>
                    {(s.approvals ?? 0) + (s.rejections ?? 0)}
                  </span>
                  {s.confidence != null && <span className="conf">{Math.round(s.confidence)}%</span>}
                </div>
                <div className="exec-name">{s.name ?? s.symbol}</div>
                <div className="votes-strip" title="how each of the six desks voted on this one">
                  {[...(s.verdicts ?? []), ...(s.ceo ? [s.ceo] : [])].map((v) => (
                    <span key={v.cabin} className={`vote ${v.verdict === "APPROVE" ? "yes"
                      : v.verdict === "REJECT" ? "no" : "ab"}`}
                          title={`${v.cabin}: ${v.verdict} ${v.confidence != null ? `${Math.round(v.confidence)}%` : ""}${v.reason ? ` — ${v.reason}` : ""}`}>
                      {v.cabin === "CEO" ? "NVD" : v.cabin.slice(0, 3)}
                      <b>{v.verdict === "APPROVE" ? "✓" : v.verdict === "REJECT" ? "✗" : "–"}</b>
                    </span>
                  ))}
                </div>
                <div className="exec-row-body">
                  <div className="exec-num"><label>entry</label><span>{num(s.entry)}</span></div>
                  <div className="exec-num"><label>stop</label><span className="stop">{num(s.stop)}</span></div>
                  <div className="exec-num"><label>target</label><span className="target">{num(s.target)}</span></div>
                  <div className="exec-num"><label>R:R</label><span>{s.rr ? s.rr.toFixed(2) : "—"}</span></div>
                  <div className="exec-num wide">
                    <label>size</label>
                    <span>
                      {s.sizing?.ok
                        ? `${s.sizing.volume} ${s.sizing.unit} · ${money(s.sizing.risk_dollars)} at risk`
                        : "—"}
                    </span>
                  </div>
                </div>
                <div className="exec-row-actions">
                  <span className="route" title={s.venue_detail}>{s.venue_detail ?? s.venue}</span>
                  <span className="grow" />
                  {s.ticket ? (
                    <span className="taken-tag">placed · {s.ticket}</span>
                  ) : (
                    <button
                      className="place-btn"
                      disabled={!s.placeable || busy === s.id}
                      title={s.blocked ?? `send to ${venueTag(s.venue)}`}
                      onClick={() => place(s)}
                    >
                      {busy === s.id ? "sending…" : "Place trade"}
                    </button>
                  )}
                </div>
                {!s.placeable && s.blocked && <p className="exec-why">{s.blocked}</p>}
              </article>
            ))}
          </div>
        </div>

        <div className="exec-col right">
          <h4 className="exec-col-head">
            Placed trades <b>{openCount}</b>
            {openCount > 1 && (
              <button className="flatten" onClick={async () => {
                await onCloseAll();
                setFlash({ tone: "bad", text: "every live order booked" });
                window.setTimeout(() => setFlash(null), 6000);
              }}>
                close all
              </button>
            )}
          </h4>
          <div className="exec-scroll">
            {openCount === 0 && (
              <p className="muted pad">
                Nothing placed. Pick a scanned trade and hit <b>Place trade</b>.
              </p>
            )}
            {orders.open.map((o) => (
              <article key={o.ticket} className="exec-row open-order">
                <div className="exec-row-top">
                  <span className="sym">{o.symbol}</span>
                  <span className={`side ${o.side === "LONG" ? "long" : "short"}`}>{o.side}</span>
                  <span className={`venue-tiny ${o.venue}`}>{venueTag(o.venue)}</span>
                  <span className="grow" />
                  <span className={`pnl ${(o.pnl ?? 0) >= 0 ? "up" : "down"}`}>
                    {money(o.pnl, o.currency)}
                    <em>{o.pnl_pct != null ? `${o.pnl_pct >= 0 ? "+" : ""}${o.pnl_pct.toFixed(1)}%` : ""}</em>
                  </span>
                </div>
                <div className="exec-name">{o.name ?? o.symbol}</div>
                <div className="exec-row-body">
                  <div className="exec-num"><label>volume</label><span>{o.volume} {o.unit}</span></div>
                  <div className="exec-num"><label>entry</label><span>{num(o.entry)}</span></div>
                  <div className="exec-num"><label>now</label><span>{num(o.price)}</span></div>
                  <div className="exec-num"><label>stop</label><span className="stop">{num(o.stop)}</span></div>
                  <div className="exec-num"><label>target</label><span className="target">{num(o.target)}</span></div>
                  <div className="exec-num"><label>R:R now</label><span>{o.rr_at_fill ? o.rr_at_fill.toFixed(2) : "—"}</span></div>
                  <div className="exec-num wide"><label>risked</label><span>{money(o.risk, o.currency)}</span></div>
                </div>
                <div className="exec-row-actions">
                  <span className="route">
                    ticket {o.ticket}{o.source === "autotrade" ? " · auto-placed" : ""}
                  </span>
                  <span className="grow" />
                  <button className="close-btn" disabled={busy === o.ticket} onClick={() => close(o)}>
                    {busy === o.ticket ? "booking…" : "Close trade"}
                  </button>
                </div>
              </article>
            ))}

            {orders.closed.length > 0 && (
              <>
                <h4 className="exec-sub">Booked this session</h4>
                {orders.closed.slice(0, 14).map((o) => (
                  <div key={o.ticket} className="exec-closed">
                    <span className="sym">{o.symbol}</span>
                    <span className="side-tiny">{o.side}</span>
                    <span className="closed-why">{o.exit_reason || "MANUAL"}</span>
                    <span className="grow" />
                    <span className={`pnl ${(o.pnl ?? 0) >= 0 ? "up" : "down"}`}>
                      {money(o.pnl, o.currency)}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </div>

      <footer className="exec-foot">
        {placeable.length} ready to place · {openCount} live ·{" "}
        {broker?.stats ? `${money(broker.stats.realised, broker?.account?.currency)} booked` : "—"}
        {broker && !broker.connected && (
          <span className="muted"> · {broker.routing?.forex?.detail ?? "paper venue"}</span>
        )}
      </footer>
    </section>
  );
}

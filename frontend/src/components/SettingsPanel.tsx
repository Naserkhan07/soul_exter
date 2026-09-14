/**
 * Settings — the desk roster and the instrument book.
 *
 * Two things live behind this button, and both are operational rather than
 * decorative:
 *
 * 1. **The roster.** Who is on the desk, what each of them is for, and which
 *    *local* model is under the hood. There is no key field on this screen and
 *    there never will be: the models are open weights fetched from Hugging Face
 *    and run on this machine's GPU (or Kaggle's free tier), and the market data
 *    comes from keyless public endpoints. The column that would hold "API key"
 *    is occupied by the model id and the backend instead, which is the honest
 *    version of that information.
 *
 * 2. **The book.** Every market this desk can be pointed at, as a checkbox
 *    tree: crypto, forex (all the majors and crosses), indices, stocks,
 *    futures, options, metals. Ticking a symbol puts it in the scanner's
 *    universe; unticking it takes it out. Asset classes with no free keyless
 *    feed say so on the label rather than pretending, and are traded on the
 *    internal simulator when selected.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

interface RosterEntry {
  key: string;
  name: string;
  title: string;
  role: string;
  is_ceo: boolean;
  model: string;
  backend: string;
  /** why the backend is what it is — "mock personas, no weights loaded" on a CPU box */
  note?: string;
  temperature: number;
  expertise: string[];
  style: string;
  key_required: boolean;
  auth: string;
  license: string;
  /** path to this desk's LoRA adapter, when the trainer has produced one */
  adapter?: string | null;
}

interface SymbolEntry {
  symbol: string;
  name: string;
  /** what the instrument is wired for */
  kind: string;
  /** what the desk is actually reading right now (falls back to kind) */
  live?: string;
  venue?: string | null;
  rate?: string | null;
}

const badgeOf = (s: SymbolEntry) => SOURCE_BADGE[s.live ?? s.kind] ?? s.live ?? s.kind;

interface ClassEntry {
  key: string;
  label: string;
  source: string;
  instrument: string;
  count: number;
  symbols: SymbolEntry[];
}

export interface BrokerView {
  mode: string;
  venue: "mt5" | "paper";
  connected: boolean;
  ready: boolean;
  creds?: { login?: string; server?: string; path?: string; mode?: string; has_password?: boolean;
            password?: string };
  account?: { login?: string; server?: string; currency?: string; balance?: number; equity?: number;
              margin_free?: number; leverage?: number; demo?: boolean; company?: string };
  routing?: Record<string, { label: string; venue: string; detail: string }>;
  autotrade?: { on: boolean; classes: string[]; risk_pct: number; max_open: number;
                min_confidence: number; placed: number; skipped: number; last: string };
  stats?: { orders_total: number; open: number; closed: number; realised: number };
  terminal?: { note?: string; error?: string; symbols_known?: number };
  note?: string;
}

export interface SettingsPayload {
  roster: RosterEntry[];
  instruments: { classes: ClassEntry[]; default: string[]; total: number };
  selected: string[];
  engine: { llm_mode: string; model_profile: string; market_mode: string; desks: number };
  training?: {
    rows: number; settled_rows: number; curriculum_rows: number; lesson_rows: number;
    waiting: number; adapters_dir: string; trained_now: boolean;
    desks: Record<string, { rows: number; settled: number; adapter: string | null }>;
  };
}

const SOURCE_BADGE: Record<string, string> = {
  venue: "live venue feed",
  rates: "reference rates",
  sim: "simulated",
};

export function SettingsPanel({
  open,
  onClose,
  onApplied,
}: {
  open: boolean;
  onClose: () => void;
  onApplied: (symbols: string[]) => void;
}) {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<"roster" | "book" | "broker">("roster");
  const [broker, setBroker] = useState<BrokerView | null>(null);
  const [form, setForm] = useState({ login: "", password: "", server: "", mode: "auto", path: "" });
  const [brokerMsg, setBrokerMsg] = useState<string | null>(null);
  const [brokerBusy, setBrokerBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [q, setQ] = useState("");
  const [onlyTicked, setOnlyTicked] = useState(false);

  const load = () => {
    fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: SettingsPayload) => {
        setData(j);
        setTicked(new Set(j.selected ?? []));
        setDirty(false);
        setErr(null);
      })
      .catch((e) => setErr(`could not load settings (${e.message})`));
  };

  useEffect(() => {
    if (open && !data) load();
  }, [open, data]);

  const toggle = (symbol: string) => {
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
    setDirty(true);
  };

  const toggleClass = (cls: ClassEntry, on: boolean) => {
    setTicked((prev) => {
      const next = new Set(prev);
      for (const s of cls.symbols) {
        if (on) next.add(s.symbol);
        else next.delete(s.symbol);
      }
      return next;
    });
    setDirty(true);
  };

  const apply = async () => {
    setBusy(true);
    try {
      const res = await fetch("/api/settings/instruments", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ symbols: [...ticked] }),
      });
      const j = await res.json();
      if (j?.selected) {
        setTicked(new Set(j.selected));
        onApplied(j.selected);
        setDirty(false);
      }
    } catch (e) {
      setErr(`apply failed (${(e as Error).message})`);
    } finally {
      setBusy(false);
    }
  };

  /** Read the venue back, and pre-fill what we already know (never the password). */
  const loadBroker = useCallback(async () => {
    try {
      const j = (await (await fetch("/api/broker")).json()) as BrokerView;
      setBroker(j);
      setForm((f) => ({
        ...f,
        login: f.login || j.creds?.login || "",
        server: f.server || j.creds?.server || "",
        mode: j.creds?.mode || j.mode || "auto",
      }));
    } catch {
      /* the panel still works offline: it just cannot report the venue */
    }
  }, []);

  useEffect(() => {
    if (open) void loadBroker();
  }, [open, loadBroker]);

  const connectBroker = async (forget = false) => {
    setBrokerBusy(true);
    setBrokerMsg(null);
    try {
      const res = await fetch(forget ? "/api/broker/disconnect" : "/api/broker/connect", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(forget
          ? { forget: true }
          : { login: form.login.trim(), password: form.password, server: form.server.trim(), mode: form.mode }),
      });
      const j = (await res.json()) as BrokerView;
      setBroker(j);
      if (forget) {
        setForm({ login: "", password: "", server: "", mode: "auto", path: "" });
        setBrokerMsg("login forgotten — nothing is stored on this machine");
      } else if (j.connected) {
        setBrokerMsg(`connected to ${j.creds?.server ?? "the terminal"} as ${j.account?.login ?? form.login}`);
        setForm((f) => ({ ...f, password: "" }));
      } else {
        setBrokerMsg(j.terminal?.error
          ? `the terminal did not answer: ${j.terminal.error}`
          : "login not accepted");
      }
    } catch (e) {
      setBrokerMsg(`connect failed (${(e as Error).message})`);
    } finally {
      setBrokerBusy(false);
    }
  };

  const roster = data?.roster ?? [];
  const tr = data?.training;
  const cabins = useMemo(() => roster.filter((r) => !r.is_ceo), [roster]);
  const ceo = roster.find((r) => r.is_ceo);

  if (!open) return null;

  return (
    <div className="drawer settings" role="dialog" aria-label="Desk settings">
      <header className="drawer-head">
        <div>
          <h2>Desk settings</h2>
          <p className="muted">
            {data
              ? `${data.engine.llm_mode === "mock" ? "mock personas" : "local models"} · ` +
                `${data.engine.market_mode === "live" ? "live venue" : "simulated venue"} · ` +
                `${data.engine.desks} desks`
              : "loading…"}
          </p>
        </div>
        <button className="ghost" onClick={onClose} aria-label="Close settings">
          ✕
        </button>
      </header>

      <nav className="tabs">
        <button className={tab === "roster" ? "tab on" : "tab"} onClick={() => setTab("roster")}>
          The desk <span className="pill">{roster.length}</span>
        </button>
        <button className={tab === "book" ? "tab on" : "tab"} onClick={() => setTab("book")}>
          Markets <span className="pill">{ticked.size}</span>
        </button>
        <button className={tab === "broker" ? "tab on" : "tab"} onClick={() => setTab("broker")}>
          Broker{" "}
          <span className={`pill ${broker?.connected ? "ok" : ""}`}>
            {broker?.connected ? "MT5" : "paper"}
          </span>
        </button>
      </nav>

      {err && <div className="warn">{err}</div>}

      {tab === "roster" && (
        <div className="scroll">
          <div className="note">
            <strong>No API keys — by design.</strong> Every model below is open
            weights, downloaded ungated and run locally (4-bit on a GPU, or on
            Kaggle&apos;s free tier). Nothing in this system calls a hosted
            endpoint, so there is no key to show, paste or leak. Gated
            repositories (Llama, Gemma) are deliberately not used.
          </div>

          {tr && (
            <div className="note training">
              <strong>
                Training set: {tr.rows.toLocaleString()} rows
                {tr.settled_rows > 0 ? ` · ${tr.settled_rows.toLocaleString()} settled decisions` : ""}
              </strong>{" "}
              The house curriculum ({tr.curriculum_rows} rows), the rules the debate room
              agreed ({tr.lesson_rows} rows), and every trade whose outcome is known — the
              packet the desk saw, the verdict it gave, and what it was worth.{" "}
              {tr.trained_now
                ? `Adapters trained: ${Object.values(tr.desks).filter((d) => d.adapter).length}/6.`
                : `Adapters: none yet — run \`python -m soul.train\` on a GPU box (Kaggle 2×T4); they load from ${tr.adapters_dir} when the floor restarts.`}
            </div>
          )}

          {ceo && (
            <div className="roster-card ceo">
              <div className="roster-top">
                <span className="who">
                  <b>{ceo.name}</b>
                  <i>{ceo.title}</i>
                </span>
                <span className="slot">HEAD OF DESK</span>
              </div>
              <div className="roster-meta">
                <span className="mono">{ceo.model}</span>
                <span className="badge" title={ceo.note || undefined}>{ceo.backend}</span>
                <span className="badge">T={ceo.temperature}</span>
                <span className="badge ok">no key</span>
              </div>
              <div className="roster-auth">{ceo.auth} · {ceo.license}</div>
              {tr?.desks?.[ceo.key] && (
                <div className="roster-train">
                  {tr.desks[ceo.key].settled > 0
                    ? `${tr.desks[ceo.key].settled} settled decisions in the training set`
                    : "no settled decisions yet — curriculum + room rules only"}
                  {tr.desks[ceo.key].adapter ? " · adapter trained" : " · adapter: none yet"}
                </div>
              )}
              <p className="style">{ceo.style}</p>
            </div>
          )}

          {cabins.map((r, i) => (
            <div className="roster-card" key={r.key}>
              <div className="roster-top">
                <span className="who">
                  <b>{r.name}</b>
                  <i>{r.title}</i>
                </span>
                <span className="slot">CABIN {i + 1}</span>
              </div>
              <div className="roster-meta">
                <span className="mono">{r.model}</span>
                <span className="badge" title={r.note || undefined}>{r.backend}</span>
                <span className="badge">T={r.temperature}</span>
                <span className="badge ok">ungated</span>
              </div>
              <div className="roster-auth">{r.auth} · {r.license}</div>
              {tr?.desks?.[r.key] && (
                <div className="roster-train">
                  {tr.desks[r.key].settled > 0
                    ? `${tr.desks[r.key].settled} settled decisions in the training set`
                    : "no settled decisions yet — curriculum + room rules only"}
                  {tr.desks[r.key].adapter ? " · adapter trained" : " · adapter: none yet"}
                </div>
              )}
              <p className="style">{r.style}</p>
              <ul className="expertise">
                {r.expertise.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
          ))}

          <div className="note small">
            Roster stage order: each cabin sees the trade plus every earlier
            cabin&apos;s verdict, and the head of desk sees all five plus the
            transcript. Swapping a model id here is a one-line change in
            <code> soul/brains/base.py</code>.
          </div>
        </div>
      )}

      {tab === "broker" && (
        <div className="scroll">
          <div className="note">
            <strong>Where a placed trade goes.</strong> Forex and metals are routed to
            your MetaTrader 5 terminal; every other class waits for a broker to be
            named and runs on the paper venue until then. The login below is stored in
            <code> {broker ? "artifacts/broker/mt5.json" : "artifacts/broker/mt5.json"}</code>{" "}
            on this machine only — never in the repository, never in a page, and the
            password is never sent back to the browser or written to a log.
          </div>

          <div className={`broker-card ${broker?.connected ? "live" : "paper"}`}>
            <div className="broker-top">
              <span className="who">
                <b>{broker?.connected ? "MetaTrader 5 connected" : "Paper venue"}</b>
                <i>{broker?.connected
                  ? `${broker?.account?.company || "terminal"} · ${broker?.account?.server ?? ""}`
                  : "orders are filled off the floor's own feed"}</i>
              </span>
              <span className="slot">{broker?.connected ? "LIVE PATH" : "OFFLINE"}</span>
            </div>
            <div className="roster-meta">
              <span className="badge">login {broker?.creds?.login || "—"}</span>
              <span className="badge">server {broker?.creds?.server || "—"}</span>
              <span className="badge">{broker?.account?.currency ?? "USD"}</span>
              {broker?.account?.balance != null && (
                <span className="badge">
                  balance {broker.account.balance.toLocaleString()} · equity{" "}
                  {broker.account.equity?.toLocaleString()}
                </span>
              )}
              <span className="badge">{broker?.creds?.password || "no password stored"}</span>
            </div>
            {broker?.terminal?.note && <div className="roster-auth">{broker.terminal.note}</div>}
            {broker?.terminal?.error && <div className="warn">{broker.terminal.error}</div>}
          </div>

          <div className="broker-form">
            <label>
              MT5 login
              <input value={form.login} placeholder="112594843" inputMode="numeric"
                     onChange={(e) => setForm({ ...form, login: e.target.value })} />
            </label>
            <label>
              Password
              <input type="password" value={form.password} placeholder="••••••••"
                     autoComplete="new-password"
                     onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
            <label>
              Server
              <input value={form.server} placeholder="MetaQuotes-Demo"
                     onChange={(e) => setForm({ ...form, server: e.target.value })} />
            </label>
            <label>
              Venue mode
              <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
                <option value="auto">auto — terminal when it answers, paper otherwise</option>
                <option value="mt5">mt5 — pinned: refuse rather than fall back to paper</option>
                <option value="paper">paper — never touch the terminal</option>
              </select>
            </label>
            <div className="broker-actions">
              <button className="primary" disabled={brokerBusy || (!form.login && !form.server)}
                      onClick={() => connectBroker(false)}>
                {brokerBusy ? "connecting…" : "Connect terminal"}
              </button>
              <button className="ghost" onClick={() => connectBroker(true)}>Forget login</button>
            </div>
            {brokerMsg && <div className="note small">{brokerMsg}</div>}
            <div className="note small">
              A password typed here is used for one connection attempt and stored only if
              it works. Two-factor prompts, investor passwords and prop-firm servers are
              yours to handle in the terminal; this panel only sends orders.
            </div>
          </div>

          {broker?.routing && (
            <>
              <h4 className="broker-h">Routing by asset class</h4>
              <table className="broker-table">
                <thead>
                  <tr><th>class</th><th>venue</th><th>detail</th></tr>
                </thead>
                <tbody>
                  {Object.entries(broker.routing).map(([key, meta]) => (
                    <tr key={key}>
                      <td>{meta.label}</td>
                      <td><span className={`venue-tiny ${meta.venue}`}>{meta.venue.toUpperCase()}</span></td>
                      <td className="muted">{meta.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {broker && (
            <div className="note small">
              Auto-trade is {broker.autotrade?.on ? "ARMED" : "disarmed"} for{" "}
              {(broker.autotrade?.classes ?? []).join(", ") || "nothing"} at{" "}
              {broker.autotrade?.risk_pct}% risk per order. Places: {broker.autotrade?.placed ?? 0} ·
              skipped: {broker.autotrade?.skipped ?? 0}
              {broker.autotrade?.last ? ` · last: ${broker.autotrade.last}` : ""}. Arm it from the
              Execution panel; disarmed, every order is your click.
            </div>
          )}
        </div>
      )}

      {tab === "book" && (
        <div className="scroll">
          <div className="note">
            Ticked instruments become the scanner&apos;s universe. The fly scout
            only hunts inside this book, and every trade on the floor carries one
            of these symbols. Screen <b>Forex</b> and every pair is a checkbox —
            or type a symbol to find one.
          </div>

          <div className="book-tools">
            <input
              className="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Find a symbol (EUR, INR, NVDA…)"
              aria-label="Filter instruments"
            />
            <label className="check sym">
              <input type="checkbox" checked={onlyTicked}
                     onChange={(e) => setOnlyTicked(e.target.checked)} />
              <span>only ticked</span>
            </label>
            <span className="muted small">{ticked.size} / {data?.instruments.total ?? 0}</span>
          </div>

          {(data?.instruments.classes ?? []).map((cls) => {
            const needle = q.trim().toUpperCase();
            const shown = cls.symbols.filter((s) =>
              (!needle || s.symbol.toUpperCase().includes(needle) || s.name.toUpperCase().includes(needle))
              && (!onlyTicked || ticked.has(s.symbol)));
            if (shown.length === 0) return null;
            const all = cls.symbols.every((s) => ticked.has(s.symbol));
            const some = cls.symbols.some((s) => ticked.has(s.symbol));
            return (
              <section className="book-class" key={cls.key}>
                <div className="book-head">
                  <label className="check strong">
                    <input
                      type="checkbox"
                      checked={all}
                      ref={(el) => {
                        if (el) el.indeterminate = !all && some;
                      }}
                      onChange={(e) => toggleClass(cls, e.target.checked)}
                    />
                    <span>{cls.label}</span>
                  </label>
                  <span className="muted small">
                    {cls.symbols.filter((s) => ticked.has(s.symbol)).length}/{cls.count} ticked ·{" "}
                    {cls.instrument} · {cls.source}
                  </span>
                </div>
                <div className="book-grid">
                  {shown.map((s) => (
                    <label className="check sym" key={s.symbol} title={`${s.name} - ${badgeOf(s)}`}>
                      <input
                        type="checkbox"
                        checked={ticked.has(s.symbol)}
                        onChange={() => toggle(s.symbol)}
                      />
                      <span className="mono">{s.symbol}</span>
                      <em>{badgeOf(s)}</em>
                    </label>
                  ))}
                </div>
              </section>
            );
          })}
          {q.trim() && !(data?.instruments.classes ?? []).some((c) =>
            c.symbols.some((s) => s.symbol.toUpperCase().includes(q.trim().toUpperCase()))) && (
            <div className="warn">no instrument matches “{q.trim()}” on this desk</div>
          )}
        </div>
      )}

      <footer className="drawer-foot">
        <button className="ghost" onClick={load} disabled={busy}>
          Reload
        </button>
        <span className="muted small">
          {dirty ? "unsaved changes" : "in sync with the desk"}
        </span>
        <button className="primary" onClick={apply} disabled={busy || !dirty}>
          {busy ? "applying…" : `Trade ${ticked.size} instruments`}
        </button>
      </footer>
    </div>
  );
}

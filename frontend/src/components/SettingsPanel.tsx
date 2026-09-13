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
import { useEffect, useMemo, useState } from "react";

interface RosterEntry {
  key: string;
  name: string;
  title: string;
  role: string;
  is_ceo: boolean;
  model: string;
  backend: string;
  temperature: number;
  expertise: string[];
  style: string;
  key_required: boolean;
  auth: string;
  license: string;
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

interface SettingsPayload {
  roster: RosterEntry[];
  instruments: { classes: ClassEntry[]; default: string[]; total: number };
  selected: string[];
  engine: { llm_mode: string; model_profile: string; market_mode: string; desks: number };
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
  const [tab, setTab] = useState<"roster" | "book">("roster");
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

  const roster = data?.roster ?? [];
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
                <span className="badge">{ceo.backend}</span>
                <span className="badge">T={ceo.temperature}</span>
                <span className="badge ok">no key</span>
              </div>
              <div className="roster-auth">{ceo.auth} · {ceo.license}</div>
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
                <span className="badge">{r.backend}</span>
                <span className="badge">T={r.temperature}</span>
                <span className="badge ok">ungated</span>
              </div>
              <div className="roster-auth">{r.auth} · {r.license}</div>
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

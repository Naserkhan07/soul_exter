/**
 * The debate room — the chat room where the cabins talk to each other.
 *
 * The cabins vote; this is where they *talk*. Every round has a topic, a claim
 * from one desk, a challenge, a question, an answer, an acknowledgement and a
 * lesson from the head of desk — and the lesson is written into desk memory,
 * which is read back into the prompt for every following trade. So the panel is
 * not a log of chatter: it is the training channel, and the rules at the bottom
 * are the ones the desk will judge the next trade against.
 *
 * Two shapes, one room:
 *   - `rail`   the compact panel in the left rail, always on screen;
 *   - `room`   the full chat room, opened from the top bar, with the composer
 *              that lets the user ask any desk a question and watch the answer
 *              land in the same transcript.
 *
 * The training is visible in here, not just counted: a desk that opens a round
 * names the rule it was taught (↺), the head of desk writes the new rule (★),
 * two desks say how they will carry it (↺ carried), and a closed position is
 * reviewed out loud by a desk that was on the wrong side of it (▲). The
 * "training turns" filter shows only those, which is the answer to "are they
 * actually learning, or just talking?"
 *
 * Turns stream in over the bus as they are spoken (`debate_message`), so the
 * transcript is live; the REST endpoint fills the history on load.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { DebateTurn } from "../state/useSoul";

const TURN_STYLE: Record<string, { icon: string; label: string; cls: string }> = {
  round: { icon: "◎", label: "topic", cls: "round" },
  claim: { icon: "◆", label: "claims", cls: "claim" },
  challenge: { icon: "⚔", label: "challenges", cls: "challenge" },
  question: { icon: "?", label: "asks", cls: "question" },
  answer: { icon: "→", label: "answers", cls: "answer" },
  ack: { icon: "✓", label: "agrees", cls: "ack" },
  lesson: { icon: "★", label: "writes the rule", cls: "lesson" },
  carry: { icon: "↺", label: "carries the rule", cls: "carry" },
  postmortem: { icon: "▲", label: "after the close", cls: "postmortem" },
  you: { icon: "✎", label: "asks", cls: "you" },
};

/** What the scoreboard knows about one desk: its settled calls and its R. */
export interface DeskRecord {
  calls: number;
  right: number;
  hit_rate: number | null;
  r_sum: number;
  proven: boolean;
  weight?: number;
}

export interface Speaker {
  key: string;
  name: string;
  title: string;
}

export function DebateRoomPanel({
  transcript,
  lessons,
  speakers,
  rounds,
  topic,
  onConvene,
  onAsk,
  records,
  thinking,
  training,
  heard,
  heardTotals,
  roomName,
  tagline,
  hours24,
  variant = "rail",
  onClose,
  onOpenRoom,
}: {
  transcript: DebateTurn[];
  lessons: Array<{ topic: string; speaker_label: string; text: string; round: number }>;
  speakers: Speaker[];
  rounds: number;
  topic?: string | null;
  onConvene: () => void;
  /** ask one desk a question; its answer arrives in the same transcript */
  onAsk?: (cabin: string, question: string) => void | Promise<void>;
  records?: Partial<Record<string, DeskRecord>>;
  /** the desk currently composing a turn, if any */
  thinking?: { key: string; name: string } | null;
  /** rules heard off another desk, newest last — training by listening */
  heard?: Array<{ listener: string; name: string; speaker_name: string; rule: string; round: number }>;
  /** how many rules each desk has heard written */
  heardTotals?: Record<string, number>;
  /** the room's name, straight from the engine */
  roomName?: string;
  tagline?: string;
  /** what the desks have been trained on, straight from the engine */
  training?: {
    rows: number; settled_rows: number; curriculum_rows: number; lesson_rows: number;
    adapters?: Record<string, string>; trained_now?: boolean;
  } | null;
  hours24?: boolean;
  variant?: "rail" | "room";
  onClose?: () => void;
  /** the rail panel's shortcut into the full room */
  onOpenRoom?: () => void;
}) {
  const feedRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);
  const [draft, setDraft] = useState("");
  const [to, setTo] = useState("");
  // the room can be read as an argument or as a training log; both are real,
  // and which one is useful depends on why you opened it
  const [onlyTraining, setOnlyTraining] = useState(false);

  const nameOf = useMemo(() => {
    const map = new Map(speakers.map((s) => [s.key, s.name]));
    return (key?: string | null) => (key ? map.get(key) ?? key : "");
  }, [speakers]);

  const turns = useMemo(() => {
    const window = transcript.slice(-80);
    if (!onlyTraining) return window;
    return window.filter((m) => m.training || m.turn === "round" || m.turn === "you");
  }, [transcript, onlyTraining]);

  const trainingCount = useMemo(
    () => transcript.slice(-80).filter((m) => m.training).length,
    [transcript],
  );

  useEffect(() => {
    if (!to && speakers.length) setTo(speakers[0].key);
  }, [speakers, to]);

  useEffect(() => {
    const el = feedRef.current;
    if (el && pinned) el.scrollTop = el.scrollHeight;
  }, [turns.length, pinned, thinking?.key]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || !to || !onAsk) return;
    setDraft("");
    void onAsk(to, text);
  };

  const room = variant === "room";
  const last = turns.length ? turns[turns.length - 1] : null;

  return (
    <section className={`panel debate${room ? " room" : ""}`}>
      <header className="panel-head">
        <h3>
          {roomName ?? "The chat room"} <span className="pill">{rounds} rounds</span>
        </h3>
        <div className="head-actions">
          <button className="ghost tiny" onClick={() => setPinned((p) => !p)}>
            {pinned ? "following" : "paused"}
          </button>
          <button
            className={onlyTraining ? "ghost tiny on" : "ghost tiny"}
            onClick={() => setOnlyTraining((v) => !v)}
            title="show only the turns where the desks are being trained: rules recalled, written and carried, and closed trades reviewed"
          >
            {onlyTraining ? "training only" : "training turns"}
            {trainingCount > 0 && <span className="pill">{trainingCount}</span>}
          </button>
          <button className="ghost tiny" onClick={onConvene}>
            convene round
          </button>
          {!room && onOpenRoom && (
            <button className="ghost tiny open-room" onClick={onOpenRoom} title="open the room">
              open
            </button>
          )}
          {room && onClose && (
            <button className="ghost tiny" onClick={onClose}>
              close
            </button>
          )}
        </div>
      </header>

      {room && (
        <p className="room-intro">
          {tagline ? <b className="tagline">{tagline}. </b> : null}
          Six desks in one room: they claim, challenge, ask, answer, agree — and then they
          teach each other. A desk opens a round by naming the rule on file that bears on it
          (<b>↺</b> recalled), the head of desk writes the round&apos;s rule (<b>★</b>),
          two desks say how they will trade it (<b>↺</b> carried), and when a position closes
          a desk that was on the wrong side of it says what it learned (<b>▲</b> after the
          close). Every one of those turns goes into that desk&apos;s training set — press{" "}
          <b>training turns</b> to read only that channel.
        </p>
      )}

      <div className="speakers">
        {speakers.map((s) => {
          const rec = records?.[s.key];
          const record = rec && rec.proven
            ? `${rec.right}/${rec.calls} right · ${rec.r_sum >= 0 ? "+" : ""}${rec.r_sum.toFixed(1)}R`
            : rec
              ? `${rec.calls} settled · not proven`
              : "";
          const learned = heardTotals?.[s.key];
          return (
            <span className="speaker-chip" key={s.key} title={s.title}>
              <b>{s.name}</b>
              <em>{s.title}</em>
              {record && <i className="speaker-record">{record}</i>}
              {learned ? (
                <i className="speaker-learned" title="rules this desk has heard another desk write">
                  ↺ {learned} heard
                </i>
              ) : null}
            </span>
          );
        })}
        {!speakers.length && <span className="muted small">waiting for the desk…</span>}
      </div>

      <div className="feed" ref={feedRef}>
        {!turns.length && (
          <p className="muted small">
            The room is quiet. The next review meeting opens after the council
            closes its current trade — or press <b>convene round</b>.
          </p>
        )}
        {turns.map((m, i) => {
          const st = TURN_STYLE[m.turn] ?? TURN_STYLE.claim;
          if (m.turn === "round") {
            return (
              <div className="round-line" key={`${m.ts}-${i}`}>
                <span className="round-tag">round {m.round}</span>
                <span>{m.text}</span>
              </div>
            );
          }
          if (m.turn === "you") {
            return (
              <article className="turn you" key={`${m.ts}-${i}`}>
                <div className="turn-head">
                  <span className="turn-icon">{st.icon}</span>
                  <b>you</b>
                  <span className="turn-to">→ {nameOf(m.speaker)}</span>
                  <em>asks</em>
                </div>
                <p>{m.text}</p>
              </article>
            );
          }
          return (
            <article className={`turn ${st.cls}${m.training ? " training" : ""}`} key={`${m.ts}-${i}`}>
              <div className="turn-head">
                <span className="turn-icon">{st.icon}</span>
                <b>{m.name}</b>
                {m.to_name && <span className="turn-to">→ {m.to_name}</span>}
                <em>{st.label}</em>
                <span className="turn-model mono">{m.model}</span>
                {hours24 && <time>{fmtTime(m.ts)}</time>}
              </div>
              {m.rule && (
                <p className="rule-chip" title={m.rule}>
                  <span>rule</span> {m.rule}
                  {m.rule_from && (
                    <em className="rule-from">
                      {m.turn === "carry" ? "taught by" : "on file from"} {m.rule_from}
                      {m.rule_round ? ` · round ${m.rule_round}` : ""}
                    </em>
                  )}
                </p>
              )}
              <p>{m.text}</p>
            </article>
          );
        })}
        {thinking && (
          <div className="thinking-line">
            <span className="dot" />
            <b>{thinking.name}</b> is thinking…
          </div>
        )}
        {last && (
          <div className="listening-line">
            <span className="listening-tag">listening</span>
            {speakers
              .filter((sp) => sp.key !== last.speaker)
              .map((sp) => (
                <span
                  key={sp.key}
                  className={`listener${sp.key === last.to ? " addressed" : ""}`}
                  title={sp.key === last.to ? `${last.name} is answering ${sp.name}` : sp.name}
                >
                  {sp.name.split(" ").slice(-1)[0]}
                </span>
              ))}
          </div>
        )}
        {heard && heard.length > 0 && (
          <div className="heard-line">
            <span className="heard-tag">learned</span>
            <b>{heard[heard.length - 1].name}</b> heard{" "}
            <b>{heard[heard.length - 1].speaker_name}</b>&apos;s rule
            <i className="mono">{heard[heard.length - 1].rule.slice(0, 70)}</i>
          </div>
        )}
      </div>

      {onAsk && (
        <form className="composer" onSubmit={submit}>
          <select
            className="composer-to"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            title="which desk to ask"
          >
            {speakers.map((s) => (
              <option value={s.key} key={s.key}>
                {s.name}
              </option>
            ))}
          </select>
          <input
            className="composer-text"
            placeholder="ask the room — why did you take that trade, and what would change your mind?"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={() => setPinned(true)}
          />
          <button className="ghost tiny send" type="submit" disabled={!draft.trim()}>
            send
          </button>
        </form>
      )}

      <div className="lessons">
        <h4>
          Rules this desk has agreed <span className="pill">{lessons.length}</span>
        </h4>
        {!lessons.length && (
          <p className="muted small">
            Nothing on file yet. The first round writes one, and every following
            verdict is argued against it.
          </p>
        )}
        <ul>
          {lessons
            .slice(-(room ? 8 : 4))
            .reverse()
            .map((l, i) => (
              <li key={`${l.round}-${i}`}>
                <span className="mono">R{l.round}</span> {l.text}
                <em> — {l.speaker_label}</em>
              </li>
            ))}
        </ul>
      </div>
      {training && (
        <p className="muted small training-line">
          trained on <b>{training.rows.toLocaleString()}</b> rows —{" "}
          {training.curriculum_rows.toLocaleString()} curriculum ·{" "}
          {training.lesson_rows.toLocaleString()} from the room ·{" "}
          <b>{training.settled_rows.toLocaleString()}</b> settled decisions
          {training.trained_now
            ? ` · adapters: ${Object.keys(training.adapters ?? {}).length}/6 desks`
            : " · adapters: none trained yet"}
        </p>
      )}
      {topic && <p className="muted small topic-line">current topic: {topic}</p>}
    </section>
  );
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

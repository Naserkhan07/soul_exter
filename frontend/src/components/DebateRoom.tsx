/**
 * The debate room.
 *
 * The cabins vote; this is where they *talk*. Every round has a topic, a claim
 * from one desk, a challenge, a question, an answer, an acknowledgement and a
 * lesson from the head of desk — and the lesson is written into desk memory,
 * which is read back into the prompt for every following trade. So the panel is
 * not a log of chatter: it is the training channel, and the rules at the bottom
 * are the ones the desk will judge the next trade against.
 *
 * Turns stream in over the bus as they are spoken (`debate_message`), so the
 * transcript is live; the REST endpoint fills the history on load.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { DebateTurn } from "../state/useSoul";

const TURN_STYLE: Record<string, { icon: string; label: string; cls: string }> = {
  round: { icon: "◎", label: "topic", cls: "round" },
  claim: { icon: "◆", label: "claims", cls: "claim" },
  challenge: { icon: "⚔", label: "challenges", cls: "challenge" },
  question: { icon: "?", label: "asks", cls: "question" },
  answer: { icon: "→", label: "answers", cls: "answer" },
  ack: { icon: "✓", label: "agrees", cls: "ack" },
  lesson: { icon: "★", label: "writes the rule", cls: "lesson" },
};

export function DebateRoomPanel({
  transcript,
  lessons,
  speakers,
  rounds,
  topic,
  onConvene,
  hours24,
}: {
  transcript: DebateTurn[];
  lessons: Array<{ topic: string; speaker_label: string; text: string; round: number }>;
  speakers: Array<{ key: string; name: string; title: string }>;
  rounds: number;
  topic?: string | null;
  onConvene: () => void;
  hours24?: boolean;
}) {
  const feedRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);

  // newest first for reading, but the auto-scroll follows the newest turn
  const turns = useMemo(() => transcript.slice(-60), [transcript]);

  useEffect(() => {
    const el = feedRef.current;
    if (el && pinned) el.scrollTop = el.scrollHeight;
  }, [turns.length, pinned]);

  return (
    <section className="panel debate">
      <header className="panel-head">
        <h3>
          Debate room <span className="pill">{rounds} rounds</span>
        </h3>
        <div className="head-actions">
          <button className="ghost tiny" onClick={() => setPinned((p) => !p)}>
            {pinned ? "following" : "paused"}
          </button>
          <button className="ghost tiny" onClick={onConvene}>
            convene
          </button>
        </div>
      </header>

      <div className="speakers">
        {speakers.map((s) => (
          <span className="speaker-chip" key={s.key} title={s.title}>
            <b>{s.name}</b>
            <em>{s.title}</em>
          </span>
        ))}
        {!speakers.length && <span className="muted small">waiting for the desk…</span>}
      </div>

      <div className="feed" ref={feedRef}>
        {!turns.length && (
          <p className="muted small">
            The room is quiet. The next review meeting opens after the council
            closes its current trade.
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
          return (
            <article className={`turn ${st.cls}`} key={`${m.ts}-${i}`}>
              <div className="turn-head">
                <span className="turn-icon">{st.icon}</span>
                <b>{m.name}</b>
                <em>{st.label}</em>
                <span className="turn-model mono">{m.model}</span>
                {hours24 && <time>{fmtTime(m.ts)}</time>}
              </div>
              <p>{m.text}</p>
            </article>
          );
        })}
      </div>

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
            .slice(-4)
            .reverse()
            .map((l, i) => (
              <li key={`${l.round}-${i}`}>
                <span className="mono">R{l.round}</span> {l.text}
                <em> — {l.speaker_label}</em>
              </li>
            ))}
        </ul>
      </div>
      {topic && <p className="muted small topic-line">current topic: {topic}</p>}
    </section>
  );
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

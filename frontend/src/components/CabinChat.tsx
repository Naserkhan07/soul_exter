/**
 * One desk's chat.
 *
 * The card above a cabin says what that desk thinks of the trade in front of it.
 * This is what happens when you click it: the full argument, in that desk's own
 * words — the verdict and why, every turn it has taken in the debate room, and a
 * box to ask it something directly. The question goes to the same brain that
 * votes on trades, so the answer is the desk's real reasoning, not a canned
 * blurb: `/api/debate/ask` hands the trade's numbers to the model and publishes
 * whatever it says back onto the floor, where the card picks it up.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Cabin } from "../floor/types";
import type { DebateTurn } from "../state/useSoul";

const TURN_LABEL: Record<string, string> = {
  claim: "opens",
  challenge: "challenges",
  question: "asks",
  answer: "answers",
  ack: "agrees",
  lesson: "writes the rule",
  verdict: "votes",
  you: "you",
};

const TURN_TONE: Record<string, string> = {
  claim: "spoke",
  challenge: "hard",
  question: "ask",
  answer: "spoke",
  ack: "soft",
  lesson: "rule",
  verdict: "vote",
  you: "you",
};

function clock(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function CabinChat({
  cabin,
  turns,
  question,
  onAsk,
  onClose,
}: {
  cabin: Cabin;
  turns: DebateTurn[];
  question: string;
  onAsk: (key: string, question: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const feedRef = useRef<HTMLDivElement | null>(null);

  const mine = useMemo(
    () => turns.filter((t) => t.speaker === cabin.key).slice(-40),
    [turns, cabin.key],
  );

  // keep the newest turn in view — it is a chat, after all
  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [mine.length, cabin.thinking, cabin.said]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    setDraft("");
    try {
      await onAsk(cabin.key, text);
    } finally {
      setBusy(false);
    }
  };

  const vote = cabin.lastVote;
  return (
    <div className="drawer chat" role="dialog" aria-label={`${cabin.name ?? cabin.key} chat`}>
      <header className="drawer-head chat-head">
        <div className="chat-who">
          <span className={`dot ${cabin.thinking ? "on" : ""}`} />
          <div>
            <h2>{cabin.name ?? cabin.label}</h2>
            <p className="muted small">
              {cabin.title ?? cabin.role ?? cabin.label}
              {cabin.model ? ` · \u200b${cabin.model}` : ""}
            </p>
          </div>
        </div>
        <div className="chat-head-right">
          {vote ? (
            <span className={`verdict v-${vote.toLowerCase()}`}>
              {vote}
              {cabin.confidence !== undefined ? ` ${Math.round(cabin.confidence)}%` : ""}
            </span>
          ) : (
            <span className="verdict v-idle">no vote yet</span>
          )}
          <button className="ghost" onClick={onClose} aria-label="Close chat">
            ✕
          </button>
        </div>
      </header>

      {cabin.expertise?.length ? (
        <div className="chat-expertise">
          {cabin.expertise.map((e) => (
            <span className="tag" key={e}>
              {e}
            </span>
          ))}
        </div>
      ) : null}

      <div className="chat-why">
        <h3>{question ? "This trade" : "The floor"}</h3>
        {question ? (
          <p className="q">{question}</p>
        ) : (
          <p className="q">waiting for the next trade to reach this cabin</p>
        )}
        <p className="why">
          {cabin.reason?.trim()
            || (cabin.thinking ? "reading the tape…" : "has not been asked to vote yet")}
        </p>
      </div>

      <div className="chat-feed" ref={feedRef}>
        {mine.length === 0 && !cabin.thinking && (
          <p className="muted small chat-empty">
            No turns yet. Ask this desk something and it will answer in the room — the
            same model that votes here answers you.
          </p>
        )}
        {mine.map((t, i) => (
          <div className={`bubble ${TURN_TONE[t.turn] ?? "spoke"}`} key={`${t.ts}-${i}`}>
            <div className="bubble-top">
              <span className="turn">{TURN_LABEL[t.turn] ?? t.turn}</span>
              <span className="muted small">{clock(t.ts)}</span>
            </div>
            <p>{t.text}</p>
            {t.topic && t.turn !== "answer" ? <em className="topic">{t.topic}</em> : null}
          </div>
        ))}
        {cabin.thinking && (
          <div className="bubble thinking">
            <div className="bubble-top">
              <span className="turn">thinking</span>
            </div>
            <p className="dots">
              <i />
              <i />
              <i />
            </p>
          </div>
        )}
      </div>

      <footer className="chat-ask">
        <input
          value={draft}
          placeholder={`ask ${(cabin.name ?? cabin.key).split(" ")[0]} why…`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
          }}
          disabled={busy}
          aria-label="Ask this desk a question"
        />
        <button className="primary" onClick={() => void submit()} disabled={busy || !draft.trim()}>
          {busy ? "…" : "Ask"}
        </button>
      </footer>
    </div>
  );
}

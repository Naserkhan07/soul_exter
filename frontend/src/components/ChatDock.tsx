/**
 * The chat-room icon on the floor.
 *
 * The room was behind a top-bar button, which is fine once you know it is
 * there and useless if you do not. This is the standing entry point: a named
 * icon in the corner that says what the room is, whether the desks are talking
 * right now, how long until the next round, and how much training has happened
 * since you last looked. Clicking it opens the room over the floor.
 */
import { useEffect, useRef, useState } from "react";

export function ChatDock({
  name,
  open,
  trainingTurns,
  thinking,
  nextRoundIn,
  heardCount,
  onOpen,
}: {
  /** the room's name, straight from the engine */
  name?: string;
  /** true while the room is on screen (so it stops counting as unread) */
  open: boolean;
  trainingTurns: number;
  /** a desk composing a turn right now */
  thinking: { key: string; name: string } | null;
  nextRoundIn?: number | null;
  /** how many rules the desks have heard each other write */
  heardCount: number;
  onOpen: () => void;
}) {
  const seen = useRef(trainingTurns);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (open) {
      seen.current = trainingTurns;
      setUnread(0);
      return;
    }
    const fresh = Math.max(0, trainingTurns - seen.current);
    if (fresh !== unread) setUnread(fresh);
  }, [trainingTurns, open, unread]);

  const speaking = Boolean(thinking);
  const status = speaking
    ? `${thinking?.name} is talking…`
    : nextRoundIn != null
      ? `next round in ${Math.max(0, Math.round(nextRoundIn))}s`
      : "the desks are at their screens";

  return (
    <button
      className={`chat-dock${speaking ? " live" : ""}${unread > 0 ? " unread" : ""}`}
      onClick={onOpen}
      title={`${name ?? "Chat room"} — the six desks talk, debate and train each other here`}
    >
      <span className="dock-icon" aria-hidden>
        <svg viewBox="0 0 24 24" width="22" height="22">
          <path
            d="M4 5.5h16a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H9.2l-4.1 3.3a.6.6 0 0 1-1-.46V16.5H4A1.5 1.5 0 0 1 2.5 15V7A1.5 1.5 0 0 1 4 5.5Z"
            fill="currentColor"
          />
          <circle cx="8" cy="11" r="1.25" fill="#0b1017" />
          <circle cx="12" cy="11" r="1.25" fill="#0b1017" />
          <circle cx="16" cy="11" r="1.25" fill="#0b1017" />
        </svg>
        {speaking && <span className="dock-pulse" />}
      </span>
      <span className="dock-text">
        <b>{name ?? "Chat room"}</b>
        <i>{status}</i>
        <em>
          {trainingTurns} training turns · {heardCount} rules heard
        </em>
      </span>
      {unread > 0 && <span className="dock-badge">{unread}</span>}
    </button>
  );
}

"""Parse a scene-by-scene script into individual shots.

Accepted input styles (all case-insensitive, mix-and-match friendly):

    Scene 1: A lone astronaut walks across red dunes.
    Scene 2 - The camera pulls back to reveal a wrecked ship.

    [Scene 3]
    Dust storm rolls in over the ridge.

    ---
    A paragraph separated by a blank line or a rule also counts as a scene.

If a scene's text is longer than one clip can cover, it is split into
several sequential shots so the narration still lands in order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# "Scene 1:", "SCENE 12 -", "[Scene 3]", "Shot 4."
_HEADER = re.compile(
    r"""^\s*
        \[?                         # optional opening bracket
        (?:scene|shot|clip|part)    # the keyword
        \s*
        \#?\s*
        (\d+)                       # the number
        \]?                         # optional closing bracket
        \s*
        [:.\-–—)]*                  # optional separator
        \s*
        (.*)$                       # trailing text on the same line
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A line that is only a horizontal rule: ---, ***, ___
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")

# Sentence-ish boundary used when splitting overlong scenes.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: Sentences shorter than this are folded into a neighbour before splitting.
_MIN_PROMPT_CHARS = 60


@dataclass
class Scene:
    """One shot to be sent to the video model."""

    index: int
    """1-based position in the final film."""

    text: str
    """The prompt handed to the video model."""

    duration: int = 10
    """Requested clip length in seconds."""

    source_scene: int | None = None
    """Which script scene this came from (set when a scene was split)."""

    part: int = 1
    """Part number within the source scene."""

    parts_total: int = 1
    """How many parts the source scene was split into."""

    meta: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Stable filename stem, e.g. ``scene_007``."""
        return f"scene_{self.index:03d}"

    @property
    def label(self) -> str:
        """Human-readable name for logs."""
        if self.parts_total > 1:
            return f"scene {self.source_scene} (part {self.part}/{self.parts_total})"
        return f"scene {self.source_scene or self.index}"


class ScriptError(ValueError):
    """Raised when a script cannot be turned into any scenes."""


def _split_text(text: str, chunks: int) -> list[str]:
    """Split *text* into at most *chunks* pieces, never below a sentence.

    A video prompt has to be a coherent description, so this refuses to cut
    mid-sentence. If a scene has fewer sentences than requested parts, the
    caller gets back fewer pieces and the whole scene text is reused as the
    prompt for each continuing shot instead of being chopped into fragments.
    """
    if chunks <= 1:
        return [text]

    sentences = [s.strip() for s in _SENTENCE.split(text) if s.strip()]

    if len(sentences) <= 1:
        # One sentence: can't split it without producing nonsense. Every part
        # keeps the full description; continuation is signalled in the prompt.
        return [text] * chunks

    # Fold very short sentences ("Wide shot.", "Inside the wreck.") into a
    # neighbour — alone they make thin, ambiguous prompts. Only do this while
    # we still have more sentences than shots to fill, so merging never
    # starves the split.
    while len(sentences) > chunks:
        shortest = min(range(len(sentences)), key=lambda i: len(sentences[i]))
        if len(sentences[shortest]) >= _MIN_PROMPT_CHARS:
            break
        if shortest + 1 < len(sentences):
            sentences[shortest] = f"{sentences[shortest]} {sentences[shortest + 1]}"
            del sentences[shortest + 1]
        else:
            sentences[shortest - 1] = f"{sentences[shortest - 1]} {sentences[shortest]}"
            del sentences[shortest]

    if len(sentences) <= 1:
        return [sentences[0] if sentences else text] * chunks

    if len(sentences) < chunks:
        # Give each sentence its own shot, then let the remaining parts
        # continue the last beat rather than inventing fragments.
        pieces = list(sentences)
        while len(pieces) < chunks:
            pieces.append(sentences[-1])
        return pieces

    # Balance groups by character count rather than sentence count, so one
    # long sentence doesn't get paired with three short ones.
    total = sum(len(s) for s in sentences)
    target = total / chunks
    out: list[str] = []
    current: list[str] = []
    running = 0
    for i, sentence in enumerate(sentences):
        remaining_sentences = len(sentences) - i
        remaining_slots = chunks - len(out)
        must_close = remaining_sentences <= remaining_slots - (1 if current else 0)

        current.append(sentence)
        running += len(sentence)

        if remaining_slots <= 1:
            continue
        if running >= target * 0.85 or must_close:
            out.append(" ".join(current))
            current, running = [], 0

    if current:
        out.append(" ".join(current))
    while len(out) < chunks:
        out.append(out[-1])
    return out[:chunks]


def _raw_scenes(script: str) -> list[tuple[int | None, str]]:
    """Pull (declared_number, text) pairs out of the script."""
    lines = script.splitlines()
    scenes: list[tuple[int | None, list[str]]] = []
    current: list[str] | None = None
    current_no: int | None = None
    saw_header = False

    def flush() -> None:
        nonlocal current, current_no
        if current is not None:
            body = "\n".join(current).strip()
            if body:
                scenes.append((current_no, current))
        current, current_no = None, None

    for line in lines:
        header = _HEADER.match(line)
        if header:
            saw_header = True
            flush()
            current_no = int(header.group(1))
            trailing = header.group(2).strip()
            current = [trailing] if trailing else []
            continue

        if _RULE.match(line):
            flush()
            continue

        if not line.strip():
            if not saw_header:
                # Blank line separates scenes only in header-less scripts.
                flush()
            elif current is not None:
                current.append("")
            continue

        if current is None:
            current = []
        current.append(line)

    flush()

    out: list[tuple[int | None, str]] = []
    for number, body in scenes:
        text = " ".join(part.strip() for part in body if part.strip()).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            out.append((number, text))
    return out


def parse_script(
    script: str,
    *,
    clip_seconds: int = 10,
    target_seconds: int | None = None,
    max_scenes: int | None = None,
) -> list[Scene]:
    """Turn raw script text into an ordered list of :class:`Scene`.

    Args:
        script: The user's script.
        clip_seconds: Length of a single generated clip.
        target_seconds: If set, scenes are split until the total run time
            reaches at least this many seconds. Use it to hit "5 minutes"
            from a script that only has a handful of scenes.
        max_scenes: Hard ceiling on the number of clips, as a cost guard.

    Raises:
        ScriptError: If no scenes could be found.
    """
    if clip_seconds <= 0:
        raise ValueError("clip_seconds must be positive")

    raw = _raw_scenes(script)
    if not raw:
        raise ScriptError(
            "No scenes found. Label them like 'Scene 1: ...' or separate "
            "them with blank lines."
        )

    # Work out how many clips each scene should become.
    needed = len(raw)
    if target_seconds:
        needed = max(needed, -(-target_seconds // clip_seconds))  # ceil div
    if max_scenes:
        needed = min(needed, max(len(raw), 1) if max_scenes < len(raw) else max_scenes)
        needed = min(needed, max_scenes)

    # Distribute the extra clips across scenes, longest text first.
    per_scene = [1] * len(raw)
    extra = needed - len(raw)
    if extra > 0:
        order = sorted(range(len(raw)), key=lambda i: len(raw[i][1]), reverse=True)
        for n in range(extra):
            per_scene[order[n % len(order)]] += 1

    scenes: list[Scene] = []
    index = 1
    for (declared, text), chunks in zip(raw, per_scene):
        source_no = declared if declared is not None else len(scenes) + 1
        pieces = _split_text(text, chunks)
        for part, piece in enumerate(pieces, start=1):
            if max_scenes and index > max_scenes:
                break

            prompt = piece
            # When a part repeats earlier text (scene was too short to split
            # cleanly), tell the model to continue the shot instead of
            # restarting it, so the cut doesn't jump back to frame one.
            if part > 1 and piece == pieces[part - 2]:
                prompt = (
                    f"{piece} Continuous shot, part {part} of {len(pieces)}: "
                    "the action carries on from the previous moment with the "
                    "camera still moving."
                )
            elif len(piece) < _MIN_PROMPT_CHARS and piece != text:
                # A terse beat like "Wide shot." on its own gives the model
                # nothing to work with — carry the rest of the scene in as
                # setting so the look stays consistent across the cut.
                # Only the *surrounding* text is added; repeating the piece
                # itself would just pad the prompt with a duplicate sentence.
                context = " ".join(p for p in pieces if p != piece).strip()
                prompt = f"{piece} Setting: {context}" if context else piece

            scenes.append(
                Scene(
                    index=index,
                    text=prompt,
                    duration=clip_seconds,
                    source_scene=source_no,
                    part=part,
                    parts_total=len(pieces),
                )
            )
            index += 1

    return scenes


def load_script(path: str) -> str:
    """Read a script file as UTF-8."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def summarize(scenes: Iterable[Scene]) -> str:
    """One-line human summary of a scene list."""
    scenes = list(scenes)
    total = sum(s.duration for s in scenes)
    return (
        f"{len(scenes)} clips x ~{scenes[0].duration if scenes else 0}s "
        f"= {total // 60}m {total % 60:02d}s"
    )

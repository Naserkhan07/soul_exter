"""Turn a plain story into a numbered shot list.

Most people have a story, not a storyboard. This splits prose into scenes
sized for one clip each, and — importantly for video models — carries a
consistent description of every recurring character into each shot.

Two backends:

``rules`` (default)
    Sentence-boundary splitting plus regex character extraction. No model,
    no network, instant, works offline.

``llm``
    Ask a local Ollama model for a proper shot breakdown. Better pacing and
    much better character descriptions, but needs Ollama running.

Both emit the same ``Scene 1: ...`` format the parser already understands,
so the rest of the pipeline is unchanged.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# Sentence split that tolerates "Mr." and "e.g."
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")

# A capitalised name not at the start of a sentence is probably a character.
_NAME = re.compile(r"\b([A-Z][a-z]{2,})\b")

#: Words that look like names but are not.
_NOT_NAMES = {
    "The", "A", "An", "But", "And", "Then", "When", "While", "After",
    "Before", "Inside", "Outside", "Above", "Below", "Later", "Suddenly",
    "Meanwhile", "Finally", "However", "Now", "Here", "There", "This",
    "That", "These", "Those", "One", "Two", "Three", "First", "Last",
    "Next", "Every", "Some", "Many", "Most", "His", "Her", "Their", "Its",
    "She", "He", "They", "It", "We", "You", "I", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January",
    "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "Scene", "Shot",
}

#: Traits worth carrying between shots so a character stays recognisable.
_TRAIT = re.compile(
    r"\b((?:young|old|elderly|tall|short|small|large|thin|slender|burly|"
    r"bearded|bald|grey|gray|white|black|brown|blonde|red)[\w-]*)\s+"
    r"(?:haired\s+)?(\w+)?",
    re.IGNORECASE,
)


@dataclass
class Character:
    """A recurring figure, described once and reused everywhere."""

    name: str
    description: str = ""
    mentions: int = 0

    def as_prompt(self) -> str:
        return f"{self.name} ({self.description})" if self.description else self.name


@dataclass
class Storyboard:
    scenes: list[str] = field(default_factory=list)
    characters: dict[str, Character] = field(default_factory=dict)
    style: str = ""

    def to_script(self, *, with_characters: bool = True) -> str:
        """Render as the ``Scene N:`` text the parser expects."""
        out: list[str] = []
        for i, text in enumerate(self.scenes, start=1):
            body = text
            if with_characters:
                described = self._describe_present(text)
                if described:
                    body = f"{body} {described}"
            if self.style:
                body = f"{body} {self.style}"
            out.append(f"Scene {i}: {body}")
        return "\n\n".join(out) + "\n"

    def _describe_present(self, text: str) -> str:
        """Append descriptions of characters mentioned in this shot.

        Video models have no memory between clips, so the only way a
        character stays recognisable is to re-describe them every time.
        """
        parts = []
        for char in self.characters.values():
            if not char.description:
                continue
            if re.search(rf"\b{re.escape(char.name)}\b", text):
                parts.append(f"{char.name} is {char.description}.")
        return " ".join(parts)


#: Verbs and connectives that mean the match ran past the character's
#: own noun phrase into a neighbouring clause.
_STOP_BEFORE_NAME = {
    "had", "has", "have", "was", "were", "is", "are", "did", "does",
    "went", "came", "ran", "sat", "stood", "passed", "rolled", "turned",
    "climbed", "heard", "saw", "hauled", "clung", "waving", "wrapped",
    "and", "but", "then", "when", "while", "because", "so",
}

#: Words that can precede a name but are never part of a description.
_FILLER = {
    "the", "a", "an", "and", "of", "his", "her", "their", "its", "was",
    "is", "were", "are", "named", "called", "then", "when", "while",
    "said", "who", "that", "with", "from", "to", "by", "at", "in", "on",
}


def find_characters(story: str, *, min_mentions: int = 2) -> dict[str, Character]:
    """Pull recurring named characters and their traits out of prose.

    A capitalised word is treated as a name when it appears at least
    *min_mentions* times and is not a common sentence-opening word. Counting
    every position matters: a character who starts sentences ("Alden ran...")
    would otherwise be missed entirely.
    """
    counts: dict[str, int] = {}
    for match in _NAME.finditer(story):
        name = match.group(1)
        if name in _NOT_NAMES:
            continue
        counts[name] = counts.get(name, 0) + 1

    characters: dict[str, Character] = {}
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        if count < min_mentions:
            continue
        characters[name] = Character(name=name, mentions=count,
                                     description=_describe(story, name))
    return characters


def _describe(story: str, name: str) -> str:
    """Build a usable appearance phrase for *name*.

    Looks at the words immediately before each mention and keeps the
    descriptive ones, so "the old keeper Alden" yields "old keeper" and
    "a young woman named Mira" yields "young woman" — dropping the
    connective "named", which would otherwise produce the nonsense
    "Mira is young woman named."
    """
    best: list[str] = []
    for match in re.finditer(
        # Only descriptive words: no verbs or clause boundaries may sneak in,
        # otherwise "...wrapped in a blanket. Mira" yields "a blanket".
        rf"\b(?:the|a|an)\s+((?:[a-z][\w-]*\s+){{1,4}}?){re.escape(name)}\b",
        story, re.IGNORECASE,
    ):
        words = match.group(1).split()
        if any(w.lower() in _STOP_BEFORE_NAME for w in words):
            continue
        words = [w for w in words if w.lower() not in _FILLER]
        if words and len(words) > len(best):
            best = words

    if not best:
        return ""

    phrase = " ".join(best[:4]).lower()
    # "old keeper" -> "an old keeper"; keep it grammatical when appended.
    article = "an" if phrase[0] in "aeiou" else "a"
    return f"{article} {phrase}"


def split_story(
    story: str,
    *,
    scenes: int | None = None,
    clip_seconds: int = 5,
    target_seconds: int | None = None,
) -> list[str]:
    """Split prose into roughly *scenes* shot descriptions."""
    text = " ".join(story.split())
    sentences = [s.strip() for s in _SENTENCE.split(text) if s.strip()]
    if not sentences:
        return []

    if scenes is None:
        scenes = (
            max(1, -(-target_seconds // clip_seconds)) if target_seconds
            else len(sentences)
        )

    if scenes >= len(sentences):
        # More shots wanted than sentences: one each, the parser's
        # --target logic will pad the rest.
        return sentences

    # Group sentences into balanced chunks by character count, so one long
    # sentence is not paired with three short ones.
    per = sum(len(s) for s in sentences) / scenes
    out: list[str] = []
    current: list[str] = []
    running = 0
    for i, sentence in enumerate(sentences):
        current.append(sentence)
        running += len(sentence)
        slots_left = scenes - len(out)
        sentences_left = len(sentences) - i - 1
        if slots_left <= 1:
            continue
        if running >= per * 0.85 or sentences_left < slots_left:
            out.append(" ".join(current))
            current, running = [], 0
    if current:
        out.append(" ".join(current))
    return out[:scenes]


def storyboard_rules(
    story: str,
    *,
    scenes: int | None = None,
    clip_seconds: int = 5,
    target_seconds: int | None = None,
    style: str = "",
) -> Storyboard:
    """Offline storyboard: split sentences, carry characters forward."""
    return Storyboard(
        scenes=split_story(story, scenes=scenes, clip_seconds=clip_seconds,
                           target_seconds=target_seconds),
        characters=find_characters(story),
        style=style,
    )


# --------------------------------------------------------------------------
# LLM backend (local Ollama)
# --------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"

_PROMPT = """You are a storyboard artist. Break this story into exactly \
{n} shots for an AI video generator.

Rules:
- One shot per line, numbered "1." to "{n}.".
- Each shot is ONE sentence describing what the camera sees.
- Name the camera move (slow dolly in, pan left, static wide, handheld).
- Re-describe each character's appearance EVERY time they appear, because
  the video model has no memory between shots.
- Describe only visible things. No dialogue, no inner thoughts.

Story:
{story}

Shots:"""


class StoryboardError(RuntimeError):
    pass


def storyboard_llm(
    story: str,
    *,
    scenes: int = 12,
    model: str = "llama3.2",
    style: str = "",
    url: str = OLLAMA_URL,
    timeout: int = 180,
) -> Storyboard:
    """Ask a local Ollama model for a shot breakdown."""
    body = {
        "model": model,
        "prompt": _PROMPT.format(n=scenes, story=story.strip()),
        "stream": False,
        "options": {"temperature": 0.7},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read().decode()).get("response", "")
    except urllib.error.URLError as exc:
        raise StoryboardError(
            f"Could not reach Ollama at {url} ({exc.reason}). Start it with "
            "`ollama serve`, or use --storyboard rules for the offline "
            "splitter."
        ) from exc

    shots = []
    for line in reply.splitlines():
        line = line.strip()
        match = re.match(r"^\d+[.)]\s*(.+)$", line)
        if match and len(match.group(1)) > 15:
            shots.append(match.group(1).strip())

    if not shots:
        raise StoryboardError(
            f"Ollama returned no usable shots. Raw reply:\n{reply[:400]}"
        )

    return Storyboard(scenes=shots[:scenes],
                      characters=find_characters(story), style=style)


def build(
    story: str,
    *,
    backend: str = "rules",
    scenes: int | None = None,
    clip_seconds: int = 5,
    target_seconds: int | None = None,
    style: str = "",
    model: str = "llama3.2",
) -> Storyboard:
    """Build a storyboard with the chosen backend."""
    if backend == "llm":
        n = scenes or (-(-target_seconds // clip_seconds) if target_seconds else 12)
        return storyboard_llm(story, scenes=n, model=model, style=style)
    if backend == "rules":
        return storyboard_rules(story, scenes=scenes, clip_seconds=clip_seconds,
                                target_seconds=target_seconds, style=style)
    raise StoryboardError(f"Unknown storyboard backend {backend!r}")

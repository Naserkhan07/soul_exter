"""Building the text actually sent to a video model.

A scene description from a script is not a good prompt. Video models respond
to concrete visual instruction — who is on screen and what they look like,
where they are, how it is lit, what the camera does — and they weight early
tokens heavily.

This assembles those parts in a deliberate order and lets each provider take
only the fields it understands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from soulclip.capabilities import Capabilities
from soulclip.characters import Character, CharacterBook

#: Ordered so the most important information lands first.
SECTION_ORDER = (
    "shot", "characters", "action", "location", "lighting", "style",
)

#: Camera framings we can infer from the text.
_SHOTS = {
    "close-up": r"\b(close[- ]?up|closeup|face|eyes|hands?)\b",
    "wide establishing shot": r"\b(wide|establishing|landscape|vista|"
                              r"panorama|horizon)\b",
    "medium shot": r"\b(medium shot|waist|standing|talking|speaking)\b",
    "low angle shot": r"\b(low angle|looming|towering|from below)\b",
    "aerial shot": r"\b(aerial|bird'?s eye|from above|overhead|drone)\b",
}

#: Camera movement, if the writer named one.
_MOVES = {
    "slow dolly in": r"\b(dolly in|push in|zoom in|approach)\b",
    "slow pull back": r"\b(pull back|pulls? back|zoom out|reveal)\b",
    "pan left": r"\bpan(?:ning)? left\b",
    "pan right": r"\bpan(?:ning)? right\b",
    "handheld camera": r"\b(handheld|shaky|chaotic|violent|frantic)\b",
    "static locked-off shot": r"\b(static|still|locked|motionless)\b",
}

_LIGHTING = {
    "warm golden hour light": r"\b(dawn|sunrise|sunset|dusk|golden|amber)\b",
    "cool moonlight": r"\b(night|moonlit|moonlight|midnight|starlight)\b",
    "soft overcast light": r"\b(overcast|grey|gray|cloudy|fog|mist)\b",
    "dramatic storm light": r"\b(storm|lightning|thunder|tempest)\b",
    "warm interior lamplight": r"\b(lamp|candle|fire|hearth|lantern|indoor|"
                               r"warmly lit|cosy|cozy)\b",
    "harsh midday sun": r"\b(noon|midday|harsh sun|blazing|scorching)\b",
}

#: Baseline negatives that help almost every model.
BASE_NEGATIVE = (
    "blurry, low quality, distorted, watermark, text, extra limbs, "
    "duplicate person, deformed hands, jittery motion"
)


@dataclass
class PromptParts:
    """The assembled pieces, kept separate so they can be inspected."""

    shot: str = ""
    characters: str = ""
    action: str = ""
    location: str = ""
    lighting: str = ""
    style: str = ""
    negative: str = ""
    seed: int | None = None
    reference_image: str | None = None

    def text(self) -> str:
        parts = [getattr(self, name) for name in SECTION_ORDER]
        joined = ", ".join(p.strip(" ,.") for p in parts if p.strip())
        return re.sub(r"\s+", " ", joined).strip(" ,")

    def as_dict(self) -> dict:
        return {
            "prompt": self.text(),
            "negative_prompt": self.negative,
            "seed": self.seed,
            "reference_image": self.reference_image,
        }


def _match(text: str, table: dict[str, str]) -> str:
    for label, pattern in table.items():
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return ""


def infer_shot(text: str) -> str:
    """Guess framing and camera move from the scene description."""
    framing = _match(text, _SHOTS) or "cinematic shot"
    move = _match(text, _MOVES)
    return f"{framing}, {move}" if move else framing


def infer_lighting(text: str) -> str:
    return _match(text, _LIGHTING)


class PromptBuilder:
    """Turns a scene into a provider-ready prompt.

    Args:
        book: Character profiles to inject when a name appears.
        style: Style suffix applied to every shot, e.g. "Pixar-quality
            animation, ultra detailed".
        negative: Extra negatives on top of :data:`BASE_NEGATIVE`.
        infer: Guess shot type and lighting from the text. Turn off if your
            scene descriptions already specify them.
    """

    def __init__(
        self,
        book: CharacterBook | None = None,
        *,
        style: str = "",
        negative: str = "",
        infer: bool = True,
        base_seed: int | None = None,
    ) -> None:
        self.book = book
        self.style = style
        self.extra_negative = negative
        self.infer = infer
        self.base_seed = base_seed

    # ------------------------------------------------------------------

    def build(self, scene, *, capabilities: Capabilities | None = None
              ) -> PromptParts:
        """Assemble the prompt for one scene."""
        text = scene.text if hasattr(scene, "text") else str(scene)
        index = getattr(scene, "index", 0)

        parts = PromptParts()
        parts.action = self._clean_action(text)

        if self.infer:
            parts.shot = infer_shot(text)
            parts.lighting = infer_lighting(text)

        present = self.book.present_in(text) if self.book else []
        if present:
            parts.characters = "; ".join(c.describe() for c in present)

        parts.style = self.style
        parts.negative = self._negative(present)
        parts.seed = self._seed(index, present)

        ref = self._reference(present)
        if ref:
            parts.reference_image = str(ref)

        if capabilities is not None:
            if not capabilities.supports("negative_prompt"):
                parts.negative = ""
            if not capabilities.supports("seed"):
                parts.seed = None
            if not capabilities.supports("image_reference"):
                parts.reference_image = None

        return parts

    # ------------------------------------------------------------------

    @staticmethod
    def _clean_action(text: str) -> str:
        """Strip bookkeeping the parser added; keep the visible action."""
        text = re.split(r"\bSetting:\s*", text)[0]
        text = re.sub(r"Continuous shot.*?(?:\.|$)", "", text,
                      flags=re.IGNORECASE)
        # Character re-descriptions are rebuilt from profiles instead.
        text = re.sub(r"\b\w+ is an? [\w\s]+?\.", "", text)
        return " ".join(text.split()).strip(" ,.")

    def _negative(self, present: list[Character]) -> str:
        parts = [BASE_NEGATIVE]
        if self.extra_negative:
            parts.append(self.extra_negative)
        for char in present:
            if char.negative_prompt:
                parts.append(char.negative_prompt)

        seen: list[str] = []
        for chunk in parts:
            for item in chunk.split(","):
                item = item.strip()
                if item and item not in seen:
                    seen.append(item)
        return ", ".join(seen)

    def _seed(self, index: int, present: list[Character]) -> int | None:
        """Prefer a character's fixed seed so they render consistently."""
        for char in present:
            if char.seed is not None:
                return char.seed
        if self.base_seed is not None:
            # Vary per shot, but reproducibly.
            return self.base_seed + index
        return None

    @staticmethod
    def _reference(present: list[Character]):
        for char in present:
            ref = char.reference or char.full_body
            if ref:
                return ref
        return None


def build_all(scenes, book=None, **kwargs) -> list[PromptParts]:
    """Convenience: build prompts for a whole scene list."""
    builder = PromptBuilder(book, **kwargs)
    return [builder.build(scene) for scene in scenes]

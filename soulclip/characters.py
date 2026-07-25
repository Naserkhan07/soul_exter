"""Persistent character definitions.

A video model has no memory between clips, so the only way a character stays
recognisable is to describe them identically every time. Writing that by hand
for thirty shots is tedious and error-prone, so it lives on disk instead:

    characters/
        father/
            profile.json
            reference.png
        mother/
            profile.json

The prompt builder injects the right profile automatically whenever a
character is named in a scene.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Where profiles live by default, relative to the project root.
DEFAULT_DIR = Path("characters")

#: Filenames tried, in order, when looking for a reference still.
REFERENCE_NAMES = ("reference.png", "reference.jpg", "reference.jpeg",
                   "face.png", "portrait.png")
FULL_BODY_NAMES = ("full_body.png", "full_body.jpg", "body.png")


def slugify(name: str) -> str:
    """'Old Keeper' -> 'old_keeper'."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


@dataclass
class Character:
    """Everything needed to render one person consistently."""

    name: str
    age: int | None = None
    gender: str = ""
    appearance: str = ""
    clothes: str = ""
    voice: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    notes: str = ""

    #: Filled in when loaded from disk.
    directory: Path | None = field(default=None, repr=False, compare=False)

    # -- files ---------------------------------------------------------

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def _find(self, names) -> Path | None:
        if not self.directory:
            return None
        for candidate in names:
            path = self.directory / candidate
            if path.exists():
                return path
        return None

    @property
    def reference(self) -> Path | None:
        """Face/portrait still, if one was supplied."""
        return self._find(REFERENCE_NAMES)

    @property
    def full_body(self) -> Path | None:
        return self._find(FULL_BODY_NAMES)

    # -- prompt text ---------------------------------------------------

    def describe(self, *, include_name: bool = True) -> str:
        """One clause describing this character, for a prompt.

        Deliberately terse: video models weight early tokens heavily, and a
        long biography crowds out the action.
        """
        bits: list[str] = []
        if self.age and self.gender:
            bits.append(f"{self.age}-year-old {self.gender}")
        elif self.gender:
            bits.append(self.gender)
        elif self.age:
            bits.append(f"{self.age} years old")

        if self.appearance:
            bits.append(self.appearance)
        if self.clothes:
            bits.append(f"wearing {self.clothes}")

        body = ", ".join(b for b in bits if b)
        if not body:
            return self.name if include_name else ""
        return f"{self.name}: {body}" if include_name else body

    # -- persistence ---------------------------------------------------

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("directory", None)
        return {k: v for k, v in data.items() if v not in (None, "", [])}

    def save(self, root: Path | str = DEFAULT_DIR) -> Path:
        directory = Path(root) / self.slug
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "profile.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        self.directory = directory
        return path

    @classmethod
    def load(cls, directory: Path | str) -> "Character":
        directory = Path(directory)
        path = directory / "profile.json"
        if not path.exists():
            raise FileNotFoundError(f"No profile.json in {directory}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__ if f != "directory"}
        unknown = set(raw) - known
        # Unknown keys are kept as notes rather than crashing, so a profile
        # written by a newer version still loads.
        extra = {k: raw[k] for k in unknown}
        char = cls(**{k: v for k, v in raw.items() if k in known})
        char.directory = directory
        if extra:
            char.notes = (char.notes + " " + json.dumps(extra)).strip()
        return char


class CharacterBook:
    """All characters for a project, loaded from a directory."""

    def __init__(self, root: Path | str = DEFAULT_DIR) -> None:
        self.root = Path(root)
        self.characters: dict[str, Character] = {}
        if self.root.is_dir():
            self.reload()

    def reload(self) -> None:
        self.characters.clear()
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir():
                continue
            if not (directory / "profile.json").exists():
                continue
            char = Character.load(directory)
            self.characters[char.slug] = char

    # -- lookup --------------------------------------------------------

    def __len__(self) -> int:
        return len(self.characters)

    def __iter__(self):
        return iter(self.characters.values())

    def get(self, name: str) -> Character | None:
        return self.characters.get(slugify(name))

    def add(self, char: Character, *, save: bool = True) -> Character:
        self.characters[char.slug] = char
        if save:
            char.save(self.root)
        return char

    def present_in(self, text: str) -> list[Character]:
        """Characters whose name appears in *text*, in order of appearance.

        Matching is word-boundary and case-insensitive, so "father" in prose
        finds the "Father" profile without also matching "grandfather".
        """
        found: list[tuple[int, Character]] = []
        for char in self.characters.values():
            match = re.search(rf"\b{re.escape(char.name)}\b", text,
                              re.IGNORECASE)
            if match:
                found.append((match.start(), char))
        return [c for _, c in sorted(found, key=lambda p: p[0])]

    def negative_prompts(self) -> str:
        """Merged negative prompts from every character."""
        seen: list[str] = []
        for char in self.characters.values():
            for part in char.negative_prompt.split(","):
                part = part.strip()
                if part and part not in seen:
                    seen.append(part)
        return ", ".join(seen)

    def summary(self) -> str:
        if not self.characters:
            return "no characters defined"
        return "; ".join(
            f"{c.name}" + (" [ref]" if c.reference else "")
            for c in self.characters.values()
        )


def from_detected(detected: dict, root: Path | str = DEFAULT_DIR
                  ) -> list[Character]:
    """Turn storyboard-detected names into draft profiles.

    The storyboarder guesses appearance from prose; those guesses become
    editable profiles rather than being silently baked into prompts.
    """
    out = []
    for name, info in detected.items():
        appearance = getattr(info, "description", "") or ""
        # Strip the leading article the detector adds ("an old keeper").
        appearance = re.sub(r"^(a|an|the)\s+", "", appearance,
                            flags=re.IGNORECASE)
        out.append(Character(name=name, appearance=appearance))
    return out

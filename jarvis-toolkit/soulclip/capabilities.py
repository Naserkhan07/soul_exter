"""What each backend can actually do.

Providers differ widely: some take a reference image, some accept a seed,
some ignore negative prompts entirely. Passing an unsupported parameter is
at best wasted and at worst an API error, so every provider declares its
capabilities and the pipeline filters requests through them.

Adding a capability means adding one field here and setting it on the
providers that support it — nothing else changes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Capabilities:
    """A declaration of what a provider accepts.

    Defaults are deliberately conservative: an unknown provider is assumed
    to support only a text prompt, so nothing surprising is ever sent.
    """

    #: Accepts a still image to condition the clip on (image-to-video).
    image_reference: bool = False
    #: Accepts the last frame of the previous clip, for continuity chains.
    frame_chaining: bool = False
    #: Honours a fixed seed, so a shot can be reproduced.
    seed: bool = False
    #: Accepts a negative prompt.
    negative_prompt: bool = False
    #: Accepts a classifier-free guidance scale.
    cfg: bool = False
    #: Accepts a motion/dynamism control.
    motion: bool = False
    #: Produces its own audio track.
    audio: bool = False
    #: Can upscale its own output.
    upscale: bool = False
    #: Can extend an existing clip rather than starting fresh.
    extend: bool = False

    #: Clip lengths the service accepts; empty means anything goes.
    durations: tuple[int, ...] = ()
    #: Longest clip in seconds, 0 for no limit.
    max_seconds: float = 0.0
    #: Output dimensions must be a multiple of this.
    size_multiple: int = 1
    #: Requires a GPU to run at all.
    needs_gpu: bool = False
    #: Requires network access.
    needs_network: bool = False
    #: Costs real money per clip.
    costs_money: bool = False

    def supports(self, name: str) -> bool:
        """True if *name* is a capability this provider has."""
        return bool(getattr(self, name, False))

    def filter_kwargs(self, **kwargs) -> dict:
        """Drop any keyword whose backing capability is missing.

        Lets callers pass a full set of options and have each provider
        quietly take only what it understands.
        """
        mapping = {
            "image": "image_reference",
            "reference_image": "image_reference",
            "last_frame": "frame_chaining",
            "seed": "seed",
            "negative": "negative_prompt",
            "negative_prompt": "negative_prompt",
            "guidance": "cfg",
            "cfg_scale": "cfg",
            "motion": "motion",
        }
        out = {}
        for key, value in kwargs.items():
            need = mapping.get(key)
            if need is None or self.supports(need):
                out[key] = value
        return out

    def dropped(self, **kwargs) -> list[str]:
        """Names that :meth:`filter_kwargs` would remove — useful for logs."""
        kept = self.filter_kwargs(**kwargs)
        return sorted(set(kwargs) - set(kept))

    def as_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """Short human-readable list of what is supported."""
        flags = [
            n for n in (
                "image_reference", "frame_chaining", "seed",
                "negative_prompt", "cfg", "motion", "audio",
                "upscale", "extend",
            ) if self.supports(n)
        ]
        return ", ".join(flags) if flags else "text prompt only"


#: Sensible baseline for a provider that has not declared anything.
DEFAULT = Capabilities()


#: Known capability sets, keyed by provider name. Providers may also carry
#: their own ``capabilities`` attribute; that takes precedence.
KNOWN: dict[str, Capabilities] = {
    "mock": Capabilities(seed=True, audio=True),
    "folder": Capabilities(seed=True, image_reference=True),
    "localimage": Capabilities(seed=True, image_reference=True,
                               negative_prompt=True),
    "pollinations": Capabilities(seed=True, needs_network=True),
    "command": Capabilities(seed=True),
    "wan": Capabilities(
        seed=True, negative_prompt=True, cfg=True, needs_gpu=True,
        max_seconds=5.1, size_multiple=16,
    ),
    "ltx": Capabilities(
        seed=True, negative_prompt=True, cfg=True, image_reference=True,
        frame_chaining=True, needs_gpu=True, max_seconds=5.1,
        size_multiple=32,
    ),
    "replicate": Capabilities(
        seed=True, negative_prompt=True, cfg=True, image_reference=True,
        durations=(5, 10), needs_network=True, costs_money=True,
    ),
    "fal": Capabilities(
        seed=True, negative_prompt=True, image_reference=True,
        needs_network=True, costs_money=True,
    ),
    "xai": Capabilities(
        audio=True, needs_network=True, costs_money=True,
    ),
}


def for_provider(provider) -> Capabilities:
    """Capabilities for a provider instance or name."""
    if isinstance(provider, str):
        return KNOWN.get(provider.lower(), DEFAULT)
    declared = getattr(provider, "capabilities", None)
    if isinstance(declared, Capabilities):
        return declared
    return KNOWN.get(getattr(provider, "name", ""), DEFAULT)


def table() -> str:
    """Rendered capability matrix, for `soulclip providers`."""
    cols = [
        ("image", "image_reference"), ("chain", "frame_chaining"),
        ("seed", "seed"), ("neg", "negative_prompt"), ("cfg", "cfg"),
        ("audio", "audio"), ("gpu", "needs_gpu"), ("paid", "costs_money"),
    ]
    head = f"  {'provider':<14}" + "".join(f"{label:>7}" for label, _ in cols)
    lines = [head, "  " + "-" * (14 + 7 * len(cols))]
    for name in sorted(KNOWN):
        caps = KNOWN[name]
        row = f"  {name:<14}"
        row += "".join(f"{'yes' if caps.supports(a) else '-':>7}"
                       for _, a in cols)
        lines.append(row)
    return "\n".join(lines)

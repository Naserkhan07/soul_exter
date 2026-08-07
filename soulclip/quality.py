"""Validating generated clips, and deciding whether a failure is worth retrying.

Two jobs:

1. **Quality checks** — a provider can return HTTP 200 and still hand back a
   truncated file, a black frame, or a clip at the wrong length. Catching
   that here means one bad clip is regenerated instead of poisoning the
   final cut.

2. **Failure classification** — retrying a rate limit is sensible; retrying
   an invalid prompt just burns quota. Errors are sorted into kinds with
   different retry behaviour.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from soulclip.ffmpeg import ffmpeg_path, probe_duration


# --------------------------------------------------------------------------
# Quality checking
# --------------------------------------------------------------------------

@dataclass
class ClipReport:
    """Outcome of inspecting one generated clip."""

    path: Path
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = False
    size_bytes: int = 0

    def fail(self, reason: str) -> None:
        self.ok = False
        self.problems.append(reason)

    def warn(self, reason: str) -> None:
        self.warnings.append(reason)

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "ok"
        bits = [f"FAIL: {p}" for p in self.problems]
        bits += [f"warn: {w}" for w in self.warnings]
        return "; ".join(bits)


def _probe_streams(path: Path) -> dict:
    """Read size, fps and audio presence out of ffmpeg's own report."""
    info: dict = {}
    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-i", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return info

    err = proc.stderr
    size = re.search(r",\s(\d{2,5})x(\d{2,5})", err)
    if size:
        info["width"], info["height"] = int(size.group(1)), int(size.group(2))

    fps = re.search(r"(\d+(?:\.\d+)?)\s+fps", err)
    if fps:
        info["fps"] = float(fps.group(1))

    info["has_audio"] = "Audio:" in err
    return info


def check_clip(
    path: Path,
    *,
    expect_seconds: float | None = None,
    tolerance: float = 0.6,
    min_width: int = 64,
    min_bytes: int = 2048,
    require_audio: bool = False,
    check_black: bool = True,
) -> ClipReport:
    """Inspect one clip and report anything wrong with it."""
    path = Path(path)
    report = ClipReport(path=path)

    if not path.exists():
        report.fail("file does not exist")
        return report

    report.size_bytes = path.stat().st_size
    if report.size_bytes < min_bytes:
        report.fail(f"file is only {report.size_bytes} bytes")
        return report

    report.duration = probe_duration(path)
    if report.duration is None:
        report.fail("unreadable — not a valid video file")
        return report
    if report.duration <= 0.05:
        report.fail(f"duration is {report.duration:.2f}s")
        return report

    if expect_seconds:
        drift = abs(report.duration - expect_seconds)
        if drift > tolerance:
            # Not fatal: providers snap to their own frame counts, and the
            # stitcher copes. Worth surfacing though.
            report.warn(
                f"{report.duration:.2f}s, expected ~{expect_seconds:.2f}s"
            )

    streams = _probe_streams(path)
    report.width = streams.get("width")
    report.height = streams.get("height")
    report.fps = streams.get("fps")
    report.has_audio = streams.get("has_audio", False)

    if report.width and report.width < min_width:
        report.fail(f"only {report.width}px wide")
    if require_audio and not report.has_audio:
        report.fail("no audio track")

    if check_black and report.ok and is_black(path):
        report.fail("every sampled frame is black")

    return report


def is_black(path: Path, *, threshold: float = 0.98) -> bool:
    """True if the clip is essentially a black screen.

    Models occasionally return a valid file containing nothing. ffmpeg's
    blackdetect reports black spans; if they cover almost the whole clip
    the generation failed regardless of what the API said.
    """
    duration = probe_duration(path)
    if not duration or duration <= 0:
        return False

    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-i", str(path),
             "-vf", "blackdetect=d=0.1:pix_th=0.10",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except Exception:
        return False

    black = 0.0
    for match in re.finditer(r"black_duration:(\d+(?:\.\d+)?)", proc.stderr):
        black += float(match.group(1))
    return black >= duration * threshold


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------

class FailureKind(Enum):
    """How a failure should be handled."""

    NETWORK = "network"            # retry soon
    TIMEOUT = "timeout"            # retry soon
    RATE_LIMIT = "rate_limit"      # retry after a long back-off
    PROVIDER_BUSY = "busy"         # retry after a long back-off
    GPU_MEMORY = "gpu_memory"      # retry once smaller, then give up
    SAFETY_FILTER = "safety"       # never retry — the prompt is rejected
    INVALID_PROMPT = "invalid"     # never retry
    AUTH = "auth"                  # never retry
    QUALITY = "quality"            # retry: the clip came back unusable
    UNKNOWN = "unknown"            # retry cautiously

    @property
    def retryable(self) -> bool:
        return self not in {
            FailureKind.SAFETY_FILTER,
            FailureKind.INVALID_PROMPT,
            FailureKind.AUTH,
        }

    @property
    def backoff(self) -> float:
        """Seconds to wait before the first retry."""
        return {
            FailureKind.RATE_LIMIT: 60.0,
            FailureKind.PROVIDER_BUSY: 30.0,
            FailureKind.GPU_MEMORY: 5.0,
            FailureKind.NETWORK: 5.0,
            FailureKind.TIMEOUT: 10.0,
            FailureKind.QUALITY: 2.0,
        }.get(self, 5.0)

    @property
    def max_attempts(self) -> int:
        return {
            FailureKind.GPU_MEMORY: 2,
            FailureKind.RATE_LIMIT: 5,
            FailureKind.PROVIDER_BUSY: 5,
        }.get(self, 3)


#: Ordered most-specific first; the first match wins.
_PATTERNS: list[tuple[FailureKind, str]] = [
    (FailureKind.AUTH,
     r"\b(401|403|unauthori[sz]ed|forbidden|invalid api key|"
     r"authentication)\b"),
    (FailureKind.RATE_LIMIT,
     r"\b(429|rate.?limit|too many requests|quota exceeded|"
     r"throttl)\w*\b"),
    (FailureKind.GPU_MEMORY,
     r"\b(out of memory|oom|cuda error|insufficient memory|"
     r"memory allocation)\b"),
    (FailureKind.SAFETY_FILTER,
     r"\b(safety|nsfw|content policy|moderation|flagged|blocked "
     r"by filter)\b"),
    (FailureKind.INVALID_PROMPT,
     r"\b(invalid (?:prompt|input|parameter)|400 bad request|"
     r"validation (?:error|failed)|unsupported)\b"),
    (FailureKind.PROVIDER_BUSY,
     r"\b(50[234]|service unavailable|server (?:busy|overload)|"
     r"capacity|try again later)\b"),
    (FailureKind.TIMEOUT,
     r"\b(timed? ?out|timeout|deadline exceeded)\b"),
    (FailureKind.NETWORK,
     r"\b(connection|network|dns|unreachable|reset by peer|"
     r"ssl|certificate|temporarily)\b"),
    (FailureKind.QUALITY,
     r"\b(unplayable|empty or unplayable|black|corrupt|truncated|"
     r"no usable file)\b"),
]


def classify(error: BaseException | str) -> FailureKind:
    """Work out what kind of failure this is, from its message and type."""
    if isinstance(error, BaseException):
        # Trust explicit exception types over message matching.
        name = type(error).__name__
        if name == "AuthError":
            return FailureKind.AUTH
        if name == "PermanentError":
            return FailureKind.INVALID_PROMPT
        if name in ("OutOfMemoryError", "CudaOutOfMemoryError"):
            return FailureKind.GPU_MEMORY
        if name in ("TimeoutError", "ReadTimeout", "ConnectTimeout"):
            return FailureKind.TIMEOUT
        text = f"{name}: {error}"
    else:
        text = str(error)

    lowered = text.lower()
    for kind, pattern in _PATTERNS:
        if re.search(pattern, lowered):
            return kind
    return FailureKind.UNKNOWN


@dataclass
class RetryPlan:
    """What to do about a failure."""

    kind: FailureKind
    should_retry: bool
    wait_seconds: float
    attempt: int
    reason: str = ""

    def describe(self) -> str:
        if not self.should_retry:
            return f"{self.kind.value} — not retryable"
        return (f"{self.kind.value} — retry {self.attempt} in "
                f"{self.wait_seconds:.0f}s")


def plan_retry(error, attempt: int, *, max_retries: int = 2) -> RetryPlan:
    """Decide whether and when to retry after *error*.

    ``attempt`` is 1-based: 1 means the first try just failed.
    """
    kind = classify(error)
    limit = min(max_retries + 1, kind.max_attempts)

    if not kind.retryable:
        return RetryPlan(kind, False, 0.0, attempt,
                         "this failure will repeat identically")
    if attempt >= limit:
        return RetryPlan(kind, False, 0.0, attempt,
                         f"gave up after {attempt} attempts")

    # Exponential back-off, so a busy provider is not hammered.
    wait = kind.backoff * (2 ** (attempt - 1))
    return RetryPlan(kind, True, wait, attempt)

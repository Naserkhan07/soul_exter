"""Turn a still image into a moving cinematic clip.

Free image generators are effectively unlimited; free *video* generators are
not. This module closes the gap: it takes one still and animates it with a
virtual camera — slow push-ins, pans, drifts — plus film grain, vignette and
letterboxing, so a sequence of stills reads as a shot film rather than a
slideshow.

This is the technique behind animatics and motion comics. It is not true
frame-by-frame animation: subjects inside the frame don't move, the camera
does. For anime-styled storytelling that reads as intentional.

Everything here is ffmpeg filter work — no model, no GPU, no network.
"""

from __future__ import annotations

import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

from soulclip.ffmpeg import FFmpegError, ffmpeg_path, has_filter

#: Camera moves, chosen per shot. Each is a (zoom, x, y) expression trio for
#: the zoompan filter, evaluated per output frame with `on` as frame number.
MOVES = (
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "drift_up",
    "drift_down",
)


@dataclass
class MotionStyle:
    """Look and camera settings for a generated clip."""

    #: How far the camera travels over the shot. 0.12 = a 12% push.
    intensity: float = 0.12
    #: Film grain strength (0 disables).
    grain: float = 8.0
    #: Vignette darkening at the corners.
    vignette: bool = True
    #: Black bars for a 2.39:1 scope feel (0 disables).
    letterbox: float = 0.0
    #: Fade in/out duration in seconds.
    fade: float = 0.4
    #: Subtle warm/cool grade: "warm", "cool", "neutral".
    grade: str = "neutral"


def _zoompan_expr(move: str, frames: int, intensity: float) -> tuple[str, str, str]:
    """Return (zoom, x, y) expressions for a named camera move."""
    # `on` is the current output frame. Normalised progress 0..1:
    p = f"(on/{max(frames - 1, 1)})"
    zi = 1.0 + intensity

    if move == "push_in":
        return f"1+{intensity}*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if move == "pull_out":
        return f"{zi}-{intensity}*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if move == "pan_left":
        return f"{zi}", f"(iw-iw/zoom)*(1-{p})", "ih/2-(ih/zoom/2)"
    if move == "pan_right":
        return f"{zi}", f"(iw-iw/zoom)*{p}", "ih/2-(ih/zoom/2)"
    if move == "drift_up":
        return f"{zi}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-{p})"
    if move == "drift_down":
        return f"{zi}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*{p}"
    # Fallback: gentle push.
    return f"1+{intensity}*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"


def pick_move(seed: int) -> str:
    """Deterministically choose a camera move for a shot index.

    Consecutive shots get different moves so the film doesn't feel like the
    same push repeated thirty times.
    """
    return MOVES[seed % len(MOVES)]


def animate_still(
    image: Path,
    dest: Path,
    *,
    duration: float = 10.0,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    move: str | None = None,
    style: MotionStyle | None = None,
    seed: int = 0,
    silent_audio: bool = True,
) -> Path:
    """Render *image* into a moving clip at *dest*.

    Args:
        duration: Clip length in seconds.
        move: One of :data:`MOVES`; chosen from *seed* when omitted.
        style: Look settings; defaults are a mild cinematic grade.
        silent_audio: Attach a silent track so clips concat cleanly.
    """
    image = Path(image)
    dest = Path(dest)
    if not image.exists():
        raise FFmpegError(f"Image not found: {image}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    style = style or MotionStyle()
    move = move or pick_move(seed)
    frames = max(int(round(duration * fps)), 2)

    zoom, x, y = _zoompan_expr(move, frames, style.intensity)

    # Supersample before zoompan: it works in integer steps, and scaling up
    # first is what keeps the motion smooth instead of visibly juddering.
    ss_w, ss_h = width * 2, height * 2

    chain = [
        f"scale={ss_w}:{ss_h}:force_original_aspect_ratio=increase",
        f"crop={ss_w}:{ss_h}",
        (
            f"zoompan=z='{zoom}':x='{x}':y='{y}'"
            f":d={frames}:s={width}x{height}:fps={fps}"
        ),
    ]

    if style.grade == "warm":
        chain.append("colorbalance=rs=.06:gs=.02:bs=-.06")
    elif style.grade == "cool":
        chain.append("colorbalance=rs=-.06:gs=-.01:bs=.08")

    if style.vignette and has_filter("vignette"):
        chain.append("vignette=PI/5")

    if style.grain > 0 and has_filter("noise"):
        chain.append(f"noise=alls={style.grain:.0f}:allf=t+u")

    if style.letterbox > 0:
        bar = int(height * style.letterbox / 2) // 2 * 2
        if bar > 0:
            chain.append(
                f"drawbox=x=0:y=0:w=iw:h={bar}:color=black@1:t=fill,"
                f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black@1:t=fill"
            )

    if style.fade > 0:
        out_start = max(duration - style.fade, 0)
        chain.append(f"fade=t=in:st=0:d={style.fade}")
        chain.append(f"fade=t=out:st={out_start:.2f}:d={style.fade}")

    chain.append("format=yuv420p")

    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-t", f"{duration}", "-i", str(image),
    ]
    if silent_audio:
        cmd += ["-f", "lavfi", "-t", f"{duration}",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]

    cmd += ["-vf", ",".join(chain), "-r", str(fps)]
    if silent_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(dest),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(
            f"Could not animate {image.name}:\n{proc.stderr.strip()[-1200:]}"
        )
    return dest


def crossblend_stills(
    images: list[Path],
    dest: Path,
    *,
    duration: float = 10.0,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    style: MotionStyle | None = None,
    seed: int = 0,
) -> Path:
    """Animate several stills of the same scene into one clip.

    Generating 2-3 images per scene and dissolving between them adds real
    change inside a shot, which a single still cannot give. Costs nothing
    extra when the image source is free.
    """
    images = [Path(i) for i in images]
    if not images:
        raise FFmpegError("No images supplied")
    if len(images) == 1:
        return animate_still(
            images[0], dest, duration=duration, width=width, height=height,
            fps=fps, style=style, seed=seed,
        )

    style = style or MotionStyle()
    per = duration / len(images)
    tmpdir = dest.parent / f".{dest.stem}_parts"
    tmpdir.mkdir(parents=True, exist_ok=True)

    parts = []
    try:
        for i, img in enumerate(images):
            part = tmpdir / f"part_{i:02d}.mp4"
            animate_still(
                img, part,
                duration=per + (0.6 if i < len(images) - 1 else 0),
                width=width, height=height, fps=fps,
                style=MotionStyle(
                    intensity=style.intensity, grain=style.grain,
                    vignette=style.vignette, letterbox=style.letterbox,
                    fade=0.0, grade=style.grade,
                ),
                seed=seed + i,
            )
            parts.append(part)

        from soulclip.ffmpeg import concat

        concat(parts, dest, width=width, height=height, fps=fps, crossfade=0.5)
    finally:
        for p in parts:
            p.unlink(missing_ok=True)
        tmpdir.rmdir() if tmpdir.exists() and not any(tmpdir.iterdir()) else None

    return dest

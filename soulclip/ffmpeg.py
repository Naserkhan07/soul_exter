"""Locating ffmpeg and stitching clips together."""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Find an ffmpeg binary: PATH first, then the imageio-ffmpeg bundle."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - depends on environment
        pass
    raise FFmpegError(
        "ffmpeg not found. Install it with your package manager, or run "
        "`pip install imageio-ffmpeg` to get a bundled static build."
    )


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    """ffprobe if available — optional, used only for duration reporting."""
    return shutil.which("ffprobe")


@lru_cache(maxsize=1)
def _filters() -> frozenset[str]:
    """Names of every filter this ffmpeg build supports."""
    try:
        out = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:  # pragma: no cover - depends on environment
        return frozenset()

    names = set()
    for line in out.splitlines():
        parts = line.split()
        # Rows look like: " TQC t->v  drawtext  Draw text on top of video."
        if len(parts) >= 3 and not line.startswith(("Filters:", " ---")):
            names.add(parts[1])
    return frozenset(names)


def has_filter(name: str) -> bool:
    """True if this ffmpeg build has *name*.

    Static builds often ship without ``drawtext`` because it needs
    libfreetype, so anything optional should be probed before use.
    """
    return name in _filters()


def run(cmd: Sequence[str], *, what: str = "ffmpeg") -> subprocess.CompletedProcess:
    proc = subprocess.run(list(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"{what} failed:\n{proc.stderr.strip()[-1500:]}")
    return proc


def probe_duration(path: Path) -> float | None:
    """Duration of a media file in seconds, or None if it can't be read."""
    probe = ffprobe_path()
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", str(path)],
                capture_output=True, text=True, check=True,
            ).stdout
            return float(json.loads(out)["format"]["duration"])
        except Exception:
            return None

    # No ffprobe: parse ffmpeg's own report of the input.
    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in proc.stderr.splitlines():
            if "Duration:" in line:
                stamp = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = stamp.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None
    return None


def has_audio(path: Path) -> bool:
    """True if *path* carries at least one audio stream.

    Clips from different models are inconsistent here — some ship silent
    video, some include a soundtrack. The concat filter needs to know in
    advance so it can substitute silence and keep the streams aligned.
    """
    probe = ffprobe_path()
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "json", str(path)],
                capture_output=True, text=True, check=True,
            ).stdout
            return bool(json.loads(out).get("streams"))
        except Exception:
            return False

    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-i", str(path)], capture_output=True, text=True
        )
        return "Audio:" in proc.stderr
    except Exception:
        return False


def is_valid_video(path: Path, *, min_bytes: int = 1024) -> bool:
    """Cheap sanity check that a downloaded clip is really playable."""
    if not path.exists() or path.stat().st_size < min_bytes:
        return False
    duration = probe_duration(path)
    return duration is None or duration > 0.05


def concat(
    clips: Iterable[Path],
    output: Path,
    *,
    reencode: bool = True,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    crossfade: float = 0.0,
    audio: Path | None = None,
    progress: bool = False,
) -> Path:
    """Join *clips* into a single file at *output*.

    Args:
        reencode: Normalise every clip to the same codec/size/fps before
            joining. Slower, but the only reliable option when clips come
            from different models. Set False for a fast stream copy when
            you know they already match.
        crossfade: Seconds of cross-dissolve between clips (needs reencode).
        audio: Optional music/narration track mixed over the final cut.
    """
    clips = [Path(c) for c in clips]
    if not clips:
        raise FFmpegError("No clips to join")
    missing = [c for c in clips if not c.exists()]
    if missing:
        raise FFmpegError(f"Missing clips: {', '.join(str(m) for m in missing)}")

    output.parent.mkdir(parents=True, exist_ok=True)

    if len(clips) == 1 and not audio and not crossfade:
        shutil.copyfile(clips[0], output)
        return output

    if crossfade > 0:
        return _concat_crossfade(
            clips, output, width=width, height=height, fps=fps,
            crossfade=crossfade, audio=audio,
        )
    if reencode:
        return _concat_filter(
            clips, output, width=width, height=height, fps=fps, audio=audio,
            progress=progress,
        )
    return _concat_demuxer(clips, output, audio=audio)


def _concat_demuxer(clips: list[Path], output: Path, *, audio: Path | None) -> Path:
    """Fast path: stream copy via the concat demuxer."""
    listfile = output.parent / f".{output.stem}_concat.txt"
    listfile.write_text(
        "\n".join(f"file '{c.resolve().as_posix()}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listfile),
    ]
    if audio:
        cmd += ["-i", str(audio), "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    cmd += ["-movflags", "+faststart", str(output)]

    try:
        run(cmd, what="concat (stream copy)")
    finally:
        listfile.unlink(missing_ok=True)
    return output


def _scale_chain(width: int, height: int, fps: int) -> str:
    """Letterbox to a fixed canvas without distorting the picture."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )


def _concat_filter(
    clips: list[Path], output: Path, *, width: int, height: int, fps: int,
    audio: Path | None, progress: bool = False,
) -> Path:
    """Normalise then concat. Handles mixed sizes, fps and missing audio.

    Every clip is letterboxed to the same canvas and resampled to a common
    audio format. Clips that carry no audio get their own silent source of
    matching length, which keeps the video and audio stream counts equal —
    a hard requirement of the concat filter.
    """
    audio_flags = [has_audio(c) for c in clips]

    cmd = [ffmpeg_path(), "-y", "-hide_banner",
           "-loglevel", "info" if progress else "error"]
    for clip in clips:
        cmd += ["-i", str(clip)]

    # One dedicated silence input per silent clip. Sharing a single
    # anullsrc between several concat segments does not work.
    silence_index: dict[int, int] = {}
    next_input = len(clips)
    for i, clip in enumerate(clips):
        if audio_flags[i]:
            continue
        seconds = probe_duration(clip) or 10.0
        cmd += [
            "-f", "lavfi",
            "-t", f"{seconds:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
        silence_index[i] = next_input
        next_input += 1

    chain = _scale_chain(width, height, fps)
    aformat = ("aformat=sample_fmts=fltp:sample_rates=48000:"
               "channel_layouts=stereo")

    parts: list[str] = []
    streams = ""
    for i in range(len(clips)):
        parts.append(f"[{i}:v]{chain}[v{i}]")
        src = f"[{i}:a]" if audio_flags[i] else f"[{silence_index[i]}:a]"
        parts.append(f"{src}aresample=async=1:first_pts=0,{aformat}[a{i}]")
        streams += f"[v{i}][a{i}]"

    parts.append(f"{streams}concat=n={len(clips)}:v=1:a=1[vout][aout]")

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ]

    run(cmd, what="concat")
    return output


#: Above this many inputs, a single chained xfade graph exhausts memory,
#: so the crossfade is done in batches and the batches joined afterwards.
CROSSFADE_BATCH = 24


def _concat_crossfade(
    clips: list[Path], output: Path, *, width: int, height: int, fps: int,
    crossfade: float, audio: Path | None,
) -> Path:
    """Chain xfade between every pair of clips.

    ffmpeg opens every input at once and the xfade chain grows one filter
    per clip, so a long film (a 5-minute cut is 60+ shots) can be killed by
    the OOM reaper mid-render. Past :data:`CROSSFADE_BATCH` inputs the work
    is split into batches that are crossfaded separately and then joined,
    which keeps peak memory flat regardless of film length.
    """
    if len(clips) > CROSSFADE_BATCH:
        return _concat_crossfade_batched(
            clips, output, width=width, height=height, fps=fps,
            crossfade=crossfade, audio=audio,
        )
    return _concat_crossfade_single(
        clips, output, width=width, height=height, fps=fps,
        crossfade=crossfade, audio=audio,
    )


def _concat_crossfade_batched(
    clips: list[Path], output: Path, *, width: int, height: int, fps: int,
    crossfade: float, audio: Path | None,
) -> Path:
    """Crossfade in batches, then join the batches (also with a crossfade)."""
    tmpdir = output.parent / f".{output.stem}_xf"
    tmpdir.mkdir(parents=True, exist_ok=True)
    batches: list[Path] = []

    try:
        for start in range(0, len(clips), CROSSFADE_BATCH):
            chunk = clips[start : start + CROSSFADE_BATCH]
            part = tmpdir / f"batch_{start // CROSSFADE_BATCH:03d}.mp4"
            if len(chunk) == 1:
                shutil.copyfile(chunk[0], part)
            else:
                _concat_crossfade_single(
                    chunk, part, width=width, height=height, fps=fps,
                    crossfade=crossfade, audio=None,
                )
            batches.append(part)

        if len(batches) == 1:
            shutil.copyfile(batches[0], output)
        else:
            # Recurses only if there are still too many batches.
            _concat_crossfade(
                batches, output, width=width, height=height, fps=fps,
                crossfade=crossfade, audio=audio,
            )
    finally:
        for b in batches:
            b.unlink(missing_ok=True)
        if tmpdir.exists() and not any(tmpdir.iterdir()):
            tmpdir.rmdir()

    return output


def _concat_crossfade_single(
    clips: list[Path], output: Path, *, width: int, height: int, fps: int,
    crossfade: float, audio: Path | None,
) -> Path:
    """One xfade chain across every clip. Caller keeps the count sane."""
    durations = []
    for clip in clips:
        d = probe_duration(clip)
        if d is None:
            raise FFmpegError(
                f"Need the duration of {clip.name} for crossfades but could "
                "not read it. Re-run without --crossfade."
            )
        durations.append(d)

    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        cmd += ["-i", str(clip)]

    chain = _scale_chain(width, height, fps)
    parts = [f"[{i}:v]{chain}[v{i}]" for i in range(len(clips))]

    current = "[v0]"
    offset = durations[0] - crossfade
    for i in range(1, len(clips)):
        out = f"[x{i}]" if i < len(clips) - 1 else "[vout]"
        parts.append(
            f"{current}[v{i}]xfade=transition=fade:duration={crossfade}:"
            f"offset={max(offset, 0):.3f}{out}"
        )
        current = out
        offset += durations[i] - crossfade

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]"]
    if audio:
        cmd += ["-i", str(audio), "-map", f"{len(clips)}:a", "-c:a", "aac",
                "-b:a", "192k", "-shortest"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip()[-1200:]
        if proc.returncode < 0:
            detail = (
                f"ffmpeg was killed by signal {-proc.returncode} — most "
                "likely out of memory. Try fewer clips per batch or drop "
                "--crossfade."
            )
        raise FFmpegError(f"crossfade concat failed:\n{detail}")
    return output


def add_audio(video: Path, audio: Path, output: Path, *, volume: float = 1.0) -> Path:
    """Mix a soundtrack over an existing video."""
    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(audio),
        "-filter_complex",
        f"[1:a]volume={volume}[music];[0:a][music]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(output),
    ]
    run(cmd, what="audio mix")
    return output

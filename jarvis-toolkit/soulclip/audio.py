"""Narration and background audio for the finished film.

Three layers, all optional:

narration
    Text-to-speech per scene, timed to that scene's clip. Kokoro is the
    default — it is small, fast, permissively licensed and runs on CPU.
music
    A soundtrack laid under the whole film, ducked beneath narration so
    the words stay intelligible.
ambience
    A looping bed (rain, sea, room tone) mixed below the music.

Everything mixes through ffmpeg, so nothing here needs a GPU.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from soulclip.ffmpeg import FFmpegError, ffmpeg_path, probe_duration


class AudioError(RuntimeError):
    pass


@dataclass
class AudioMix:
    """Levels for the final mix, in linear gain (1.0 = unchanged)."""

    narration: float = 1.0
    music: float = 0.18
    ambience: float = 0.12
    #: How far music/ambience drop while narration plays.
    duck: float = 0.35
    #: Fade applied to music at the start and end, in seconds.
    fade: float = 2.0


# --------------------------------------------------------------------------
# Text to speech
# --------------------------------------------------------------------------

class Narrator:
    """Generate speech for scene text.

    Kokoro (``pip install kokoro soundfile``) is an 82M-parameter TTS model
    with an Apache licence that runs comfortably on CPU — roughly real time
    on two cores, so narration is never the bottleneck.
    """

    def __init__(self, voice: str = "af_heart", lang: str = "a",
                 speed: float = 1.0) -> None:
        self.voice = voice
        self.lang = lang
        self.speed = speed
        self._pipeline = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise AudioError(
                "Narration needs Kokoro:\n"
                "  pip install kokoro soundfile\n"
                "On Linux also: apt-get install espeak-ng\n"
                f"({exc})"
            ) from exc
        self._pipeline = KPipeline(lang_code=self.lang)
        return self._pipeline

    def speak(self, text: str, dest: Path) -> Path:
        """Synthesise *text* to a wav at *dest*."""
        try:
            import numpy as np
            import soundfile as sf
        except ImportError as exc:
            # Raised as AudioError so callers can keep the silent film
            # rather than losing the whole render to a missing dependency.
            raise AudioError(
                "Narration needs numpy and soundfile:\n"
                "  pip install kokoro soundfile\n"
                f"({exc})"
            ) from exc

        pipeline = self._load()
        dest.parent.mkdir(parents=True, exist_ok=True)

        chunks = [
            audio for _, _, audio in
            pipeline(text, voice=self.voice, speed=self.speed)
        ]
        if not chunks:
            raise AudioError(f"Kokoro produced no audio for {text[:60]!r}")

        sf.write(str(dest), np.concatenate(chunks), 24000)
        return dest


def fit_to_duration(audio: Path, seconds: float, dest: Path,
                    *, max_speedup: float = 1.4) -> Path:
    """Pad or gently speed up *audio* so it lands in *seconds*.

    Narration that overruns its clip would bleed into the next scene, so it
    is time-compressed — but only up to *max_speedup*, past which speech
    starts sounding comical. Beyond that it is simply truncated.
    """
    have = probe_duration(audio) or 0.0
    if have <= 0:
        raise AudioError(f"Could not read the duration of {audio}")

    ff = ffmpeg_path()
    if have <= seconds:
        # Pad with silence to fill the clip.
        cmd = [ff, "-y", "-v", "error", "-i", str(audio),
               "-af", f"apad=whole_dur={seconds}", "-t", str(seconds),
               str(dest)]
    else:
        ratio = min(have / seconds, max_speedup)
        cmd = [ff, "-y", "-v", "error", "-i", str(audio),
               "-af", f"atempo={ratio:.4f},apad=whole_dur={seconds}",
               "-t", str(seconds), str(dest)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"Could not fit narration: {proc.stderr[-400:]}")
    return dest


def narrate_scenes(
    scenes,
    workdir: Path,
    *,
    narrator: Narrator | None = None,
    reporter=None,
) -> dict[int, Path]:
    """Generate one narration track per scene, timed to its clip.

    Returns ``{scene_index: wav_path}``. Existing files are reused, so an
    interrupted run resumes like the video side does.
    """
    narrator = narrator or Narrator()
    out_dir = workdir / "narration"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = reporter or (lambda m: None)

    tracks: dict[int, Path] = {}
    for scene in scenes:
        fitted = out_dir / f"{scene.slug}.wav"
        if fitted.exists() and (probe_duration(fitted) or 0) > 0.1:
            tracks[scene.index] = fitted
            continue

        raw = out_dir / f"{scene.slug}_raw.wav"
        report(f"narrating {scene.label}")
        # Strip the instructions we add for the video model; they are not
        # part of the story and should never be read aloud.
        spoken = _speakable(scene.text)
        if not spoken:
            continue
        narrator.speak(spoken, raw)
        fit_to_duration(raw, scene.duration, fitted)
        raw.unlink(missing_ok=True)
        tracks[scene.index] = fitted

    return tracks


def _speakable(text: str) -> str:
    """Remove camera and style directions before reading a line aloud."""
    import re

    text = re.split(r"\bSetting:\s*", text)[0]
    text = re.sub(r"Continuous shot.*?$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(cinematic|anime|film grain|dramatic lighting|handheld|"
        r"slow dolly in|pan left|pan right|static wide|4k|8k)\b[ ,]*",
        "", text, flags=re.IGNORECASE,
    )
    return " ".join(text.split()).strip(" ,.") or ""


# --------------------------------------------------------------------------
# Mixing
# --------------------------------------------------------------------------

def concat_narration(tracks: list[Path], dest: Path) -> Path:
    """Join per-scene narration into one track matching the film."""
    if not tracks:
        raise AudioError("No narration tracks to join")

    ff = ffmpeg_path()
    cmd = [ff, "-y", "-v", "error"]
    for track in tracks:
        cmd += ["-i", str(track)]
    filt = "".join(f"[{i}:a]" for i in range(len(tracks)))
    filt += f"concat=n={len(tracks)}:v=0:a=1[out]"
    cmd += ["-filter_complex", filt, "-map", "[out]", str(dest)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"Could not join narration: {proc.stderr[-400:]}")
    return dest


def mix(
    video: Path,
    dest: Path,
    *,
    narration: Path | None = None,
    music: Path | None = None,
    ambience: Path | None = None,
    levels: AudioMix | None = None,
) -> Path:
    """Lay narration, music and ambience over *video*.

    Music and ambience are looped to the film's length and side-chain ducked
    under the narration, so dialogue stays clear without manual level
    riding.
    """
    levels = levels or AudioMix()
    if not (narration or music or ambience):
        raise AudioError("Nothing to mix")

    length = probe_duration(video)
    if not length:
        raise FFmpegError(f"Could not read the duration of {video}")

    ff = ffmpeg_path()
    cmd = [ff, "-y", "-v", "error", "-i", str(video)]
    parts: list[str] = []
    labels: list[str] = []
    idx = 1

    if narration:
        cmd += ["-i", str(narration)]
        parts.append(f"[{idx}:a]volume={levels.narration},"
                     f"aresample=48000[narr]")
        labels.append("[narr]")
        narr_idx = idx
        idx += 1
    else:
        narr_idx = None

    for path, gain, name in (
        (music, levels.music, "music"),
        (ambience, levels.ambience, "amb"),
    ):
        if not path:
            continue
        cmd += ["-stream_loop", "-1", "-i", str(path)]
        chain = (f"[{idx}:a]atrim=0:{length:.2f},volume={gain},"
                 f"aresample=48000")
        if levels.fade > 0:
            chain += (f",afade=t=in:st=0:d={levels.fade}"
                      f",afade=t=out:st={max(length - levels.fade, 0):.2f}"
                      f":d={levels.fade}")
        if narr_idx is not None:
            # Duck under narration using it as the sidechain key.
            parts.append(f"{chain}[{name}pre]")
            parts.append(
                f"[{name}pre][narrkey{name}]sidechaincompress="
                f"threshold=0.05:ratio={1 / max(levels.duck, 0.01):.1f}"
                f":attack=20:release=400[{name}]"
            )
            parts.append(f"[{narr_idx}:a]asplit=1[narrkey{name}]")
        else:
            parts.append(f"{chain}[{name}]")
        labels.append(f"[{name}]")
        idx += 1

    if len(labels) > 1:
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}"
                     f":duration=first:dropout_transition=0[aout]")
        out_label = "[aout]"
    else:
        out_label = labels[0]

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "0:v", "-map", out_label,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(dest),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"Audio mix failed:\n{proc.stderr[-800:]}")
    return dest

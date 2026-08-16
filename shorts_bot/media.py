from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .errors import ConfigurationError, MediaError


class MediaProcessor:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def check_tools(self) -> None:
        missing = [tool for tool in (self.ffmpeg, self.ffprobe) if shutil.which(tool) is None]
        if missing:
            raise ConfigurationError(
                f"Missing media tools: {', '.join(missing)}. Install FFmpeg and ffprobe."
            )

    def probe_duration(self, path: Path) -> float:
        result = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ]
        )
        try:
            return float(json.loads(result.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaError(f"Could not read media duration for {path.name}.") from exc

    def extract_audio(self, source: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                str(output),
            ],
            timeout=1800,
        )
        return output

    def render_short(
        self,
        source: Path,
        output: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Fill a 9:16 frame. Landscape sources are center-cropped; no stretching is applied.
        video_filter = (
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"
        )
        command = [
            self.ffmpeg,
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-i",
            str(source),
            "-t",
            f"{duration_seconds:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output),
        ]
        self._run(command, timeout=1800)
        if not output.exists() or output.stat().st_size == 0:
            raise MediaError("FFmpeg did not create the Short.")
        return output

    def generate_thumbnail(self, video: Path, output: Path, at_seconds: float) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_filter = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1280:720:force_original_aspect_ratio=increase,"
            "crop=1280:720,boxblur=20:2[blurred];"
            "[fg]scale=1280:720:force_original_aspect_ratio=decrease[front];"
            "[blurred][front]overlay=(W-w)/2:(H-h)/2"
        )
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-ss",
                f"{max(0, at_seconds):.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-filter_complex",
                thumbnail_filter,
                "-q:v",
                "3",
                str(output),
            ],
            timeout=180,
        )
        if not output.exists() or output.stat().st_size == 0:
            raise MediaError("FFmpeg did not create the thumbnail.")
        return output

    @staticmethod
    def _run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise ConfigurationError(f"Required command {command[0]!r} was not found.") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaError(f"Media command timed out after {timeout} seconds.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "Unknown FFmpeg error").strip()[-1500:]
            raise MediaError(f"Media processing failed: {detail}") from exc

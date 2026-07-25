"""Video generation backends.

Each provider takes a text prompt and returns a finished clip on disk.
The pipeline only relies on :meth:`VideoProvider.generate`, so adding a new
service means writing one small class.

Built in:
    replicate  — Replicate predictions API (Kling, Wan, Veo, Seedance, ...)
    fal        — fal.ai queue API
    xai        — xAI Grok Imagine video
    command    — shell out to any local tool / your own script
    mock       — offline colour-bars generator, for testing the pipeline

Only the stdlib is used, so there is nothing to install.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from soulclip.ffmpeg import ffmpeg_path, has_filter

UserAgent = "soulclip/0.1"


class ProviderError(RuntimeError):
    """A provider failed in a way the pipeline should report."""


class AuthError(ProviderError):
    """Missing or rejected credentials — retrying will not help."""


class PermanentError(ProviderError):
    """A misconfiguration that every retry will hit again.

    Raised for things like an unsupported ffmpeg build, a bad model name or
    a malformed command template. The pipeline reports these immediately
    instead of burning the retry budget on a guaranteed failure.
    """


@dataclass
class GenerationResult:
    path: Path
    provider: str
    model: str
    remote_id: str | None = None
    raw: dict | None = None


# --------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# --------------------------------------------------------------------------

def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: int = 60,
) -> dict:
    data = None
    headers = dict(headers or {})
    headers.setdefault("User-Agent", UserAgent)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        if exc.code in (401, 403):
            raise AuthError(f"{exc.code} from {url}: {detail}") from exc
        raise ProviderError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"Could not reach {url}: {exc.reason}") from exc

    return json.loads(payload) if payload.strip() else {}


def download(url: str, dest: Path, *, timeout: int = 300) -> Path:
    """Stream a URL to *dest*, writing to a temp file first."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UserAgent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        tmp.unlink(missing_ok=True)
        raise ProviderError(f"Download failed for {url}: {exc}") from exc

    if tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise ProviderError(f"Downloaded an empty file from {url}")

    tmp.replace(dest)
    return dest


def _find_video_url(payload: Any) -> str | None:
    """Dig a video URL out of an arbitrarily shaped API response."""
    if isinstance(payload, str):
        low = payload.split("?")[0].lower()
        if payload.startswith("http") and low.endswith(
            (".mp4", ".webm", ".mov", ".m4v")
        ):
            return payload
        if payload.startswith("http") and "video" in payload.lower():
            return payload
        return None

    if isinstance(payload, dict):
        # Common keys first, so we prefer the real output over thumbnails.
        for key in ("video", "output", "url", "video_url", "mp4", "file", "result"):
            if key in payload:
                found = _find_video_url(payload[key])
                if found:
                    return found
        for value in payload.values():
            found = _find_video_url(value)
            if found:
                return found
        return None

    if isinstance(payload, (list, tuple)):
        for item in payload:
            found = _find_video_url(item)
            if found:
                return found
    return None


# --------------------------------------------------------------------------
# Base class
# --------------------------------------------------------------------------

class VideoProvider(ABC):
    name = "base"
    #: Clip lengths the service accepts; None means anything goes.
    supported_durations: tuple[int, ...] | None = None

    def __init__(self, model: str | None = None, **options: Any) -> None:
        self.model = model or self.default_model
        self.options = options

    default_model = ""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        duration: int = 10,
        on_status: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        """Generate one clip for *prompt* and save it to *dest*."""

    def normalize_duration(self, duration: int) -> int:
        """Snap a requested duration to what the service actually supports."""
        if not self.supported_durations:
            return duration
        return min(self.supported_durations, key=lambda d: (abs(d - duration), d))

    @staticmethod
    def _token(*env_names: str) -> str:
        for name in env_names:
            value = os.environ.get(name)
            if value:
                return value.strip()
        raise AuthError(
            f"Set one of these environment variables: {', '.join(env_names)}"
        )


# --------------------------------------------------------------------------
# Replicate
# --------------------------------------------------------------------------

class ReplicateProvider(VideoProvider):
    """Replicate's async predictions API.

    Works with any text-to-video model on Replicate; swap the model string.
    """

    name = "replicate"
    default_model = "kwaivgi/kling-v1.6-standard"
    supported_durations = (5, 10)
    api_root = "https://api.replicate.com/v1"

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        token = self._token("REPLICATE_API_TOKEN", "REPLICATE_API_KEY")
        headers = {"Authorization": f"Bearer {token}"}
        duration = self.normalize_duration(duration)

        payload: dict[str, Any] = {
            "input": {
                "prompt": prompt,
                "duration": duration,
                **self.options.get("input", {}),
            }
        }

        # Official models use /models/<owner>/<name>/predictions; pinned
        # versions use /predictions with a "version" field.
        if ":" in self.model or len(self.model) == 64:
            version = self.model.split(":")[-1]
            payload["version"] = version
            url = f"{self.api_root}/predictions"
        else:
            url = f"{self.api_root}/models/{self.model}/predictions"

        prediction = _request(url, method="POST", headers=headers, body=payload)
        pred_id = prediction.get("id")
        if not pred_id:
            raise ProviderError(f"Replicate did not return a prediction id: {prediction}")

        poll_url = f"{self.api_root}/predictions/{pred_id}"
        deadline = time.time() + int(self.options.get("timeout", 900))
        interval = float(self.options.get("poll_interval", 5))

        while True:
            status = prediction.get("status")
            if status == "succeeded":
                break
            if status in ("failed", "canceled"):
                raise ProviderError(
                    f"Replicate prediction {pred_id} {status}: "
                    f"{prediction.get('error') or 'no error detail'}"
                )
            if time.time() > deadline:
                raise ProviderError(f"Replicate prediction {pred_id} timed out")

            if on_status:
                on_status(f"{status} ({pred_id[:8]})")
            time.sleep(interval)
            prediction = _request(poll_url, headers=headers)

        video_url = _find_video_url(prediction.get("output"))
        if not video_url:
            raise ProviderError(
                f"No video URL in Replicate output: {prediction.get('output')!r}"
            )

        download(video_url, dest)
        return GenerationResult(dest, self.name, self.model, pred_id, prediction)


# --------------------------------------------------------------------------
# fal.ai
# --------------------------------------------------------------------------

class FalProvider(VideoProvider):
    """fal.ai queue API."""

    name = "fal"
    default_model = "fal-ai/kling-video/v1.6/standard/text-to-video"
    api_root = "https://queue.fal.run"

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        token = self._token("FAL_KEY", "FAL_API_KEY")
        headers = {"Authorization": f"Key {token}"}

        submit = _request(
            f"{self.api_root}/{self.model}",
            method="POST",
            headers=headers,
            body={
                "prompt": prompt,
                "duration": str(self.normalize_duration(duration)),
                **self.options.get("input", {}),
            },
        )

        status_url = submit.get("status_url")
        response_url = submit.get("response_url")
        request_id = submit.get("request_id")
        if not status_url:
            raise ProviderError(f"fal did not return a status_url: {submit}")

        deadline = time.time() + int(self.options.get("timeout", 900))
        interval = float(self.options.get("poll_interval", 5))

        while True:
            state = _request(status_url, headers=headers)
            status = state.get("status")
            if status == "COMPLETED":
                break
            if status in ("FAILED", "CANCELLED", "ERROR"):
                raise ProviderError(f"fal request {request_id} {status}: {state}")
            if time.time() > deadline:
                raise ProviderError(f"fal request {request_id} timed out")
            if on_status:
                on_status(f"{status.lower()} ({str(request_id)[:8]})")
            time.sleep(interval)

        result = _request(response_url or status_url, headers=headers)
        video_url = _find_video_url(result)
        if not video_url:
            raise ProviderError(f"No video URL in fal response: {result}")

        download(video_url, dest)
        return GenerationResult(dest, self.name, self.model, request_id, result)


# --------------------------------------------------------------------------
# xAI Grok Imagine
# --------------------------------------------------------------------------

class XaiProvider(VideoProvider):
    """xAI video generations endpoint."""

    name = "xai"
    default_model = "grok-imagine-video"
    api_root = "https://api.x.ai/v1"

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        token = self._token("XAI_API_KEY")
        headers = {"Authorization": f"Bearer {token}"}

        submit = _request(
            f"{self.api_root}/videos/generations",
            method="POST",
            headers=headers,
            body={
                "model": self.model,
                "prompt": prompt,
                "duration": duration,
                "aspect_ratio": self.options.get("aspect_ratio", "16:9"),
                "resolution": self.options.get("resolution", "720p"),
                **self.options.get("input", {}),
            },
        )

        request_id = submit.get("request_id") or submit.get("id")
        if not request_id:
            raise ProviderError(f"xAI did not return a request id: {submit}")

        deadline = time.time() + int(self.options.get("timeout", 900))
        interval = float(self.options.get("poll_interval", 5))

        while True:
            state = _request(f"{self.api_root}/videos/{request_id}", headers=headers)
            status = state.get("status")
            if status == "done":
                break
            if status in ("failed", "expired"):
                raise ProviderError(f"xAI request {request_id} {status}: {state}")
            if time.time() > deadline:
                raise ProviderError(f"xAI request {request_id} timed out")
            if on_status:
                on_status(f"{status} ({str(request_id)[:8]})")
            time.sleep(interval)

        video_url = _find_video_url(state)
        if not video_url:
            raise ProviderError(f"No video URL in xAI response: {state}")

        download(video_url, dest)
        return GenerationResult(dest, self.name, self.model, request_id, state)


# --------------------------------------------------------------------------
# Arbitrary local command
# --------------------------------------------------------------------------

class CommandProvider(VideoProvider):
    """Shell out to any command that writes a clip.

    Set ``SOULCLIP_COMMAND`` to a template using ``{prompt}``, ``{output}``
    and ``{duration}``::

        export SOULCLIP_COMMAND='my-video-cli --text {prompt} --secs {duration} -o {output}'

    Handy for local models (CogVideoX, Wan, LTX) or an in-house wrapper.
    """

    name = "command"
    default_model = "local"

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        import shlex

        template = self.options.get("command") or os.environ.get("SOULCLIP_COMMAND")
        if not template:
            raise PermanentError(
                "Set SOULCLIP_COMMAND to a command template using "
                "{prompt}, {output} and {duration}."
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            piece.format(prompt=prompt, output=str(dest), duration=duration)
            for piece in shlex.split(template)
        ]

        if on_status:
            on_status("running local command")

        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ProviderError(
                f"Command failed ({proc.returncode}): {proc.stderr.strip()[:500]}"
            )
        if not dest.exists():
            raise ProviderError(f"Command finished but {dest} was not created")

        return GenerationResult(dest, self.name, self.model, None, {"argv": argv})


# --------------------------------------------------------------------------
# Mock provider — no network, no API key
# --------------------------------------------------------------------------

class MockProvider(VideoProvider):
    """Render a placeholder clip locally with ffmpeg.

    Every clip shows the scene number and prompt text over a colour that
    changes per scene, so you can watch the finished cut and confirm the
    ordering, timing and stitching are right before spending real money.
    """

    name = "mock"
    default_model = "testsrc"

    PALETTE = [
        "0x1f2a44", "0x3d1f44", "0x44321f", "0x1f4433",
        "0x441f22", "0x24441f", "0x1f3a44", "0x40401f",
    ]

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if on_status:
            on_status("rendering placeholder")

        colour = self.PALETTE[self.options.get("seed", 0) % len(self.PALETTE)]
        text = prompt if len(prompt) <= 220 else prompt[:217] + "..."
        wrapped = _wrap(text, 46)
        label = self.options.get("label", "")

        # drawtext needs its own escaping rules.
        def esc(value: str) -> str:
            for a, b in (("\\", r"\\"), (":", r"\:"), ("'", r"\u0027"),
                         ("%", r"\%"), ("[", r"\["), ("]", r"\]"),
                         (",", r"\,"), (";", r"\;")):
                value = value.replace(a, b)
            return value

        filters = [
            f"drawbox=x=0:y=0:w=iw:h=ih:color={colour}@1:t=fill",
            "drawgrid=w=80:h=80:t=1:c=white@0.06",
        ]

        if has_filter("drawtext"):
            if label:
                filters.append(
                    f"drawtext=text='{esc(label.upper())}':"
                    "fontcolor=white@0.85:fontsize=44:x=60:y=60"
                )
            filters.append(
                f"drawtext=text='{esc(wrapped)}':fontcolor=white@0.95:fontsize=30:"
                "x=60:y=(h-text_h)/2:line_spacing=12"
            )
            filters.append(
                "drawtext=text='%{eif\\:t\\:d}s':fontcolor=white@0.6:fontsize=28:"
                "x=w-tw-60:y=h-th-60"
            )
        else:
            # Static ffmpeg builds are often compiled without libfreetype, so
            # drawtext is unavailable. Fall back to a marker that still makes
            # each clip visually distinct and countable: a scene-numbered bar
            # of blocks plus a sweeping progress line.
            n = self.options.get("seed", 0)
            per_row = 10
            for i in range(min(n, 60)):
                x = 60 + (i % per_row) * 46
                y = 60 + (i // per_row) * 46
                filters.append(
                    f"drawbox=x={x}:y={y}:w=32:h=32:color=white@0.85:t=fill"
                )
            filters.append(
                "drawbox=x=0:y=ih-14:w='iw*t/{d}':h=14:"
                "color=white@0.5:t=fill".format(d=max(duration, 1))
            )

        size = self.options.get("size", "1280x720")
        fps = self.options.get("fps", 24)

        cmd = [
            ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={size}:r={fps}:d={duration}",
            "-f", "lavfi", "-i",
            f"sine=frequency={220 + 40 * (self.options.get('seed', 0) % 8)}:"
            f"duration={duration}",
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-shortest",
            str(dest),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise PermanentError(
                f"Mock render failed: {proc.stderr.strip()[:500]}"
            )

        return GenerationResult(dest, self.name, self.model, None, None)


def _wrap(text: str, width: int) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(text, width)) or text


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

PROVIDERS: dict[str, type[VideoProvider]] = {
    "replicate": ReplicateProvider,
    "fal": FalProvider,
    "xai": XaiProvider,
    "command": CommandProvider,
    "mock": MockProvider,
}


def get_provider(name: str, model: str | None = None, **options: Any) -> VideoProvider:
    try:
        cls = PROVIDERS[name.lower()]
    except KeyError:
        raise ProviderError(
            f"Unknown provider {name!r}. Choose from: {', '.join(sorted(PROVIDERS))}"
        ) from None
    return cls(model=model, **options)

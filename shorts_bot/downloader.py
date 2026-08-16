from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from .errors import DownloadError
from .models import SourceVideo

_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in _ALLOWED_HOSTS


def extract_youtube_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_PATTERN.findall(text):
        candidate = match.rstrip(".,;:!?)]}'\"")
        if is_youtube_url(candidate) and candidate not in urls:
            urls.append(candidate)
    return urls


class VideoDownloader:
    def __init__(self, cookies_from_browser: str = "", browser_profile: str = "") -> None:
        self.cookies_from_browser = cookies_from_browser
        self.browser_profile = browser_profile

    async def download(self, url: str, destination: Path) -> SourceVideo:
        if not is_youtube_url(url):
            raise DownloadError("Only individual youtube.com or youtu.be URLs are accepted.")
        return await asyncio.to_thread(self._download_sync, url, destination)

    @staticmethod
    def _retry_delay(attempt: int) -> int:
        """Use bounded exponential backoff for temporary CDN/network failures."""
        return min(2 ** max(0, attempt - 1), 20)

    @classmethod
    def _download_options(
        cls,
        output_template: str,
        cookies_from_browser: str = "",
        browser_profile: str = "",
    ) -> dict[str, object]:
        options: dict[str, object] = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "overwrites": True,
            # Windows networks and some ISPs intermittently reset YouTube CDN streams.
            # Resume partial files, force IPv4, use small HTTP chunks, and back off.
            "continuedl": True,
            "source_address": "0.0.0.0",
            "socket_timeout": 30,
            "http_chunk_size": 10 * 1024 * 1024,
            "concurrent_fragment_downloads": 1,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 5,
            "retry_sleep_functions": {
                "http": cls._retry_delay,
                "fragment": cls._retry_delay,
                "extractor": cls._retry_delay,
            },
        }
        if cookies_from_browser:
            options["cookiesfrombrowser"] = (
                cookies_from_browser,
                browser_profile or None,
                None,
                None,
            )
        return options

    def _download_sync(self, url: str, destination: Path) -> SourceVideo:
        destination.mkdir(parents=True, exist_ok=True)
        output_template = str(destination / "source.%(ext)s")
        options = self._download_options(
            output_template,
            self.cookies_from_browser,
            self.browser_profile,
        )
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            detail = str(exc)
            if "sign in to confirm" in detail.lower():
                if self.cookies_from_browser:
                    detail = (
                        f"YouTube rejected cookies from {self.cookies_from_browser}. "
                        "Confirm that you are signed in to YouTube in that browser, "
                        "close the browser, and retry."
                    )
                else:
                    detail = (
                        "YouTube requires signed-in browser cookies. Set "
                        "YTDLP_COOKIES_FROM_BROWSER=brave (or your browser) in .env and retry."
                    )
            raise DownloadError(f"YouTube download failed: {detail}") from exc
        except Exception as exc:
            raise DownloadError(f"Unexpected downloader error: {exc}") from exc

        candidates = [
            path
            for path in destination.glob("source.*")
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise DownloadError("The downloader finished but no video file was created.")
        source_path = max(candidates, key=lambda path: path.stat().st_size)
        duration = float(info.get("duration") or 0)
        if duration <= 0:
            raise DownloadError("Could not determine the source video's duration.")
        if duration < 20:
            raise DownloadError("The source video is shorter than the minimum 20-second Short.")

        return SourceVideo(
            path=source_path,
            source_url=str(info.get("webpage_url") or url),
            video_id=str(info.get("id") or "unknown"),
            title=str(info.get("title") or "Untitled video"),
            uploader=str(info.get("uploader") or info.get("channel") or "Unknown creator"),
            duration_seconds=duration,
        )

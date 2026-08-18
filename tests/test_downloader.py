from pathlib import Path

import pytest
import yt_dlp

from shorts_bot.downloader import VideoDownloader, extract_youtube_urls, is_youtube_url


def test_extracts_and_deduplicates_supported_urls() -> None:
    text = (
        "Try https://youtu.be/abc123, then "
        "https://www.youtube.com/watch?v=xyz987. Duplicate: https://youtu.be/abc123"
    )

    assert extract_youtube_urls(text) == [
        "https://youtu.be/abc123",
        "https://www.youtube.com/watch?v=xyz987",
    ]


def test_rejects_lookalike_and_non_http_urls() -> None:
    assert not is_youtube_url("https://youtube.com.evil.example/watch?v=abc")
    assert not is_youtube_url("ftp://youtube.com/watch?v=abc")
    assert not is_youtube_url("https://vimeo.com/123")
    assert is_youtube_url("https://youtube.com/shorts/abc")


def test_download_options_retry_transient_network_failures() -> None:
    options = VideoDownloader._download_options("source.%(ext)s")

    assert options["format"] == "bestvideo+bestaudio"
    assert options["merge_output_format"] == "mkv"
    assert options["source_address"] == "0.0.0.0"
    assert options["continuedl"] is True
    assert options["retries"] == 10
    assert options["fragment_retries"] == 10
    assert options["concurrent_fragment_downloads"] == 1
    assert options["js_runtimes"] == {"deno": {}}
    assert VideoDownloader._retry_delay(1) == 1
    assert VideoDownloader._retry_delay(10) == 20


def test_download_options_can_use_local_browser_cookies() -> None:
    options = VideoDownloader._download_options(
        "source.%(ext)s",
        cookies_from_browser="brave",
        browser_profile="Profile 1",
    )

    assert options["cookiesfrombrowser"] == ("brave", "Profile 1", None, None)


def test_cookie_file_takes_precedence_over_chrome_dpapi_extraction(tmp_path: Path) -> None:
    cookie_file = tmp_path / "youtube-cookies.txt"
    options = VideoDownloader._download_options(
        "source.%(ext)s",
        cookies_from_browser="chrome",
        cookie_file=cookie_file,
    )

    assert options["cookiefile"] == str(cookie_file)
    assert "cookiesfrombrowser" not in options


def test_retries_exact_format_without_cookies_when_cookie_client_hides_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, object]) -> None:
            self.options = options
            calls.append(options)

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, object]:
            assert download is True
            assert url == "https://youtu.be/example"
            if "cookiefile" in self.options:
                raise yt_dlp.utils.DownloadError(
                    "Requested format is not available. Use --list-formats"
                )
            output = Path(str(self.options["outtmpl"]).replace("%(ext)s", "mkv"))
            output.write_bytes(b"source")
            return {
                "duration": 60,
                "webpage_url": url,
                "id": "example",
                "title": "Example",
                "uploader": "Creator",
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    downloader = VideoDownloader(cookie_file=tmp_path / "youtube-cookies.txt")

    source = downloader._download_sync("https://youtu.be/example", tmp_path / "job")

    assert source.path.name == "source.mkv"
    assert len(calls) == 2
    assert calls[0]["format"] == "bestvideo+bestaudio"
    assert calls[1]["format"] == "bestvideo+bestaudio"
    assert "cookiefile" in calls[0]
    assert "cookiefile" not in calls[1]


def test_retries_with_po_token_clients_after_public_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, object]) -> None:
            self.options = options
            calls.append(options)

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, object]:
            if "cookiefile" in self.options:
                raise yt_dlp.utils.DownloadError("Requested format is not available")
            if "extractor_args" not in self.options:
                raise yt_dlp.utils.DownloadError("HTTP Error 403: Forbidden")
            output = Path(str(self.options["outtmpl"]).replace("%(ext)s", "mkv"))
            output.write_bytes(b"source")
            return {
                "duration": 60,
                "webpage_url": url,
                "id": "example",
                "title": "Example",
                "uploader": "Creator",
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    downloader = VideoDownloader(cookie_file=tmp_path / "youtube-cookies.txt")

    source = downloader._download_sync("https://youtu.be/example", tmp_path / "job")

    assert source.path.name == "source.mkv"
    assert len(calls) == 3
    assert calls[2]["format"] == "bestvideo+bestaudio"
    assert "cookiefile" not in calls[2]
    assert calls[2]["extractor_args"] == {"youtube": {"player_client": ["mweb", "web_safari"]}}

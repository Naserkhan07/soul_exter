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

    assert options["source_address"] == "0.0.0.0"
    assert options["continuedl"] is True
    assert options["retries"] == 10
    assert options["fragment_retries"] == 10
    assert options["concurrent_fragment_downloads"] == 1
    assert VideoDownloader._retry_delay(1) == 1
    assert VideoDownloader._retry_delay(10) == 20

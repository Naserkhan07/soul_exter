from pathlib import Path

from shorts_bot.file_queue import LinkFileQueue
from shorts_bot.models import Job, JobStatus, SourceVideo


def test_acknowledges_download_atomically_and_preserves_comments(tmp_path: Path) -> None:
    links_file = tmp_path / "links.txt"
    log_file = tmp_path / "work" / "downloaded.log"
    log_file.parent.mkdir()
    url = "https://youtu.be/example"
    links_file.write_text(
        f"# queue\n\n{url}\nhttps://youtu.be/next\n{url}\n",
        encoding="utf-8",
    )
    queue = LinkFileQueue(links_file, log_file)
    job = Job(
        id="job123",
        chat_id=0,
        user_id=0,
        source_url=url,
        status=JobStatus.DOWNLOADING,
        progress_message="downloading",
        source_title=None,
        short_title=None,
        short_description=None,
        instagram_caption=None,
        output_path=None,
        youtube_video_id=None,
        instagram_media_id=None,
        instagram_url=None,
        archive_path=None,
        error=None,
        created_at="now",
        updated_at="now",
    )
    source = SourceVideo(Path("source.mp4"), url, "example", "Video title", "Creator", 60)

    assert queue.pending_urls() == [url, "https://youtu.be/next"]
    queue.acknowledge_download(url, job, source)

    remaining = links_file.read_text(encoding="utf-8")
    assert "# queue" in remaining
    assert url not in remaining
    assert "https://youtu.be/next" in remaining
    log = log_file.read_text(encoding="utf-8")
    assert "job123" in log
    assert url in log
    assert "Video title" in log

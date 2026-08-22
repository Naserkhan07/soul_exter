from pathlib import Path

from shorts_bot.db import JobRepository
from shorts_bot.models import JobStatus, ShortPlan


def test_job_lifecycle(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    job = repository.create(101, 202, "https://youtu.be/example")

    assert job.status == JobStatus.QUEUED
    assert job.archive_path is None
    assert repository.list_recent(202) == [job]

    updated = repository.update(
        job.id,
        status=JobStatus.RENDERING,
        progress_message="Rendering",
        short_title="A title",
    )
    assert updated.status == JobStatus.RENDERING
    assert updated.short_title == "A title"

    assert repository.fail_interrupted() == 1
    failed = repository.get(job.id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.error


def test_saves_and_updates_multiple_clips(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    job = repository.create(0, 0, "https://youtu.be/example")
    plans = [
        ShortPlan(0, 25, "First", "Description 1", "Caption 1"),
        ShortPlan(40, 25, "Second", "Description 2", "Caption 2"),
    ]

    clips = repository.save_plans(job.id, plans)
    updated = repository.update_clip(
        job.id,
        1,
        output_path="short-001.mp4",
        thumbnail_path="thumbnail-001.jpg",
        youtube_video_id="youtube-1",
    )

    assert len(clips) == 2
    assert clips[1].start_seconds == 40
    assert clips[0].metadata_ready is True
    assert clips[0].enhancement_complete is False
    assert updated.output_path == "short-001.mp4"
    assert updated.thumbnail_path == "thumbnail-001.jpg"
    assert updated.youtube_url == "https://youtube.com/shorts/youtube-1"

    previous = repository.reset_clip_media(job.id)
    reset = repository.list_clips(job.id)[0]
    assert previous[0].youtube_video_id == "youtube-1"
    assert reset.metadata_ready is False
    assert reset.output_path is None
    assert reset.thumbnail_path is None
    assert reset.youtube_video_id is None


def test_lists_jobs_with_pending_platform_uploads(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    job = repository.create(0, 0, "https://youtu.be/example")
    repository.save_plans(
        job.id,
        [ShortPlan(0, 25, "First", "Description", "Caption")],
    )
    repository.update_clip(
        job.id,
        1,
        output_path="short-001.mp4",
        youtube_video_id="youtube-id",
    )
    repository.update(job.id, status=JobStatus.COMPLETE)

    assert repository.pending_upload_counts() == {
        "YouTube": 0,
        "Instagram": 1,
        "Facebook": 1,
    }
    assert repository.list_pending_upload_jobs(youtube=True, instagram=False, facebook=False) == []
    assert repository.list_pending_upload_jobs(youtube=False, instagram=True, facebook=False) == [
        repository.get(job.id)
    ]
    assert repository.list_pending_upload_jobs(youtube=False, instagram=False, facebook=True) == [
        repository.get(job.id)
    ]

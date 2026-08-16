from pathlib import Path

from shorts_bot.db import JobRepository
from shorts_bot.models import JobStatus


def test_job_lifecycle(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    job = repository.create(101, 202, "https://youtu.be/example")

    assert job.status == JobStatus.QUEUED
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

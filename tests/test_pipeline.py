from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.models import JobStatus, ShortPlan, SourceVideo
from shorts_bot.pipeline import WorkflowPipeline, WorkflowServices


class FakeDownloader:
    async def download(self, url: str, destination: Path) -> SourceVideo:
        destination.mkdir(parents=True, exist_ok=True)
        source_path = destination / "source.mp4"
        source_path.write_bytes(b"source")
        return SourceVideo(source_path, url, "id", "Source title", "Creator", 90)


class FakeMedia:
    def extract_audio(self, source: Path, output: Path) -> Path:
        output.write_bytes(b"audio")
        return output

    def render_short(
        self, source: Path, output: Path, start_seconds: float, duration_seconds: float
    ) -> Path:
        assert start_seconds == 10
        assert duration_seconds == 25
        output.write_bytes(b"rendered")
        return output


class FakePlanner:
    async def create_plan(self, audio_path: Path, source: SourceVideo) -> ShortPlan:
        assert audio_path.exists()
        return ShortPlan(10, 25, "Short title", "Description #Shorts")


class FakeUploader:
    async def upload(self, video_path: Path, plan: ShortPlan) -> str:
        assert video_path.read_bytes() == b"rendered"
        return "youtube-id"


def settings_for(tmp_path: Path) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        openai_api_key="key",
        rights_acknowledged=True,
        auto_upload=True,
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
        youtube_token_file=tmp_path / "token.json",
    )


async def test_pipeline_completes_and_uploads(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(1, 2, "https://youtu.be/example")
    statuses: list[JobStatus] = []

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        statuses.append(updated.status)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        uploader=FakeUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services, notify)

    result = await pipeline.process(job.id)

    assert result.status == JobStatus.COMPLETE
    assert result.youtube_video_id == "youtube-id"
    assert result.short_title == "Short title"
    assert statuses == [
        JobStatus.DOWNLOADING,
        JobStatus.ANALYZING,
        JobStatus.RENDERING,
        JobStatus.UPLOADING,
        JobStatus.COMPLETE,
    ]

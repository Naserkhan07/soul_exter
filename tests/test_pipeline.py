from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.models import (
    InstagramUploadResult,
    JobStatus,
    ShortPlan,
    SourceVideo,
)
from shorts_bot.pipeline import WorkflowPipeline, WorkflowServices


class FakeDownloader:
    async def download(self, url: str, destination: Path) -> SourceVideo:
        destination.mkdir(parents=True, exist_ok=True)
        source_path = destination / "source.mp4"
        source_path.write_bytes(b"source")
        return SourceVideo(source_path, url, "id", "Source title", "Creator", 90)


class FakeMedia:
    def probe_duration(self, source: Path) -> float:
        return 90

    def extract_audio(self, source: Path, output: Path) -> Path:
        output.write_bytes(b"audio")
        return output

    def generate_thumbnail(self, video: Path, output: Path, at_seconds: float) -> Path:
        output.write_bytes(b"thumbnail")
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
        return ShortPlan(
            10,
            25,
            "Short title #Shorts",
            "Description #Shorts",
            "Instagram caption #Reels",
        )

    async def create_plans(
        self,
        audio_path: Path,
        source: SourceVideo,
        max_clips: int,
    ) -> list[ShortPlan]:
        return [await self.create_plan(audio_path, source)]

    async def create_full_coverage_plans(
        self,
        audio_path: Path,
        source: SourceVideo,
        max_clips: int,
    ) -> list[ShortPlan]:
        return await self.create_plans(audio_path, source, max_clips)


class FakeYouTubeUploader:
    async def upload(
        self,
        video_path: Path,
        plan: ShortPlan,
        thumbnail_path: Path | None = None,
    ) -> str:
        assert video_path.read_bytes() == b"rendered"
        assert thumbnail_path and thumbnail_path.read_bytes() == b"thumbnail"
        return "youtube-id"


class FakeInstagramUploader:
    async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
        assert plan.instagram_caption == "Instagram caption #Reels"
        return InstagramUploadResult("instagram-id", "https://instagram.com/reel/example")


def settings_for(tmp_path: Path) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        groq_api_key="key",
        rights_acknowledged=True,
        upload_youtube=True,
        upload_instagram=True,
        youtube_channel_id="UC123",
        instagram_user_id="1789",
        instagram_access_token="token",
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
        youtube_token_file=tmp_path / "token.json",
    )


async def test_pipeline_completes_and_uploads_to_both_platforms(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(1, 2, "https://youtu.be/example")
    statuses: list[JobStatus] = []
    downloaded: list[str] = []

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        statuses.append(updated.status)

    async def on_download(updated, source: SourceVideo) -> None:  # noqa: ANN001
        downloaded.append(updated.source_url)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services, notify, on_download)

    result = await pipeline.process(job.id)

    assert result.status == JobStatus.COMPLETE
    assert result.youtube_video_id == "youtube-id"
    assert result.instagram_media_id == "instagram-id"
    assert result.instagram_url == "https://instagram.com/reel/example"
    assert result.short_title == "Short title #Shorts"
    assert downloaded == ["https://youtu.be/example"]
    assert statuses == [
        JobStatus.DOWNLOADING,
        JobStatus.ANALYZING,
        JobStatus.RENDERING,
        JobStatus.UPLOADING,
        JobStatus.UPLOADING,
        JobStatus.COMPLETE,
    ]


async def test_pipeline_renders_and_uploads_multiple_clips(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    class MultiPlanner:
        async def create_plans(
            self, audio_path: Path, source: SourceVideo, max_clips: int
        ) -> list[ShortPlan]:
            return [
                ShortPlan(0, 25, "First #Shorts", "First", "First #Reels"),
                ShortPlan(40, 25, "Second #Shorts", "Second", "Second #Reels"),
            ]

        async def create_full_coverage_plans(
            self, audio_path: Path, source: SourceVideo, max_clips: int
        ) -> list[ShortPlan]:
            return await self.create_plans(audio_path, source, max_clips)

    class MultiMedia(FakeMedia):
        def render_short(
            self,
            source: Path,
            output: Path,
            start_seconds: float,
            duration_seconds: float,
        ) -> Path:
            output.write_bytes(f"{start_seconds}".encode())
            return output

    class MultiYouTube:
        async def upload(
            self,
            video_path: Path,
            plan: ShortPlan,
            thumbnail_path: Path | None = None,
        ) -> str:
            assert thumbnail_path and thumbnail_path.exists()
            return f"youtube-{plan.start_seconds:g}"

    class MultiInstagram:
        async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
            suffix = f"{plan.start_seconds:g}"
            return InstagramUploadResult(
                f"instagram-{suffix}", f"https://instagram.com/reel/{suffix}"
            )

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=MultiMedia(),  # type: ignore[arg-type]
        planner=MultiPlanner(),  # type: ignore[arg-type]
        youtube_uploader=MultiYouTube(),  # type: ignore[arg-type]
        instagram_uploader=MultiInstagram(),  # type: ignore[arg-type]
    )
    result = await WorkflowPipeline(settings, repository, services).process(job.id)
    clips = repository.list_clips(job.id)

    assert result.status == JobStatus.COMPLETE
    assert len(clips) == 2
    assert clips[0].youtube_video_id == "youtube-0"
    assert clips[1].youtube_video_id == "youtube-40"
    assert clips[1].instagram_media_id == "instagram-40"


async def test_pipeline_can_resume_an_already_downloaded_job(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")
    repository.update(job.id, source_title="Previously downloaded")
    job_dir = settings.work_dir / "jobs" / job.id
    job_dir.mkdir(parents=True)
    (job_dir / "source.mkv").write_bytes(b"existing source")
    statuses: list[JobStatus] = []

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        statuses.append(updated.status)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services, notify)

    result = await pipeline.process(job.id, reuse_downloaded=True)

    assert result.status == JobStatus.COMPLETE
    assert JobStatus.DOWNLOADING not in statuses
    assert statuses[0] == JobStatus.ANALYZING

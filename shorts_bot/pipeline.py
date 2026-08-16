from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

from .ai import AIPlanner
from .config import Settings
from .db import JobRepository
from .downloader import VideoDownloader
from .errors import WorkflowError
from .instagram import InstagramUploader
from .media import MediaProcessor
from .models import Job, JobStatus, SourceVideo
from .youtube import YouTubeUploader

logger = logging.getLogger(__name__)
StatusCallback = Callable[[Job, str], Awaitable[None]]
DownloadedCallback = Callable[[Job, SourceVideo], Awaitable[None]]


@dataclass(slots=True)
class WorkflowServices:
    downloader: VideoDownloader
    media: MediaProcessor
    planner: AIPlanner
    youtube_uploader: YouTubeUploader | None
    instagram_uploader: InstagramUploader | None

    @classmethod
    def from_settings(cls, settings: Settings) -> WorkflowServices:
        return cls(
            downloader=VideoDownloader(),
            media=MediaProcessor(),
            planner=AIPlanner(
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                transcription_model=settings.groq_transcription_model,
                target_duration=settings.clip_duration_seconds,
            ),
            youtube_uploader=(
                YouTubeUploader(
                    token_file=settings.youtube_token_file,
                    privacy_status=settings.youtube_privacy_status,
                    expected_channel_id=settings.youtube_channel_id,
                )
                if settings.upload_youtube
                else None
            ),
            instagram_uploader=(
                InstagramUploader(
                    user_id=settings.instagram_user_id,
                    access_token=settings.instagram_access_token,
                    api_version=settings.instagram_graph_api_version,
                )
                if settings.upload_instagram
                else None
            ),
        )


class WorkflowPipeline:
    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        services: WorkflowServices,
        on_status: StatusCallback | None = None,
        on_downloaded: DownloadedCallback | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.services = services
        self.on_status = on_status
        self.on_downloaded = on_downloaded

    async def process(self, job_id: str) -> Job:
        job = self.repository.get(job_id)
        if not job:
            raise KeyError(f"Unknown job {job_id}")
        job_dir = self.settings.work_dir / "jobs" / job.id

        try:
            await self._status(job.id, JobStatus.DOWNLOADING, "Downloading source video")
            source = await self.services.downloader.download(job.source_url, job_dir)
            downloaded_job = self.repository.update(job.id, source_title=source.title)
            if self.on_downloaded:
                await self.on_downloaded(downloaded_job, source)

            await self._status(
                job.id,
                JobStatus.ANALYZING,
                "Transcribing with Groq and selecting a highlight",
            )
            audio_path = job_dir / "transcript-audio.mp3"
            await asyncio.to_thread(
                self.services.media.extract_audio,
                source.path,
                audio_path,
            )
            plan = await self.services.planner.create_plan(audio_path, source)

            await self._status(job.id, JobStatus.RENDERING, "Rendering vertical 9:16 Short")
            output_path = job_dir / "short.mp4"
            await asyncio.to_thread(
                self.services.media.render_short,
                source.path,
                output_path,
                plan.start_seconds,
                plan.duration_seconds,
            )
            self.repository.update(
                job.id,
                short_title=plan.title,
                short_description=plan.description,
                instagram_caption=plan.instagram_caption,
                output_path=str(output_path),
            )

            uploaded_platforms: list[str] = []
            if self.services.youtube_uploader:
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Uploading to YouTube as {self.settings.youtube_privacy_status} "
                    f"for channel {self.settings.youtube_channel_id}",
                )
                youtube_video_id = await self.services.youtube_uploader.upload(output_path, plan)
                self.repository.update(job.id, youtube_video_id=youtube_video_id)
                uploaded_platforms.append("YouTube")

            if self.services.instagram_uploader:
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    "Publishing Instagram Reel and sharing it to the feed",
                )
                instagram = await self.services.instagram_uploader.upload(output_path, plan)
                self.repository.update(
                    job.id,
                    instagram_media_id=instagram.media_id,
                    instagram_url=instagram.permalink,
                )
                uploaded_platforms.append("Instagram")

            progress = (
                f"Published to {' and '.join(uploaded_platforms)}"
                if uploaded_platforms
                else "Short is ready"
            )
            completed = self.repository.update(
                job.id,
                status=JobStatus.COMPLETE,
                progress_message=progress,
                error=None,
            )
            await self._notify(completed, completed.progress_message)

            if uploaded_platforms and not self.settings.keep_work_files:
                shutil.rmtree(job_dir, ignore_errors=True)
                completed = self.repository.update(job.id, output_path=None)
            return completed
        except Exception as exc:
            if isinstance(exc, WorkflowError):
                logger.info("Job %s failed: %s", job.id, exc)
            else:
                logger.exception("Job %s failed unexpectedly", job.id)
            error = _safe_error(exc)
            failed = self.repository.update(
                job.id,
                status=JobStatus.FAILED,
                progress_message="Workflow failed",
                error=error,
            )
            await self._notify(failed, f"Failed: {error}")
            return failed

    async def _status(self, job_id: str, status: JobStatus, message: str) -> Job:
        job = self.repository.update(
            job_id,
            status=status,
            progress_message=message,
            error=None,
        )
        await self._notify(job, message)
        return job

    async def _notify(self, job: Job, message: str) -> None:
        if not self.on_status:
            return
        try:
            await self.on_status(job, message)
        except Exception:
            logger.exception("Could not send status notification for job %s", job.id)


class JobQueue:
    def __init__(self, pipeline: WorkflowPipeline) -> None:
        self.pipeline = pipeline
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker(), name="shorts-workflow-worker")

    async def stop(self) -> None:
        if not self.worker_task:
            return
        self.worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await self.worker_task
        self.worker_task = None

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self.pipeline.process(job_id)
            except Exception:
                logger.exception("Unexpected queue failure for job %s", job_id)
            finally:
                self.queue.task_done()


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    return message[:1500]

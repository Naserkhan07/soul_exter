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
from .media import MediaProcessor
from .models import Job, JobStatus
from .youtube import YouTubeUploader

logger = logging.getLogger(__name__)
StatusCallback = Callable[[Job, str], Awaitable[None]]


@dataclass(slots=True)
class WorkflowServices:
    downloader: VideoDownloader
    media: MediaProcessor
    planner: AIPlanner
    uploader: YouTubeUploader | None

    @classmethod
    def from_settings(cls, settings: Settings) -> WorkflowServices:
        return cls(
            downloader=VideoDownloader(),
            media=MediaProcessor(),
            planner=AIPlanner(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                transcription_model=settings.openai_transcription_model,
                target_duration=settings.clip_duration_seconds,
            ),
            uploader=(
                YouTubeUploader(
                    token_file=settings.youtube_token_file,
                    privacy_status=settings.youtube_privacy_status,
                )
                if settings.auto_upload
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
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.services = services
        self.on_status = on_status

    async def process(self, job_id: str) -> Job:
        job = self.repository.get(job_id)
        if not job:
            raise KeyError(f"Unknown job {job_id}")
        job_dir = self.settings.work_dir / "jobs" / job.id

        try:
            await self._status(job.id, JobStatus.DOWNLOADING, "Downloading source video")
            source = await self.services.downloader.download(job.source_url, job_dir)
            self.repository.update(job.id, source_title=source.title)

            await self._status(
                job.id,
                JobStatus.ANALYZING,
                "Transcribing and selecting a highlight",
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
                output_path=str(output_path),
            )

            youtube_video_id = None
            if self.services.uploader:
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Uploading to YouTube as {self.settings.youtube_privacy_status}",
                )
                youtube_video_id = await self.services.uploader.upload(output_path, plan)

            completed = self.repository.update(
                job.id,
                status=JobStatus.COMPLETE,
                progress_message=("Uploaded to YouTube" if youtube_video_id else "Short is ready"),
                youtube_video_id=youtube_video_id,
                error=None,
            )
            await self._notify(completed, completed.progress_message)

            if youtube_video_id and not self.settings.keep_work_files:
                shutil.rmtree(job_dir, ignore_errors=True)
                completed = self.repository.update(job.id, output_path=None)
            return completed
        except Exception as exc:
            logger.exception("Job %s failed", job.id)
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
            finally:
                self.queue.task_done()


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    return message[:1500]

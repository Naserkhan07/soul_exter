from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .db import JobRepository
from .downloader import is_youtube_url
from .errors import ConfigurationError, WorkflowError
from .models import Job, SourceVideo
from .pipeline import WorkflowPipeline, WorkflowServices


class LinkFileQueue:
    """A line-based URL queue with atomic acknowledgement after download."""

    def __init__(self, links_file: Path, downloaded_log: Path) -> None:
        self.links_file = links_file
        self.downloaded_log = downloaded_log

    def pending_urls(self) -> list[str]:
        lines = self.links_file.read_text(encoding="utf-8").splitlines()
        urls: list[str] = []
        for line in lines:
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            if is_youtube_url(candidate) and candidate not in urls:
                urls.append(candidate)
            else:
                print(
                    f"Ignoring invalid or duplicate links.txt entry: {candidate}", file=sys.stderr
                )
        return urls

    def acknowledge_download(self, url: str, job: Job, source: SourceVideo) -> None:
        """Remove the first exact URL line and record it; leave comments and new URLs intact."""
        original_lines = self.links_file.read_text(encoding="utf-8").splitlines(keepends=True)
        output_lines: list[str] = []
        removed = False
        for line in original_lines:
            if line.strip() == url:
                removed = True
                continue
            output_lines.append(line)
        if not removed:
            raise WorkflowError(
                f"Downloaded {url}, but its line disappeared before it could be acknowledged."
            )

        temporary = self.links_file.with_name(f".{self.links_file.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text("".join(output_lines), encoding="utf-8")
            os.replace(temporary, self.links_file)
        finally:
            temporary.unlink(missing_ok=True)

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        safe_title = " ".join(source.title.split()).replace("\t", " ")
        with self.downloaded_log.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{timestamp}\t{job.id}\t{url}\t{safe_title}\n")


async def run_file_queue(
    settings: Settings,
    watch: bool = True,
    resume_job_id: str | None = None,
    expand_job_id: str | None = None,
    rebuild_job_id: str | None = None,
) -> int:
    settings.validate_file_queue()
    settings.prepare_directories()
    repository = JobRepository(settings.database_path)
    repository.fail_interrupted()
    services = WorkflowServices.from_settings(settings)
    services.media.check_tools()
    link_queue = LinkFileQueue(settings.links_file, settings.downloaded_links_log)

    async def report(job: Job, message: str) -> None:
        print(f"[{job.id}] {job.status.value}: {message}", flush=True)

    async def downloaded(job: Job, source: SourceVideo) -> None:
        link_queue.acknowledge_download(job.source_url, job, source)
        print(f"[{job.id}] removed downloaded URL from {settings.links_file}", flush=True)

    pipeline = WorkflowPipeline(
        settings,
        repository,
        services,
        on_status=report,
        on_downloaded=downloaded,
    )
    selected_job_id = rebuild_job_id or expand_job_id or resume_job_id
    if selected_job_id:
        job = repository.get(selected_job_id)
        if not job:
            print(
                f"Job {selected_job_id} was not found in {settings.database_path}.", file=sys.stderr
            )
            return 1
        if rebuild_job_id:
            previous_clips = repository.reset_clip_media(job.id)
            if not previous_clips:
                print(
                    f"Job {job.id} has no multi-clip batch to rebuild; use --expand first.",
                    file=sys.stderr,
                )
                return 1
            for clip in previous_clips:
                for path_value in (clip.output_path, clip.thumbnail_path):
                    if path_value:
                        Path(path_value).unlink(missing_ok=True)
            action = "rebuilding and re-uploading every clip"
        elif expand_job_id:
            action = "expanding into multiple clips"
        else:
            action = "resuming"
        print(f"[{job.id}] reusing its existing downloaded source and {action}", flush=True)
        result = await pipeline.process(
            job.id,
            reuse_downloaded=True,
            expand_existing=bool(expand_job_id),
        )
        return 1 if result.error else 0

    any_failures = False
    if watch:
        print(
            f"Local watcher started. Add YouTube URLs to {settings.links_file}. "
            "Press Ctrl+C to stop.",
            flush=True,
        )

    while True:
        urls = link_queue.pending_urls()
        for url in urls:
            job = repository.create(chat_id=0, user_id=0, source_url=url)
            result = await pipeline.process(job.id)
            any_failures = any_failures or bool(result.error)

        if not watch:
            return 1 if any_failures else 0
        await asyncio.sleep(settings.links_poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Watch links.txt and publish multiple AI-selected YouTube Shorts and/or "
            "Instagram Reels from each downloaded video."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process the current file once and exit instead of watching it",
    )
    mode.add_argument(
        "--resume",
        metavar="JOB_ID",
        help="Reuse a previously downloaded source and retry unfinished stages",
    )
    mode.add_argument(
        "--expand",
        metavar="JOB_ID",
        help="Turn a legacy single-clip job into a new multi-clip batch",
    )
    mode.add_argument(
        "--rebuild",
        metavar="JOB_ID",
        help="Re-render and re-upload every clip using current quality settings",
    )
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        exit_code = asyncio.run(
            run_file_queue(
                settings,
                watch=not args.once and not args.resume and not args.expand and not args.rebuild,
                resume_job_id=args.resume,
                expand_job_id=args.expand,
                rebuild_job_id=args.rebuild,
            )
        )
    except ConfigurationError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        print("\nLocal watcher stopped.")
        exit_code = 0
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

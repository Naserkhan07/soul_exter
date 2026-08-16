from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from .config import Settings
from .db import JobRepository
from .downloader import is_youtube_url
from .models import Job
from .pipeline import WorkflowPipeline, WorkflowServices


async def _run(urls: list[str], upload_override: bool | None) -> int:
    settings = Settings.from_env()
    if upload_override is not None:
        settings = replace(settings, auto_upload=upload_override)
    settings.validate_pipeline()
    settings.prepare_directories()

    repository = JobRepository(settings.database_path)
    services = WorkflowServices.from_settings(settings)
    services.media.check_tools()

    async def report(job: Job, message: str) -> None:
        print(f"[{job.id}] {job.status.value}: {message}")

    pipeline = WorkflowPipeline(settings, repository, services, on_status=report)
    failed = False
    for url in urls:
        if not is_youtube_url(url):
            print(f"Skipping unsupported URL: {url}")
            failed = True
            continue
        job = repository.create(chat_id=0, user_id=0, source_url=url)
        result = await pipeline.process(job.id)
        if result.error:
            failed = True
        elif result.youtube_url:
            print(f"Published: {result.youtube_url}")
        else:
            print(f"Created: {result.output_path}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn authorized YouTube videos into AI-planned vertical Shorts."
    )
    parser.add_argument("urls", nargs="+", help="Individual YouTube video URLs")
    upload = parser.add_mutually_exclusive_group()
    upload.add_argument(
        "--upload",
        action="store_true",
        dest="upload_override",
        help="Upload results using the configured YouTube OAuth token",
    )
    upload.add_argument(
        "--no-upload",
        action="store_false",
        dest="upload_override",
        help="Only render local MP4 files",
    )
    parser.set_defaults(upload_override=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.urls, args.upload_override)))


if __name__ == "__main__":
    main()

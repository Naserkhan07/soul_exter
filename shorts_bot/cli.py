from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from .config import Settings
from .db import JobRepository
from .downloader import is_youtube_url
from .errors import ConfigurationError
from .models import Job
from .pipeline import WorkflowPipeline, WorkflowServices


async def _run(urls: list[str], platform: str | None) -> int:
    settings = Settings.from_env()
    if platform is not None:
        settings = replace(
            settings,
            upload_youtube=platform in {"youtube", "both"},
            upload_instagram=platform in {"instagram", "both"},
        )
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
            continue
        if result.youtube_url:
            print(f"YouTube: {result.youtube_url}")
        if result.instagram_url:
            print(f"Instagram: {result.instagram_url}")
        if not result.youtube_url and not result.instagram_url:
            print(f"Created: {result.output_path}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn authorized YouTube videos into Groq-planned Shorts and Reels."
    )
    parser.add_argument("urls", nargs="+", help="Individual YouTube video URLs")
    parser.add_argument(
        "--platform",
        choices=("youtube", "instagram", "both", "none"),
        help="Override the upload platforms configured in .env",
    )
    args = parser.parse_args()
    platform = None if args.platform is None else args.platform
    if platform == "none":
        platform = ""
    try:
        exit_code = asyncio.run(_run(args.urls, platform))
    except ConfigurationError as exc:
        parser.error(str(exc))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

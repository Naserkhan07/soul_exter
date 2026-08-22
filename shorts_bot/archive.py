from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .errors import WorkflowError
from .models import Job, JobClip

logger = logging.getLogger(__name__)


class ArchiveError(WorkflowError):
    """A local pending-upload folder could not be created."""


def build_job_folder(
    job: Job,
    clips: list[JobClip],
    destination_dir: Path,
    pending_platforms: set[str],
) -> Path:
    """Copy generated videos, thumbnails, and metadata into one ordinary folder."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder_path = destination_dir / f"{job.id}-pending-{timestamp}"
    temporary = destination_dir / f".{folder_path.name}.building"

    metadata = {
        "job_id": job.id,
        "source_url": job.source_url,
        "source_title": job.source_title,
        "created_at": job.created_at,
        "pending_platforms": sorted(pending_platforms),
        "clip_count": len(clips),
        "clips": [_clip_metadata(clip) for clip in clips],
    }

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "clip_index",
            "start_seconds",
            "duration_seconds",
            "video_file",
            "thumbnail_file",
            "youtube_status",
            "youtube_url",
            "instagram_status",
            "instagram_url",
            "title",
            "youtube_description",
            "instagram_caption",
        ]
    )
    for clip in clips:
        writer.writerow(
            [
                clip.clip_index,
                clip.start_seconds,
                clip.duration_seconds,
                Path(clip.output_path).name if clip.output_path else "",
                Path(clip.thumbnail_path).name if clip.thumbnail_path else "",
                "uploaded" if clip.youtube_video_id else "pending",
                clip.youtube_url or "",
                "uploaded" if clip.instagram_media_id else "pending",
                clip.instagram_url or "",
                clip.title,
                clip.description,
                clip.instagram_caption,
            ]
        )

    try:
        shutil.rmtree(temporary, ignore_errors=True)
        videos_dir = temporary / "videos"
        thumbnails_dir = temporary / "thumbnails"
        videos_dir.mkdir(parents=True)
        thumbnails_dir.mkdir(parents=True)
        (temporary / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (temporary / "upload-manifest.csv").write_text(
            csv_buffer.getvalue(),
            encoding="utf-8-sig",
        )
        (temporary / "README.txt").write_text(
            "This folder was created because one or more platform uploads are pending.\n"
            "Open videos/ for MP4 files and thumbnails/ for covers.\n"
            "metadata.json and upload-manifest.csv contain titles, descriptions, captions, "
            "platform URLs, and pending status.\n",
            encoding="utf-8",
        )
        for clip in clips:
            for destination, path_value in (
                (videos_dir, clip.output_path),
                (thumbnails_dir, clip.thumbnail_path),
            ):
                if not path_value:
                    continue
                path = Path(path_value)
                if path.exists() and path.is_file():
                    shutil.copy2(path, destination / f"{clip.clip_index:03d}-{path.name}")
        temporary.replace(folder_path)
        return folder_path
    except OSError as exc:
        raise ArchiveError(f"Could not create local pending-upload folder: {exc}") from exc
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def open_local_folder(path: Path) -> None:
    """Open a folder in Windows Explorer; silently skip on other platforms or failures."""
    if os.name != "nt":
        return
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except OSError:
        logger.warning("Could not open pending-upload folder %s", path)


def _clip_metadata(clip: JobClip) -> dict[str, object]:
    return {
        "clip_index": clip.clip_index,
        "start_seconds": clip.start_seconds,
        "duration_seconds": clip.duration_seconds,
        "title": clip.title,
        "youtube_description": clip.description,
        "instagram_caption": clip.instagram_caption,
        "video_file": Path(clip.output_path).name if clip.output_path else None,
        "thumbnail_file": Path(clip.thumbnail_path).name if clip.thumbnail_path else None,
        "youtube_video_id": clip.youtube_video_id,
        "youtube_url": clip.youtube_url,
        "instagram_media_id": clip.instagram_media_id,
        "instagram_url": clip.instagram_url,
        "error": clip.error,
    }

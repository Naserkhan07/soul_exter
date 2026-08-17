from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .errors import WorkflowError
from .models import Job, JobClip


class ArchiveError(WorkflowError):
    """A local pending-upload archive could not be created."""


def build_job_archive(
    job: Job,
    clips: list[JobClip],
    destination_dir: Path,
    limited_platforms: set[str],
) -> Path:
    """Bundle generated MP4s, thumbnails, and all metadata into one ZIP without recompression."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive_path = destination_dir / f"{job.id}-upload-limit-{timestamp}.zip"
    temporary = archive_path.with_suffix(".zip.part")

    metadata = {
        "job_id": job.id,
        "source_url": job.source_url,
        "source_title": job.source_title,
        "created_at": job.created_at,
        "upload_limits_reached": sorted(limited_platforms),
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
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(
                "metadata.json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
            )
            archive.writestr("upload-manifest.csv", csv_buffer.getvalue())
            archive.writestr(
                "README.txt",
                "This archive was created because a platform upload limit was reached.\n"
                "MP4 files are stored without ZIP recompression. See metadata.json or "
                "upload-manifest.csv for titles, descriptions, captions, and upload status.\n",
            )
            for clip in clips:
                for folder, path_value in (
                    ("videos", clip.output_path),
                    ("thumbnails", clip.thumbnail_path),
                ):
                    if not path_value:
                        continue
                    path = Path(path_value)
                    if path.exists() and path.is_file():
                        archive.write(path, arcname=f"{folder}/{clip.clip_index:03d}-{path.name}")
        temporary.replace(archive_path)
        return archive_path
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"Could not create local video archive: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


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

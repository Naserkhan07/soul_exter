from __future__ import annotations

import csv
import hashlib
import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .db import JobRepository
from .errors import WorkflowError
from .models import JobClip


class StoreBundleError(WorkflowError):
    """A local Splitzzz store bundle could not be created safely."""


@dataclass(frozen=True, slots=True)
class StoreBundleResult:
    bundle_number: int
    zip_path: Path
    clip_count: int
    sha256: str


class ReelBundleBuilder:
    """Collect rendered clips into permanent local ZIP packs."""

    def __init__(self, destination: Path, bundle_size: int = 50) -> None:
        self.destination = destination
        self.bundle_size = bundle_size

    def create_ready_bundles(self, repository: JobRepository) -> list[StoreBundleResult]:
        self.destination.mkdir(parents=True, exist_ok=True)
        created: list[StoreBundleResult] = []
        while True:
            candidates = repository.list_unbundled_clips(limit=max(500, self.bundle_size * 4))
            clips = [
                clip for clip in candidates if clip.output_path and Path(clip.output_path).is_file()
            ][: self.bundle_size]
            if len(clips) < self.bundle_size:
                break
            created.append(self._create_bundle(repository, clips))
        return created

    def _create_bundle(
        self,
        repository: JobRepository,
        clips: list[JobClip],
    ) -> StoreBundleResult:
        bundle_number = repository.next_store_bundle_number()
        filename = f"splitzzz-reels-pack-{bundle_number:03d}-{self.bundle_size}-reels.zip"
        zip_path = self.destination / filename
        temporary = self.destination / f".{filename}.{os.getpid()}.tmp"
        checksum_path = zip_path.with_suffix(f"{zip_path.suffix}.sha256")

        try:
            temporary.unlink(missing_ok=True)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for position, clip in enumerate(clips, start=1):
                    assert clip.output_path is not None
                    archive.write(
                        clip.output_path,
                        arcname=f"reels/reel-{position:03d}.mp4",
                    )
                archive.writestr("manifest.csv", self._manifest(clips))
                archive.writestr(
                    "README.txt",
                    f"Splitzzz Reel Pack {bundle_number:03d}\n"
                    f"This pack contains {self.bundle_size} MP4 Reels.\n"
                    "Review license terms before redistributing or publishing any media.\n",
                )

            with zipfile.ZipFile(temporary) as archive:
                broken_entry = archive.testzip()
                reel_entries = [
                    name
                    for name in archive.namelist()
                    if name.startswith("reels/") and name.endswith(".mp4")
                ]
            if broken_entry:
                raise StoreBundleError(f"ZIP verification failed at {broken_entry}.")
            if len(reel_entries) != self.bundle_size:
                raise StoreBundleError(
                    f"ZIP contains {len(reel_entries)} Reels instead of {self.bundle_size}."
                )

            temporary.replace(zip_path)
            checksum = self._sha256(zip_path)
            checksum_path.write_text(f"{checksum}  {zip_path.name}\n", encoding="utf-8")
            repository.save_store_bundle(bundle_number, zip_path, clips)
            return StoreBundleResult(bundle_number, zip_path, len(clips), checksum)
        except (OSError, zipfile.BadZipFile) as exc:
            zip_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            raise StoreBundleError(f"Could not create Splitzzz Reel pack: {exc}") from exc
        except Exception:
            zip_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _manifest(clips: list[JobClip]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "reel_number",
                "job_id",
                "clip_index",
                "title",
                "instagram_caption",
            ]
        )
        for position, clip in enumerate(clips, start=1):
            writer.writerow(
                [
                    position,
                    clip.job_id,
                    clip.clip_index,
                    clip.title,
                    clip.instagram_caption,
                ]
            )
        return output.getvalue()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as bundle_file:
            for chunk in iter(lambda: bundle_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

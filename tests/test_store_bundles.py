import zipfile
from pathlib import Path

from shorts_bot.db import JobRepository
from shorts_bot.models import ShortPlan
from shorts_bot.store_bundles import ReelBundleBuilder


def test_creates_verified_local_zip_packs_without_reusing_clips(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    job = repository.create(0, 0, "https://youtu.be/example")
    plans = [
        ShortPlan(index * 25, 25, f"Reel {index + 1}", "Description", "Caption")
        for index in range(4)
    ]
    repository.save_plans(job.id, plans, metadata_ready=True)
    for index in range(1, 5):
        video = tmp_path / f"reel-{index}.mp4"
        video.write_bytes(f"video-{index}".encode())
        repository.update_clip(job.id, index, output_path=str(video))

    uploaded: list[str] = []

    class FakeUploader:
        def upload(self, zip_path: Path, checksum: str) -> str:
            assert len(checksum) == 64
            uploaded.append(zip_path.name)
            return f"bundles/{zip_path.name}"

    builder = ReelBundleBuilder(
        tmp_path / "store-bundles",
        bundle_size=2,
        uploader=FakeUploader(),  # type: ignore[arg-type]
    )
    results = builder.create_ready_bundles(repository)

    assert [result.bundle_number for result in results] == [1, 2]
    assert all(result.clip_count == 2 for result in results)
    bundles = repository.list_store_bundles()
    assert len(bundles) == 2
    assert uploaded == [result.zip_path.name for result in results]
    assert all(str(bundle["website_object_key"]).startswith("bundles/") for bundle in bundles)
    assert repository.list_pending_store_uploads() == []
    assert builder.create_ready_bundles(repository) == []

    with zipfile.ZipFile(results[0].zip_path) as archive:
        assert archive.testzip() is None
        assert [name for name in archive.namelist() if name.endswith(".mp4")] == [
            "reels/reel-001.mp4",
            "reels/reel-002.mp4",
        ]
        assert "manifest.csv" in archive.namelist()
    checksum_file = results[0].zip_path.with_suffix(".zip.sha256")
    assert checksum_file.exists()
    assert results[0].sha256 in checksum_file.read_text(encoding="utf-8")


def test_waits_until_full_pack_is_available(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    job = repository.create(0, 0, "https://youtu.be/example")
    repository.save_plans(
        job.id,
        [ShortPlan(0, 25, "Only Reel", "Description", "Caption")],
        metadata_ready=True,
    )
    video = tmp_path / "only.mp4"
    video.write_bytes(b"video")
    repository.update_clip(job.id, 1, output_path=str(video))

    builder = ReelBundleBuilder(tmp_path / "store-bundles", bundle_size=2)

    assert builder.create_ready_bundles(repository) == []
    assert repository.list_store_bundles() == []

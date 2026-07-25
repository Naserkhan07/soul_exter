"""The orchestrator: script in, finished film out.

For each scene it generates a clip, downloads it, records the result in a
job manifest, and finally stitches everything together. Progress is saved
after every clip, so an interrupted five-minute render resumes instead of
paying for the same clips twice.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from soulclip import ffmpeg
from soulclip.providers import (
    AuthError, PermanentError, ProviderError, VideoProvider,
)
from soulclip.quality import check_clip, plan_retry
from soulclip.script_parser import Scene

Reporter = Callable[[str], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ClipRecord:
    index: int
    label: str
    prompt: str
    duration: int
    status: str = "pending"       # pending | done | failed
    path: str | None = None
    provider: str | None = None
    model: str | None = None
    remote_id: str | None = None
    error: str | None = None
    failure_kind: str | None = None
    attempts: int = 0
    seconds: float | None = None
    updated_at: str = field(default_factory=_now)


class Job:
    """Persistent record of one render, stored as ``job.json``."""

    def __init__(self, workdir: Path, scenes: list[Scene] | None = None) -> None:
        self.workdir = Path(workdir)
        self.clips_dir = self.workdir / "clips"
        self.manifest_path = self.workdir / "job.json"
        self.records: dict[int, ClipRecord] = {}
        self.created_at = _now()
        self.output: str | None = None

        if self.manifest_path.exists():
            self._load()
        if scenes:
            self._sync(scenes)

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.created_at = data.get("created_at", _now())
        self.output = data.get("output")
        for raw in data.get("clips", []):
            rec = ClipRecord(**raw)
            self.records[rec.index] = rec

    def _sync(self, scenes: list[Scene]) -> None:
        """Add records for new scenes; drop stale ones whose prompt changed."""
        for scene in scenes:
            existing = self.records.get(scene.index)
            if existing and existing.prompt == scene.text:
                existing.label = scene.label
                continue
            if existing and existing.status == "done":
                # Prompt was edited — this clip is no longer valid.
                if existing.path:
                    Path(existing.path).unlink(missing_ok=True)
            self.records[scene.index] = ClipRecord(
                index=scene.index,
                label=scene.label,
                prompt=scene.text,
                duration=scene.duration,
            )
        wanted = {s.index for s in scenes}
        for stale in [i for i in self.records if i not in wanted]:
            rec = self.records[stale]
            # When several workers share a workdir each one only knows about
            # its own slice of the film, so an index missing from *this*
            # scene list is not necessarily stale. Keep any finished clip
            # whose file is still present; drop only genuine leftovers.
            if rec.status == "done" and rec.path and Path(rec.path).exists():
                continue
            del self.records[stale]
        self.save()

    def save(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)

        records = {i: asdict(r) for i, r in self.records.items()}

        # Another worker may share this workdir (two GPUs, two notebooks).
        # Re-read the manifest and keep any clip it finished that this
        # process does not know about, otherwise the last writer silently
        # reverts the other's progress and those clips get regenerated.
        if self.manifest_path.exists():
            try:
                on_disk = json.loads(
                    self.manifest_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                on_disk = {}
            for raw in on_disk.get("clips", []):
                index = raw.get("index")
                if index is None:
                    continue
                mine = records.get(index)
                theirs_done = (
                    raw.get("status") == "done"
                    and raw.get("path")
                    and Path(raw["path"]).exists()
                )
                if theirs_done and (mine is None or mine["status"] != "done"):
                    records[index] = raw

        payload = {
            "created_at": self.created_at,
            "updated_at": _now(),
            "output": self.output,
            "clips": [records[i] for i in sorted(records)],
        }
        # Write to a per-process temp file so two workers cannot clobber
        # each other's partial writes before the atomic rename.
        tmp = self.manifest_path.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)

    # -- queries -----------------------------------------------------------

    def ordered(self) -> list[ClipRecord]:
        return [self.records[i] for i in sorted(self.records)]

    def pending(self) -> list[ClipRecord]:
        out = []
        for rec in self.ordered():
            if rec.status == "done" and rec.path and ffmpeg.is_valid_video(Path(rec.path)):
                continue
            if rec.status == "done":
                rec.status = "pending"  # file vanished or is corrupt
            out.append(rec)
        return out

    def done(self) -> list[ClipRecord]:
        return [r for r in self.ordered() if r.status == "done"]

    def clip_paths(self) -> list[Path]:
        return [Path(r.path) for r in self.done() if r.path]


@dataclass
class RenderResult:
    output: Path | None
    job: Job
    generated: int
    reused: int
    failed: list[ClipRecord]
    elapsed: float

    @property
    def ok(self) -> bool:
        return self.output is not None and not self.failed


class Pipeline:
    """Runs scenes through a provider and stitches the results."""

    def __init__(
        self,
        provider: VideoProvider,
        workdir: Path,
        *,
        reporter: Reporter | None = None,
        max_retries: int = 2,
        retry_backoff: float = 5.0,
        concurrency: int = 1,
        abort_after: int = 3,
        check_black: bool = True,
    ) -> None:
        self.provider = provider
        self.workdir = Path(workdir)
        self.report = reporter or (lambda msg: None)
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.concurrency = max(1, concurrency)
        #: Consecutive failures tolerated before giving up on the whole run.
        self.abort_after = max(1, abort_after)
        #: Black-frame detection costs an extra ffmpeg pass per clip.
        self.check_black = check_black
        #: Swappable so tests can stub inspection without real video files.
        self.checker = check_clip
        #: Set by tests to skip the real back-off waits.
        self._fast_retry = False

    # -- one clip ----------------------------------------------------------

    def _generate_one(self, rec: ClipRecord, scene: Scene, total: int) -> ClipRecord:
        dest = self.workdir / "clips" / f"{scene.slug}.mp4"
        # `total` is this worker's slice, which may be a subset of the film
        # when several machines share a workdir. Showing the scene's real
        # index against a subset count reads as "[4/3]", so widen it.
        prefix = f"[{rec.index}/{max(total, rec.index)}]"

        for attempt in range(1, self.max_retries + 2):
            rec.attempts += 1
            started = time.time()
            try:
                self.report(f"{prefix} {rec.label}: generating…")

                # Give the mock provider per-scene variety.
                if hasattr(self.provider, "options"):
                    self.provider.options["seed"] = scene.index
                    self.provider.options.setdefault("label", "")
                    self.provider.options["label"] = rec.label

                result = self.provider.generate(
                    scene.text,
                    dest,
                    duration=scene.duration,
                    on_status=lambda s: self.report(f"{prefix} {rec.label}: {s}"),
                )

                report = self.checker(
                    dest, expect_seconds=scene.duration,
                    check_black=self.check_black,
                )
                for warning in report.warnings:
                    self.report(f"{prefix} {rec.label}: {warning}")
                if not report.ok:
                    raise ProviderError(
                        "clip failed quality check: "
                        + "; ".join(report.problems)
                    )

                rec.status = "done"
                rec.path = str(dest)
                rec.provider = result.provider
                rec.model = result.model
                rec.remote_id = result.remote_id
                rec.error = None
                rec.seconds = round(time.time() - started, 1)
                rec.updated_at = _now()
                self.report(f"{prefix} {rec.label}: saved {dest.name} ({rec.seconds}s)")
                return rec

            except AuthError:
                raise  # credentials won't fix themselves
            except PermanentError as exc:
                # Deterministic: every retry would fail identically, so stop
                # now rather than spending the retry budget (and API credit).
                rec.status = "failed"
                rec.error = str(exc)[:500]
                rec.updated_at = _now()
                self.report(f"{prefix} {rec.label}: FAILED (permanent) — {rec.error}")
                return rec
            except Exception as exc:  # noqa: BLE001 - recorded on the clip
                rec.error = str(exc)[:500]
                rec.updated_at = _now()

                # Different failures deserve different treatment: a rate
                # limit wants a long back-off, a rejected prompt should not
                # be retried at all.
                plan = plan_retry(exc, attempt, max_retries=self.max_retries)
                rec.failure_kind = plan.kind.value

                if plan.should_retry:
                    self.report(
                        f"{prefix} {rec.label}: {plan.describe()}"
                    )
                    time.sleep(plan.wait_seconds if not self._fast_retry else 0)
                else:
                    rec.status = "failed"
                    detail = f" ({plan.reason})" if plan.reason else ""
                    self.report(
                        f"{prefix} {rec.label}: FAILED [{plan.kind.value}]"
                        f"{detail} — {rec.error}"
                    )
                    return rec
        return rec

    def _report_eta(self, job, total: int) -> None:
        """Project the finish time from this run's own measured clip times.

        Published per-clip figures for a given GPU vary by several times, so
        rather than trusting an estimate the pipeline times the clips it has
        actually produced and extrapolates from those.
        """
        times = [r.seconds for r in job.done() if r.seconds]
        if len(times) < 2:
            return

        # Recent clips reflect the steady state; the first is skewed by
        # model loading and any lazy CUDA setup.
        recent = times[-5:]
        per = sum(recent) / len(recent)
        remaining = total - len(job.done())
        if remaining <= 0:
            return

        eta = per * remaining
        spread = max(recent) / max(min(recent), 0.01)
        note = "" if spread < 1.5 else " (times still varying)"

        if eta < 90:
            left = f"{eta:.0f}s"
        elif eta < 5400:
            left = f"{eta / 60:.0f} min"
        else:
            left = f"{eta / 3600:.1f} h"

        avg = f"{per:.1f}s" if per < 10 else f"{per:.0f}s"
        self.report(
            f"      avg {avg}/clip · {remaining} left · ~{left} to go{note}"
        )

    # -- whole job ---------------------------------------------------------

    def render(
        self,
        scenes: list[Scene],
        output: Path,
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 24,
        crossfade: float = 0.0,
        music: Path | None = None,
        narrate: bool = False,
        voice: str = "af_heart",
        ambience: Path | None = None,
        music_level: float = 0.18,
        duck: float = 0.35,
        fast_concat: bool = False,
        allow_partial: bool = False,
        stitch: bool = True,
    ) -> RenderResult:
        started = time.time()
        job = Job(self.workdir, scenes)
        by_index = {s.index: s for s in scenes}
        total = len(scenes)

        pending = job.pending()
        reused = total - len(pending)
        if reused:
            self.report(f"Resuming: {reused} of {total} clips already on disk.")

        generated = 0
        if self.concurrency == 1 or len(pending) <= 1:
            consecutive_failures = 0
            for rec in pending:
                self._generate_one(rec, by_index[rec.index], total)
                job.save()
                if rec.status == "done":
                    generated += 1
                    consecutive_failures = 0
                    self._report_eta(job, total)
                else:
                    consecutive_failures += 1
                    # Something systemic is wrong (bad key, bad model, no
                    # quota). Bail out instead of grinding through every
                    # remaining scene and failing on all of them.
                    if consecutive_failures >= self.abort_after:
                        self.report(
                            f"\nStopping early: {consecutive_failures} clips in a "
                            "row failed. Fix the underlying problem, then re-run "
                            "to resume — finished clips are kept."
                        )
                        break
        else:
            self.report(f"Generating {len(pending)} clips, {self.concurrency} at a time.")
            with concurrent.futures.ThreadPoolExecutor(self.concurrency) as pool:
                futures = {
                    pool.submit(self._generate_one, rec, by_index[rec.index], total): rec
                    for rec in pending
                }
                for fut in concurrent.futures.as_completed(futures):
                    rec = futures[fut]
                    try:
                        fut.result()
                    except AuthError:
                        for f in futures:
                            f.cancel()
                        raise
                    job.save()
                    if rec.status == "done":
                        generated += 1

        failed = [r for r in job.ordered() if r.status != "done"]

        if failed and not allow_partial:
            job.save()
            self.report(
                f"\n{len(failed)} clip(s) failed. Fix the cause and re-run to "
                "retry just those, or pass --allow-partial to stitch what worked."
            )
            return RenderResult(None, job, generated, reused, failed,
                                time.time() - started)

        clips = job.clip_paths()
        if not clips:
            job.save()
            self.report("No clips were produced — nothing to stitch.")
            return RenderResult(None, job, generated, reused, failed,
                                time.time() - started)

        if not stitch:
            job.save()
            self.report(f"Skipping stitch; {len(clips)} clips are in {job.clips_dir}")
            return RenderResult(None, job, generated, reused, failed,
                                time.time() - started)

        narration_track: Path | None = None
        if narrate:
            from soulclip.audio import (
                Narrator, concat_narration, narrate_scenes,
            )

            try:
                self.report(f"\nNarrating {len(scenes)} scenes…")
                tracks = narrate_scenes(
                    scenes, self.workdir,
                    narrator=Narrator(voice=voice), reporter=self.report,
                )
                ordered = [tracks[s.index] for s in scenes if s.index in tracks]
                if ordered:
                    narration_track = self.workdir / "narration.wav"
                    concat_narration(ordered, narration_track)
            except Exception as exc:  # noqa: BLE001
                # Narration is optional and third-party TTS can fail in many
                # ways. Never lose an expensively generated film over it.
                self.report(f"Narration unavailable: {exc}")
                self.report("Continuing without narration.")
                narration_track = None

        self.report(f"\nStitching {len(clips)} clips into {output.name}…")
        # When audio is layered on afterwards, stitch to a temp file first so
        # the mix can copy the video stream instead of re-encoding it.
        needs_mix = bool(narration_track or ambience or (music and narrate))
        stitch_target = (
            output.with_name(f".{output.stem}_silent{output.suffix}")
            if needs_mix else output
        )

        ffmpeg.concat(
            clips, stitch_target,
            reencode=not fast_concat,
            width=width, height=height, fps=fps,
            crossfade=crossfade,
            audio=None if needs_mix else music,
        )

        if needs_mix:
            from soulclip.audio import AudioMix, mix as mix_audio

            self.report("Mixing audio…")
            try:
                mix_audio(
                    stitch_target, output,
                    narration=narration_track,
                    music=music,
                    ambience=ambience,
                    levels=AudioMix(music=music_level, duck=duck),
                )
                stitch_target.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                self.report(f"Mix failed ({exc}); keeping the silent cut.")
                stitch_target.replace(output)

        job.output = str(output)
        job.save()

        length = ffmpeg.probe_duration(output)
        size_mb = output.stat().st_size / 1e6
        if length:
            self.report(
                f"Done: {output} — {int(length // 60)}m {int(length % 60):02d}s, "
                f"{size_mb:.1f} MB"
            )
        else:
            self.report(f"Done: {output} — {size_mb:.1f} MB")

        return RenderResult(output, job, generated, reused, failed,
                            time.time() - started)

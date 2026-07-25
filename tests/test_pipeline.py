"""Tests for the render pipeline: resume, retry and failure handling."""

import shutil
import tempfile
import unittest
from pathlib import Path

from soulclip.pipeline import Job, Pipeline
from soulclip.providers import GenerationResult, ProviderError, VideoProvider
from soulclip.script_parser import parse_script


class FakeProvider(VideoProvider):
    """Writes a tiny fake file instead of calling an API."""

    name = "fake"
    default_model = "fake-1"

    def __init__(self, fail_on=(), fail_times=None, **kw):
        super().__init__(**kw)
        self.fail_on = set(fail_on)
        self.fail_times = dict(fail_times or {})
        self.calls = []

    def generate(self, prompt, dest, *, duration=10, on_status=None):
        self.calls.append(prompt)
        seed = self.options.get("seed")

        if seed in self.fail_times and self.fail_times[seed] > 0:
            self.fail_times[seed] -= 1
            raise ProviderError(f"transient failure on {seed}")
        if seed in self.fail_on:
            raise ProviderError(f"permanent failure on {seed}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\0" * 4096)
        return GenerationResult(dest, self.name, self.model, f"id-{seed}")


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.scenes = parse_script(
            "Scene 1: First shot of a wide desert under a hard noon sun.\n\n"
            "Scene 2: Second shot of a narrow alley slick with fresh rain.\n\n"
            "Scene 3: Third shot of a rooftop at dusk above a lit city."
        )
        # Treat any non-empty file as a valid clip for these tests.
        import soulclip.pipeline as pl
        self._real_valid = pl.ffmpeg.is_valid_video
        pl.ffmpeg.is_valid_video = lambda p, **k: Path(p).exists() and \
            Path(p).stat().st_size > 0

    def tearDown(self):
        import soulclip.pipeline as pl
        pl.ffmpeg.is_valid_video = self._real_valid
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pipeline(self, provider, **kw):
        return Pipeline(provider, self.tmp / "work", reporter=lambda m: None, **kw)


class TestGeneration(PipelineTestCase):
    def test_generates_every_scene(self):
        provider = FakeProvider()
        result = self._pipeline(provider).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        self.assertEqual(result.generated, 3)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(len(result.job.done()), 3)

    def test_clips_saved_in_scene_order(self):
        result = self._pipeline(FakeProvider()).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        names = [p.name for p in result.job.clip_paths()]
        self.assertEqual(names, ["scene_001.mp4", "scene_002.mp4", "scene_003.mp4"])

    def test_prompt_passed_through(self):
        provider = FakeProvider()
        self._pipeline(provider).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        self.assertIn("wide desert", provider.calls[0])


class TestRetry(PipelineTestCase):
    def test_transient_failure_is_retried(self):
        provider = FakeProvider(fail_times={2: 1})
        pipeline = self._pipeline(provider, max_retries=2)
        pipeline.retry_backoff = 0
        result = pipeline.render(self.scenes, self.tmp / "out.mp4", stitch=False)
        self.assertEqual(len(result.failed), 0)
        self.assertEqual(len(provider.calls), 4)  # one extra attempt

    def test_permanent_failure_is_recorded(self):
        provider = FakeProvider(fail_on={2})
        pipeline = self._pipeline(provider, max_retries=1)
        pipeline.retry_backoff = 0
        result = pipeline.render(self.scenes, self.tmp / "out.mp4", stitch=False)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0].index, 2)
        self.assertIn("permanent failure", result.failed[0].error)

    def test_failure_blocks_stitch_unless_allowed(self):
        provider = FakeProvider(fail_on={2})
        pipeline = self._pipeline(provider, max_retries=0)
        pipeline.retry_backoff = 0
        result = pipeline.render(self.scenes, self.tmp / "out.mp4")
        self.assertIsNone(result.output)
        self.assertFalse(result.ok)


class TestResume(PipelineTestCase):
    def test_second_run_reuses_existing_clips(self):
        first = FakeProvider()
        self._pipeline(first).render(self.scenes, self.tmp / "out.mp4", stitch=False)

        second = FakeProvider()
        result = self._pipeline(second).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        self.assertEqual(second.calls, [])
        self.assertEqual(result.reused, 3)
        self.assertEqual(result.generated, 0)

    def test_only_failed_clips_are_retried_on_rerun(self):
        first = FakeProvider(fail_on={2})
        p1 = self._pipeline(first, max_retries=0)
        p1.retry_backoff = 0
        p1.render(self.scenes, self.tmp / "out.mp4", stitch=False)

        second = FakeProvider()
        result = self._pipeline(second).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        self.assertEqual(len(second.calls), 1)
        self.assertEqual(result.generated, 1)
        self.assertEqual(result.reused, 2)

    def test_deleted_clip_is_regenerated(self):
        first = FakeProvider()
        res = self._pipeline(first).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        res.job.clip_paths()[1].unlink()

        second = FakeProvider()
        result = self._pipeline(second).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        self.assertEqual(len(second.calls), 1)
        self.assertEqual(result.generated, 1)

    def test_edited_prompt_invalidates_that_clip(self):
        self._pipeline(FakeProvider()).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        edited = parse_script(
            "Scene 1: First shot of a wide desert under a hard noon sun.\n\n"
            "Scene 2: A COMPLETELY different second shot on a frozen lake.\n\n"
            "Scene 3: Third shot of a rooftop at dusk above a lit city."
        )
        provider = FakeProvider()
        result = self._pipeline(provider).render(
            edited, self.tmp / "out.mp4", stitch=False
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("frozen lake", provider.calls[0])
        self.assertEqual(result.reused, 2)


class TestConcurrency(PipelineTestCase):
    def test_parallel_generation_keeps_order(self):
        provider = FakeProvider()
        result = self._pipeline(provider, concurrency=3).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        self.assertEqual(result.generated, 3)
        indexes = [r.index for r in result.job.done()]
        self.assertEqual(indexes, [1, 2, 3])


class TestJobManifest(PipelineTestCase):
    def test_manifest_written_and_reloaded(self):
        self._pipeline(FakeProvider()).render(
            self.scenes, self.tmp / "out.mp4", stitch=False
        )
        manifest = self.tmp / "work" / "job.json"
        self.assertTrue(manifest.exists())

        reloaded = Job(self.tmp / "work")
        self.assertEqual(len(reloaded.done()), 3)
        self.assertEqual(reloaded.records[1].provider, "fake")


if __name__ == "__main__":
    unittest.main()


class TestStitching(unittest.TestCase):
    """Exercises the real ffmpeg concat path with awkward inputs."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _clip(self, name, seconds=2, size="320x240", with_audio=True):
        import subprocess
        from soulclip.ffmpeg import ffmpeg_path

        dest = self.tmp / name
        cmd = [ffmpeg_path(), "-y", "-v", "error",
               "-f", "lavfi", "-i", f"testsrc=s={size}:r=24:d={seconds}"]
        if with_audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if with_audio:
            cmd += ["-c:a", "aac", "-shortest"]
        cmd += [str(dest)]
        subprocess.run(cmd, capture_output=True, check=True)
        return dest

    def test_concat_clips_with_audio(self):
        from soulclip.ffmpeg import concat, probe_duration

        clips = [self._clip(f"a{i}.mp4") for i in range(3)]
        out = concat(clips, self.tmp / "out.mp4")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1024)
        self.assertAlmostEqual(probe_duration(out) or 0, 6, delta=0.6)

    def test_concat_silent_clips(self):
        """Silent clips must still produce a valid, correctly timed file."""
        from soulclip.ffmpeg import concat, has_audio, probe_duration

        clips = [self._clip(f"s{i}.mp4", with_audio=False) for i in range(3)]
        out = concat(clips, self.tmp / "silent.mp4")
        self.assertGreater(out.stat().st_size, 1024)
        self.assertAlmostEqual(probe_duration(out) or 0, 6, delta=0.6)
        self.assertTrue(has_audio(out))

    def test_concat_mixed_audio_and_sizes(self):
        """The realistic case: clips from different models don't match."""
        from soulclip.ffmpeg import concat, probe_duration

        clips = [
            self._clip("m0.mp4", size="320x240", with_audio=True),
            self._clip("m1.mp4", size="640x360", with_audio=False),
            self._clip("m2.mp4", size="480x480", with_audio=True),
        ]
        out = concat(clips, self.tmp / "mixed.mp4", width=640, height=360)
        self.assertGreater(out.stat().st_size, 1024)
        self.assertAlmostEqual(probe_duration(out) or 0, 6, delta=0.6)

    def test_has_audio_detection(self):
        from soulclip.ffmpeg import has_audio

        self.assertTrue(has_audio(self._clip("withaudio.mp4", with_audio=True)))
        self.assertFalse(has_audio(self._clip("noaudio.mp4", with_audio=False)))

    def test_single_clip_is_copied(self):
        from soulclip.ffmpeg import concat

        clip = self._clip("one.mp4")
        out = concat([clip], self.tmp / "single.mp4")
        self.assertEqual(out.stat().st_size, clip.stat().st_size)

    def test_crossfade_scales_to_a_full_length_film(self):
        """60 clips in one xfade chain gets OOM-killed; batching must fix it.

        A 5-minute film is 60+ shots, so this is the real-world case, not
        an edge case.
        """
        from soulclip.ffmpeg import CROSSFADE_BATCH, concat, probe_duration

        n = CROSSFADE_BATCH * 2 + 3      # forces several batches
        clips = [self._clip(f"x{i}.mp4", seconds=1, with_audio=False)
                 for i in range(n)]
        out = concat(clips, self.tmp / "long.mp4", width=320, height=240,
                     fps=12, crossfade=0.2)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1024)

        # n clips of 1s with (n-1) overlaps of 0.2s
        expected = n - (n - 1) * 0.2
        self.assertAlmostEqual(probe_duration(out) or 0, expected, delta=1.5)

    def test_crossfade_leaves_no_temp_files(self):
        from soulclip.ffmpeg import CROSSFADE_BATCH, concat

        n = CROSSFADE_BATCH + 2
        clips = [self._clip(f"t{i}.mp4", seconds=1, with_audio=False)
                 for i in range(n)]
        concat(clips, self.tmp / "clean.mp4", width=320, height=240,
               fps=12, crossfade=0.2)
        leftovers = [p for p in self.tmp.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [], f"temp dirs left behind: {leftovers}")

    def test_missing_clip_raises(self):
        from soulclip.ffmpeg import FFmpegError, concat

        with self.assertRaises(FFmpegError):
            concat([self.tmp / "nope.mp4"], self.tmp / "out.mp4")


class TestETA(PipelineTestCase):
    """The bot must measure its own speed rather than trust an estimate."""

    def _timed_provider(self, seconds):
        import time as _t

        class Timed(FakeProvider):
            def generate(self, prompt, dest, *, duration=10, on_status=None):
                _t.sleep(seconds)
                return super().generate(prompt, dest, duration=duration,
                                        on_status=on_status)
        return Timed()

    def test_eta_is_reported_once_enough_clips_are_timed(self):
        lines = []
        p = Pipeline(self._timed_provider(0.05), self.tmp / "w",
                     reporter=lines.append)
        p.render(self.scenes, self.tmp / "o.mp4", stitch=False)
        self.assertTrue(any("to go" in l for l in lines))

    def test_no_eta_before_there_is_data(self):
        """One sample is not enough to extrapolate from."""
        lines = []
        one = parse_script("Scene 1: A single wide shot of an empty road.")
        p = Pipeline(FakeProvider(), self.tmp / "w", reporter=lines.append)
        p.render(one, self.tmp / "o.mp4", stitch=False)
        self.assertFalse(any("to go" in l for l in lines))

    def test_eta_reflects_the_measured_rate(self):
        lines = []
        p = Pipeline(self._timed_provider(0.2), self.tmp / "w",
                     reporter=lines.append)
        p.render(self.scenes, self.tmp / "o.mp4", stitch=False)
        etas = [l for l in lines if "to go" in l]
        self.assertTrue(etas)
        # 0.2s per clip should surface as ~0.2, not a hardcoded guess
        self.assertIn("0.2s/clip", etas[0])

    def test_sub_second_times_are_not_shown_as_zero(self):
        lines = []
        p = Pipeline(self._timed_provider(0.05), self.tmp / "w",
                     reporter=lines.append)
        p.render(self.scenes, self.tmp / "o.mp4", stitch=False)
        for line in [l for l in lines if "to go" in l]:
            self.assertNotIn("avg 0s/clip", line)

    def test_remaining_count_decreases(self):
        lines = []
        p = Pipeline(self._timed_provider(0.05), self.tmp / "w",
                     reporter=lines.append)
        p.render(self.scenes, self.tmp / "o.mp4", stitch=False)
        lefts = [int(l.split("·")[1].split("left")[0].strip())
                 for l in lines if "to go" in l]
        self.assertEqual(lefts, sorted(lefts, reverse=True))


class TestSharedWorkdir(PipelineTestCase):
    """Two workers splitting one film must not destroy each other's clips."""

    def _halves(self):
        return self.scenes[:2], self.scenes[2:]

    def test_second_worker_keeps_first_workers_clips(self):
        first, second = self._halves()
        Pipeline(FakeProvider(), self.tmp / "w",
                 reporter=lambda m: None).render(
            first, self.tmp / "o.mp4", stitch=False)
        Pipeline(FakeProvider(), self.tmp / "w",
                 reporter=lambda m: None).render(
            second, self.tmp / "o.mp4", stitch=False)

        job = Job(self.tmp / "w")
        self.assertEqual(len(job.done()), len(self.scenes))

    def test_final_pass_reuses_everything(self):
        first, second = self._halves()
        for part in (first, second):
            Pipeline(FakeProvider(), self.tmp / "w",
                     reporter=lambda m: None).render(
                part, self.tmp / "o.mp4", stitch=False)

        provider = FakeProvider()
        result = Pipeline(provider, self.tmp / "w",
                          reporter=lambda m: None).render(
            self.scenes, self.tmp / "o.mp4", stitch=False)
        self.assertEqual(provider.calls, [], "re-generated work another worker did")
        self.assertEqual(result.reused, len(self.scenes))

    def test_genuinely_stale_records_are_still_dropped(self):
        """Keeping other workers' clips must not break prompt invalidation."""
        Pipeline(FakeProvider(), self.tmp / "w",
                 reporter=lambda m: None).render(
            self.scenes, self.tmp / "o.mp4", stitch=False)

        job = Job(self.tmp / "w")
        victim = job.records[2]
        Path(victim.path).unlink()          # file gone -> truly stale

        provider = FakeProvider()
        Pipeline(provider, self.tmp / "w",
                 reporter=lambda m: None).render(
            self.scenes, self.tmp / "o.mp4", stitch=False)
        self.assertEqual(len(provider.calls), 1)


class TestConcurrentWorkers(PipelineTestCase):
    """Two processes sharing a workdir (e.g. Kaggle's 2x T4)."""

    def test_save_merges_another_workers_finished_clips(self):
        """Last writer must not revert progress it never saw."""
        first, second = self.scenes[:2], self.scenes[2:]

        job_a = Job(self.tmp / "w", first)
        job_b = Job(self.tmp / "w", second)      # both loaded before either saves

        for job, part in ((job_a, first), (job_b, second)):
            for scene in part:
                clip = self.tmp / "w" / "clips" / f"{scene.slug}.mp4"
                clip.parent.mkdir(parents=True, exist_ok=True)
                clip.write_bytes(b"\0" * 2048)
                rec = job.records[scene.index]
                rec.status, rec.path = "done", str(clip)

        job_a.save()
        job_b.save()                              # would clobber A without the merge

        merged = Job(self.tmp / "w")
        self.assertEqual(len(merged.done()), len(self.scenes))

    def test_merge_does_not_resurrect_a_vanished_clip(self):
        """A 'done' record whose file is gone must still be regenerated."""
        Pipeline(FakeProvider(), self.tmp / "w",
                 reporter=lambda m: None).render(
            self.scenes, self.tmp / "o.mp4", stitch=False)

        job = Job(self.tmp / "w")
        Path(job.records[1].path).unlink()

        provider = FakeProvider()
        result = Pipeline(provider, self.tmp / "w",
                          reporter=lambda m: None).render(
            self.scenes, self.tmp / "o.mp4", stitch=False)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result.reused, len(self.scenes) - 1)

    def test_temp_file_is_process_specific(self):
        """Shared temp names let one worker truncate another's write."""
        import os

        job = Job(self.tmp / "w", self.scenes)
        job.save()
        self.assertIn(str(os.getpid()),
                      str(job.manifest_path.with_suffix(f".json.{os.getpid()}.tmp")))
        leftovers = list((self.tmp / "w").glob("*.tmp"))
        self.assertEqual(leftovers, [], "temp manifest left behind")

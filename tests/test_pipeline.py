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

"""Tests for clip validation and failure classification."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from soulclip.capabilities import Capabilities, for_provider, table
from soulclip.ffmpeg import ffmpeg_path
from soulclip.quality import (
    FailureKind, check_clip, classify, is_black, plan_retry,
)


def _clip(path, seconds=5, size="832x480", black=False):
    src = (f"color=c=black:s={size}:r=24:d={seconds}" if black
           else f"testsrc=s={size}:r=24:d={seconds}")
    subprocess.run(
        [ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i", src,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return path


class TestCheckClip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_good_clip_passes(self):
        r = check_clip(_clip(self.tmp / "g.mp4"), expect_seconds=5)
        self.assertTrue(r.ok, r.summary())
        self.assertEqual(r.width, 832)

    def test_missing_file(self):
        self.assertFalse(check_clip(self.tmp / "nope.mp4").ok)

    def test_empty_file(self):
        p = self.tmp / "e.mp4"
        p.write_bytes(b"")
        self.assertFalse(check_clip(p).ok)

    def test_truncated_file(self):
        good = _clip(self.tmp / "g.mp4")
        bad = self.tmp / "t.mp4"
        bad.write_bytes(good.read_bytes()[:400])
        self.assertFalse(check_clip(bad).ok)

    def test_black_clip_is_rejected(self):
        """A valid file full of black frames is still a failed generation."""
        r = check_clip(_clip(self.tmp / "b.mp4", black=True))
        self.assertFalse(r.ok)
        self.assertTrue(any("black" in p for p in r.problems))

    def test_black_detection_can_be_skipped(self):
        r = check_clip(_clip(self.tmp / "b.mp4", black=True),
                       check_black=False)
        self.assertTrue(r.ok)

    def test_tiny_resolution_is_rejected(self):
        self.assertFalse(check_clip(_clip(self.tmp / "s.mp4",
                                          size="32x24")).ok)

    def test_wrong_duration_warns_but_passes(self):
        """Providers snap to their own frame counts; the stitcher copes."""
        r = check_clip(_clip(self.tmp / "s.mp4", seconds=2), expect_seconds=5)
        self.assertTrue(r.ok)
        self.assertTrue(r.warnings)

    def test_required_audio_is_enforced(self):
        r = check_clip(_clip(self.tmp / "n.mp4"), require_audio=True)
        self.assertFalse(r.ok)

    def test_is_black_on_normal_clip(self):
        self.assertFalse(is_black(_clip(self.tmp / "g.mp4")))


class TestClassify(unittest.TestCase):
    CASES = [
        ("HTTP 429 rate limit exceeded", FailureKind.RATE_LIMIT),
        ("CUDA out of memory", FailureKind.GPU_MEMORY),
        ("Connection reset by peer", FailureKind.NETWORK),
        ("prediction timed out", FailureKind.TIMEOUT),
        ("flagged by content policy", FailureKind.SAFETY_FILTER),
        ("401 unauthorized", FailureKind.AUTH),
        ("503 service unavailable", FailureKind.PROVIDER_BUSY),
        ("clip is empty or unplayable", FailureKind.QUALITY),
        ("400 bad request: invalid prompt", FailureKind.INVALID_PROMPT),
        ("something odd", FailureKind.UNKNOWN),
    ]

    def test_messages_are_classified(self):
        for message, expected in self.CASES:
            self.assertIs(classify(message), expected, message)

    def test_exception_types_win_over_text(self):
        from soulclip.providers import AuthError, PermanentError

        self.assertIs(classify(AuthError("anything")), FailureKind.AUTH)
        self.assertIs(classify(PermanentError("x")), FailureKind.INVALID_PROMPT)

    def test_permanent_kinds_are_not_retryable(self):
        for kind in (FailureKind.AUTH, FailureKind.SAFETY_FILTER,
                     FailureKind.INVALID_PROMPT):
            self.assertFalse(kind.retryable, kind)

    def test_transient_kinds_are_retryable(self):
        for kind in (FailureKind.NETWORK, FailureKind.TIMEOUT,
                     FailureKind.RATE_LIMIT, FailureKind.PROVIDER_BUSY):
            self.assertTrue(kind.retryable, kind)


class TestRetryPlan(unittest.TestCase):
    def test_rate_limit_waits_longer_than_network(self):
        slow = plan_retry("429 rate limit", 1).wait_seconds
        fast = plan_retry("connection reset", 1).wait_seconds
        self.assertGreater(slow, fast)

    def test_backoff_grows(self):
        first = plan_retry("connection reset", 1).wait_seconds
        second = plan_retry("connection reset", 2).wait_seconds
        self.assertGreater(second, first)

    def test_safety_failure_never_retries(self):
        self.assertFalse(plan_retry("blocked by filter", 1).should_retry)

    def test_gives_up_after_the_limit(self):
        self.assertFalse(plan_retry("connection reset", 9,
                                    max_retries=2).should_retry)

    def test_gpu_memory_gives_up_early(self):
        """Repeating an OOM at the same settings is pointless."""
        self.assertFalse(plan_retry("CUDA out of memory", 2).should_retry)


class TestCapabilities(unittest.TestCase):
    def test_unsupported_kwargs_are_dropped(self):
        caps = Capabilities(seed=True)
        kept = caps.filter_kwargs(seed=1, negative="x", image="y.png")
        self.assertEqual(set(kept), {"seed"})

    def test_dropped_lists_what_was_removed(self):
        caps = Capabilities(seed=True)
        self.assertEqual(caps.dropped(seed=1, negative="x"), ["negative"])

    def test_unknown_keys_pass_through(self):
        """Only capability-backed keys are filtered."""
        self.assertIn("prompt", Capabilities().filter_kwargs(prompt="hello"))

    def test_known_providers_are_registered(self):
        for name in ("mock", "ltx", "wan", "replicate", "fal", "xai"):
            self.assertIsNotNone(for_provider(name))

    def test_ltx_supports_image_conditioning(self):
        self.assertTrue(for_provider("ltx").supports("image_reference"))

    def test_wan_does_not_claim_image_conditioning(self):
        self.assertFalse(for_provider("wan").supports("image_reference"))

    def test_unknown_provider_is_conservative(self):
        caps = for_provider("nonexistent")
        self.assertFalse(caps.supports("seed"))
        self.assertFalse(caps.supports("image_reference"))

    def test_instance_attribute_takes_precedence(self):
        class Fake:
            name = "mock"
            capabilities = Capabilities(upscale=True)

        self.assertTrue(for_provider(Fake()).supports("upscale"))

    def test_table_renders(self):
        self.assertIn("provider", table())
        self.assertIn("ltx", table())


if __name__ == "__main__":
    unittest.main()

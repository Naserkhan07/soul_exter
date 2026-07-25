"""Tests for the Wan GPU provider (logic only — no GPU in CI)."""

import json
import unittest
from pathlib import Path

from soulclip.providers import PermanentError, get_provider
from soulclip.wan import KNOWN_MODELS, WAN_FPS, WanProvider, _resolve


class TestFrameMath(unittest.TestCase):
    """Wan requires 4k+1 frames; wrong counts fail deep inside diffusers."""

    def setUp(self):
        self.p = WanProvider(model="wan1.3b")

    def test_frames_are_always_4k_plus_1(self):
        for duration in range(1, 21):
            n = self.p._frames_for(duration)
            self.assertEqual((n - 1) % 4, 0, f"{duration}s gave {n} frames")

    def test_common_durations_map_closely(self):
        for seconds, expected in [(2, 33), (3, 49), (4, 65), (5, 81)]:
            self.assertEqual(self.p._frames_for(seconds), expected)

    def test_long_request_is_capped_to_protect_vram(self):
        # Attention runs across all frames at once; an uncapped 10s clip
        # would exhaust a free T4.
        self.assertLessEqual(self.p._frames_for(60), 81)

    def test_never_below_the_minimum(self):
        self.assertGreaterEqual(self.p._frames_for(0), 9)

    def test_explicit_frames_override(self):
        p = WanProvider(model="wan1.3b", frames=33)
        self.assertEqual(p._frames_for(999), 33)

    def test_frames_round_to_nearest_not_down(self):
        """2s at 16fps is 32 frames; rounding down to 29 loses ~10%."""
        self.assertEqual(self.p._frames_for(2), 33)

    def test_resulting_duration_is_close_to_request(self):
        for seconds in (2, 3, 4, 5):
            actual = self.p._frames_for(seconds) / WAN_FPS
            self.assertLess(abs(actual - seconds), 0.3)


class TestModelResolution(unittest.TestCase):
    def test_shorthand_expands(self):
        self.assertEqual(_resolve("wan1.3b"), KNOWN_MODELS["wan1.3b"])

    def test_shorthand_is_punctuation_insensitive(self):
        for alias in ("wan1.3b", "wan-1.3b", "WAN1.3B"):
            self.assertEqual(_resolve(alias), KNOWN_MODELS["wan1.3b"])

    def test_full_repo_id_passes_through(self):
        self.assertEqual(_resolve("some/other-model"), "some/other-model")


class TestRegistration(unittest.TestCase):
    def test_wan_is_selectable(self):
        self.assertIsInstance(get_provider("wan"), WanProvider)

    def test_options_are_carried(self):
        p = get_provider("wan", steps=12, guidance=6.5)
        self.assertEqual(p.options["steps"], 12)
        self.assertEqual(p.options["guidance"], 6.5)

    def test_missing_torch_is_a_permanent_error(self):
        """A missing dependency must not burn the retry budget."""
        with self.assertRaises(PermanentError):
            WanProvider(model="wan1.3b")._load()


class TestNotebook(unittest.TestCase):
    def setUp(self):
        self.path = Path("notebooks/soulclip_colab.ipynb")

    def test_notebook_is_valid_json(self):
        nb = json.loads(self.path.read_text())
        self.assertGreater(len(nb["cells"]), 5)

    def test_requests_a_gpu_runtime(self):
        nb = json.loads(self.path.read_text())
        self.assertEqual(nb["metadata"]["accelerator"], "GPU")

    def test_render_cell_uses_the_wan_provider(self):
        text = self.path.read_text()
        self.assertIn("--provider wan", text)
        self.assertIn("--workdir", text, "must set a workdir so resume works")


if __name__ == "__main__":
    unittest.main()

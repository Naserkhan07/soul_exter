"""Tests for the still-to-motion engine (the free generation path)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from soulclip.ffmpeg import FFmpegError, ffmpeg_path, probe_duration
from soulclip.motion import MOVES, MotionStyle, animate_still, pick_move


def _still(path: Path, size="1600x900"):
    subprocess.run(
        [ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=s={size}:d=1", "-frames:v", "1", str(path)],
        check=True, capture_output=True,
    )
    return path


def _gray(video: Path, t: float) -> bytes:
    return subprocess.run(
        [ffmpeg_path(), "-v", "error", "-ss", str(t), "-i", str(video),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout


def _difference(a: bytes, b: bytes) -> float:
    n = min(len(a), len(b))
    return sum(abs(a[i] - b[i]) for i in range(n)) / max(n, 1)


class TestAnimateStill(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.img = _still(self.tmp / "in.png")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_produces_a_playable_clip(self):
        out = animate_still(self.img, self.tmp / "o.mp4", duration=2)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 5000)
        self.assertAlmostEqual(probe_duration(out) or 0, 2, delta=0.4)

    def test_camera_actually_moves(self):
        """A still must become genuinely moving footage, not a freeze frame."""
        out = animate_still(
            self.img, self.tmp / "move.mp4", duration=4, move="push_in",
            style=MotionStyle(intensity=0.25, fade=0, grain=0),
        )
        early, late = _gray(out, 0.5), _gray(out, 3.5)
        self.assertGreater(
            _difference(early, late), 1.5,
            "frames are nearly identical — the camera is not moving",
        )

    def test_every_move_renders(self):
        for move in MOVES:
            out = animate_still(
                self.img, self.tmp / f"{move}.mp4", duration=1.5, move=move
            )
            self.assertGreater(out.stat().st_size, 3000, f"{move} produced nothing")

    def test_moves_differ_from_each_other(self):
        a = animate_still(self.img, self.tmp / "l.mp4", duration=2,
                          move="pan_left", style=MotionStyle(fade=0, grain=0))
        b = animate_still(self.img, self.tmp / "r.mp4", duration=2,
                          move="pan_right", style=MotionStyle(fade=0, grain=0))
        self.assertGreater(
            _difference(_gray(a, 1.5), _gray(b, 1.5)), 1.0,
            "pan_left and pan_right produced the same picture",
        )

    def test_output_size_is_respected(self):
        out = animate_still(self.img, self.tmp / "s.mp4", duration=1,
                            width=640, height=360)
        info = subprocess.run(
            [ffmpeg_path(), "-i", str(out)], capture_output=True, text=True
        ).stderr
        self.assertIn("640x360", info)

    def test_clip_has_audio_for_clean_concat(self):
        from soulclip.ffmpeg import has_audio

        out = animate_still(self.img, self.tmp / "a.mp4", duration=1)
        self.assertTrue(has_audio(out), "clip needs a silent track to concat")

    def test_letterbox_darkens_top_and_bottom(self):
        out = animate_still(
            self.img, self.tmp / "lb.mp4", duration=1.5, width=640, height=360,
            style=MotionStyle(letterbox=0.2, fade=0, grain=0, vignette=False),
        )
        frame = _gray(out, 1.0)
        top_row = frame[:640]
        self.assertLess(sum(top_row) / len(top_row), 20, "no black bar on top")

    def test_missing_image_raises(self):
        with self.assertRaises(FFmpegError):
            animate_still(self.tmp / "nope.png", self.tmp / "x.mp4")

    def test_pick_move_varies_between_shots(self):
        picks = [pick_move(i) for i in range(len(MOVES))]
        self.assertEqual(len(set(picks)), len(MOVES))
        self.assertNotEqual(pick_move(0), pick_move(1))


class TestFolderProvider(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.art = self.tmp / "art"
        self.art.mkdir()
        for i in range(3):
            _still(self.art / f"{i}.png", size="1280x720")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generates_clip_from_folder(self):
        from soulclip.providers import get_provider

        p = get_provider("folder", str(self.art), seed=1)
        out = self.tmp / "clip.mp4"
        result = p.generate("a test scene", out, duration=2)
        self.assertTrue(result.path.exists())
        self.assertAlmostEqual(probe_duration(out) or 0, 2, delta=0.4)

    def test_missing_folder_is_permanent_error(self):
        from soulclip.providers import PermanentError, get_provider

        p = get_provider("folder", str(self.tmp / "gone"), seed=1)
        with self.assertRaises(PermanentError):
            p.generate("x", self.tmp / "c.mp4", duration=1)


if __name__ == "__main__":
    unittest.main()

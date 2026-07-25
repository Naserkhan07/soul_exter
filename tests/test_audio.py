"""Tests for narration timing and the audio mix."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from soulclip.audio import AudioError, AudioMix, _speakable, fit_to_duration, mix
from soulclip.ffmpeg import ffmpeg_path, probe_duration


def _tone(path: Path, seconds: float, freq: int = 440):
    subprocess.run(
        [ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}", str(path)],
        check=True, capture_output=True,
    )
    return path


def _video(path: Path, seconds: float = 10):
    subprocess.run(
        [ffmpeg_path(), "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc=s=320x240:r=24:d={seconds}",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-t", str(seconds), str(path)],
        check=True, capture_output=True,
    )
    return path


class TestSpeakable(unittest.TestCase):
    """Camera directions must never be read aloud."""

    def test_strips_setting_block(self):
        out = _speakable("A lighthouse at dusk. Setting: rain and wind.")
        self.assertNotIn("Setting", out)
        self.assertIn("lighthouse", out)

    def test_strips_continuation_instruction(self):
        out = _speakable("Waves crash. Continuous shot, part 2 of 3: more.")
        self.assertNotIn("Continuous shot", out)

    def test_strips_style_words(self):
        out = _speakable("A keeper winds a lamp, cinematic anime, film grain")
        self.assertNotIn("cinematic", out.lower())
        self.assertNotIn("film grain", out.lower())
        self.assertIn("keeper", out)


class TestFitToDuration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pads_short_audio(self):
        src = _tone(self.tmp / "s.wav", 2)
        out = fit_to_duration(src, 5, self.tmp / "o.wav")
        self.assertAlmostEqual(probe_duration(out) or 0, 5, delta=0.2)

    def test_compresses_long_audio(self):
        """Narration overrunning its clip would bleed into the next scene."""
        src = _tone(self.tmp / "l.wav", 7)
        out = fit_to_duration(src, 5, self.tmp / "o.wav")
        self.assertAlmostEqual(probe_duration(out) or 0, 5, delta=0.2)

    def test_speedup_is_capped(self):
        """Extreme compression sounds absurd; truncate instead."""
        src = _tone(self.tmp / "vl.wav", 20)
        out = fit_to_duration(src, 5, self.tmp / "o.wav", max_speedup=1.4)
        self.assertAlmostEqual(probe_duration(out) or 0, 5, delta=0.2)

    def test_missing_file_raises(self):
        with self.assertRaises(AudioError):
            fit_to_duration(self.tmp / "nope.wav", 5, self.tmp / "o.wav")


class TestMix(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.video = _video(self.tmp / "v.mp4", 10)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _loudness(self, path):
        out = subprocess.run(
            [ffmpeg_path(), "-i", str(path), "-af", "volumedetect",
             "-f", "null", "-"], capture_output=True, text=True).stderr
        for line in out.splitlines():
            if "mean_volume" in line:
                return float(line.split("mean_volume:")[1].split("dB")[0])
        return None

    def test_narration_only(self):
        narr = _tone(self.tmp / "n.wav", 10, 300)
        out = mix(self.video, self.tmp / "o.mp4", narration=narr)
        self.assertAlmostEqual(probe_duration(out) or 0, 10, delta=0.3)

    def test_music_only(self):
        music = _tone(self.tmp / "m.wav", 4, 800)
        out = mix(self.video, self.tmp / "o.mp4", music=music)
        self.assertAlmostEqual(probe_duration(out) or 0, 10, delta=0.3)

    def test_short_music_is_looped_to_fill(self):
        music = _tone(self.tmp / "m.wav", 3, 800)
        out = mix(self.video, self.tmp / "o.mp4", music=music)
        self.assertAlmostEqual(probe_duration(out) or 0, 10, delta=0.3)

    def test_all_three_layers(self):
        out = mix(
            self.video, self.tmp / "o.mp4",
            narration=_tone(self.tmp / "n.wav", 10, 300),
            music=_tone(self.tmp / "m.wav", 4, 800),
            ambience=_tone(self.tmp / "a.wav", 3, 120),
        )
        self.assertGreater(out.stat().st_size, 10_000)

    def test_music_sits_below_narration(self):
        narr_only = mix(self.video, self.tmp / "n.mp4",
                        narration=_tone(self.tmp / "n.wav", 10, 300))
        music_only = mix(self.video, self.tmp / "m.mp4",
                         music=_tone(self.tmp / "m.wav", 10, 800))
        self.assertLess(self._loudness(music_only), self._loudness(narr_only),
                        "music is not quieter than narration")

    def test_video_stream_is_preserved(self):
        out = mix(self.video, self.tmp / "o.mp4",
                  music=_tone(self.tmp / "m.wav", 4))
        info = subprocess.run([ffmpeg_path(), "-i", str(out)],
                              capture_output=True, text=True).stderr
        self.assertIn("Video:", info)
        self.assertIn("320x240", info)

    def test_nothing_to_mix_raises(self):
        with self.assertRaises(AudioError):
            mix(self.video, self.tmp / "o.mp4")

    def test_levels_are_configurable(self):
        loud = mix(self.video, self.tmp / "loud.mp4",
                   music=_tone(self.tmp / "m.wav", 10),
                   levels=AudioMix(music=0.9, fade=0))
        quiet = mix(self.video, self.tmp / "quiet.mp4",
                    music=_tone(self.tmp / "m2.wav", 10),
                    levels=AudioMix(music=0.05, fade=0))
        self.assertGreater(self._loudness(loud), self._loudness(quiet))


class TestNarrationResilience(unittest.TestCase):
    """A missing TTS dependency must not destroy the film."""

    def test_missing_backend_raises_audio_error(self):
        from soulclip.audio import Narrator

        tmp = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(AudioError):
                Narrator().speak("hello", tmp / "x.wav")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

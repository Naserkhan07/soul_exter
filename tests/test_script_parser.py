"""Tests for script parsing and scene splitting."""

import unittest

from soulclip.script_parser import (
    Scene, ScriptError, parse_script, summarize,
)


class TestParsing(unittest.TestCase):
    def test_numbered_scenes(self):
        scenes = parse_script(
            "Scene 1: A cat sits on a wall in the rain, watching cars pass.\n"
            "Scene 2: The cat jumps down and vanishes into a hedge."
        )
        self.assertEqual(len(scenes), 2)
        self.assertTrue(scenes[0].text.startswith("A cat sits"))
        self.assertEqual(scenes[0].source_scene, 1)
        self.assertEqual(scenes[1].source_scene, 2)

    def test_various_header_styles(self):
        script = (
            "SCENE 1 - Dawn over a quiet harbour with fishing boats rocking.\n"
            "[Scene 2]\n"
            "Gulls lift off the water in a wide spiral above the masts.\n"
            "Shot 3. A fisherman coils rope on a wet deck, breath steaming.\n"
        )
        scenes = parse_script(script)
        self.assertEqual(len(scenes), 3)
        self.assertEqual([s.source_scene for s in scenes], [1, 2, 3])
        self.assertIn("harbour", scenes[0].text)
        self.assertIn("Gulls", scenes[1].text)
        self.assertIn("fisherman", scenes[2].text)

    def test_blank_line_separated_without_headers(self):
        script = (
            "A market street at noon, awnings snapping in the wind.\n\n"
            "A child chases a red balloon between the stalls.\n\n"
            "The balloon escapes above the rooftops into open sky.\n"
        )
        scenes = parse_script(script)
        self.assertEqual(len(scenes), 3)
        self.assertIn("balloon escapes", scenes[2].text)

    def test_horizontal_rule_separator(self):
        script = "First shot of a rainy street.\n---\nSecond shot of a dry desert.\n"
        self.assertEqual(len(parse_script(script)), 2)

    def test_multiline_scene_body_is_joined(self):
        script = (
            "Scene 1: A long tracking shot\n"
            "down a corridor of servers,\n"
            "blue lights blinking in sequence.\n"
        )
        scenes = parse_script(script)
        self.assertEqual(len(scenes), 1)
        self.assertNotIn("\n", scenes[0].text)
        self.assertIn("corridor of servers", scenes[0].text)

    def test_empty_script_raises(self):
        with self.assertRaises(ScriptError):
            parse_script("   \n\n  ")

    def test_indices_are_sequential(self):
        scenes = parse_script("Scene 5: Alpha shot.\n\nScene 9: Beta shot.")
        self.assertEqual([s.index for s in scenes], [1, 2])
        # Declared numbers are preserved for labelling.
        self.assertEqual([s.source_scene for s in scenes], [5, 9])


class TestTargetLength(unittest.TestCase):
    LONG = (
        "Scene 1: A lone astronaut stands on a red dune under an amber sun. "
        "Wind lifts fine dust across the frame in slow ribbons. "
        "The visor reflects a shrinking horizon.\n\n"
        "Scene 2: The wreck of a colony ship lies half buried in sand. "
        "Its hull ribs arch like the bones of a whale. "
        "Sand pours steadily through a torn seam.\n"
    )

    def test_hits_five_minutes(self):
        scenes = parse_script(self.LONG, clip_seconds=10, target_seconds=300)
        self.assertEqual(len(scenes), 30)
        self.assertEqual(sum(s.duration for s in scenes), 300)

    def test_target_respects_clip_length(self):
        scenes = parse_script(self.LONG, clip_seconds=5, target_seconds=60)
        self.assertEqual(len(scenes), 12)
        self.assertTrue(all(s.duration == 5 for s in scenes))

    def test_max_scenes_caps_cost(self):
        scenes = parse_script(
            self.LONG, clip_seconds=10, target_seconds=300, max_scenes=8
        )
        self.assertLessEqual(len(scenes), 8)

    def test_no_target_means_one_clip_per_scene(self):
        scenes = parse_script(self.LONG, clip_seconds=10)
        self.assertEqual(len(scenes), 2)

    def test_prompts_are_never_mid_sentence_fragments(self):
        """Splitting must not produce dangling fragments like 'of red dune,'."""
        scenes = parse_script(self.LONG, clip_seconds=10, target_seconds=300)
        for scene in scenes:
            first = scene.text.split()[0]
            self.assertTrue(
                first[0].isupper() or first[0] in "\"'“",
                f"prompt {scene.index} starts mid-sentence: {scene.text[:60]!r}",
            )

    def test_prompts_are_substantial(self):
        scenes = parse_script(self.LONG, clip_seconds=10, target_seconds=300)
        for scene in scenes:
            self.assertGreaterEqual(
                len(scene.text), 40,
                f"prompt {scene.index} is too thin: {scene.text!r}",
            )

    def test_single_sentence_scene_padded_with_continuations(self):
        scenes = parse_script(
            "Scene 1: A single unbroken shot of a candle burning down.",
            clip_seconds=10, target_seconds=40,
        )
        self.assertEqual(len(scenes), 4)
        self.assertIn("Continuous shot", scenes[1].text)
        # The original description survives in every part.
        for scene in scenes:
            self.assertIn("candle", scene.text)

    def test_short_beat_gets_scene_context(self):
        scenes = parse_script(
            "Scene 1: Wide shot. The camera pulls back to reveal a ruined "
            "cathedral standing alone in a field of tall summer grass.",
            clip_seconds=10, target_seconds=20,
        )
        self.assertEqual(len(scenes), 2)
        short = scenes[0]
        if len(short.text) < 60 or short.text.startswith("Wide shot."):
            self.assertIn("Setting:", short.text)

    def test_ordering_is_preserved(self):
        scenes = parse_script(self.LONG, clip_seconds=10, target_seconds=120)
        self.assertEqual([s.index for s in scenes], list(range(1, len(scenes) + 1)))
        firsts = [s.source_scene for s in scenes]
        self.assertEqual(firsts, sorted(firsts))


class TestScene(unittest.TestCase):
    def test_slug_is_zero_padded_and_sorts(self):
        self.assertEqual(Scene(1, "x").slug, "scene_001")
        self.assertEqual(Scene(30, "x").slug, "scene_030")
        names = [Scene(i, "x").slug for i in (2, 10, 1)]
        self.assertEqual(sorted(names), ["scene_001", "scene_002", "scene_010"])

    def test_label_shows_parts(self):
        self.assertEqual(
            Scene(3, "x", source_scene=2, part=2, parts_total=4).label,
            "scene 2 (part 2/4)",
        )
        self.assertEqual(Scene(3, "x", source_scene=2).label, "scene 2")

    def test_summarize(self):
        scenes = [Scene(i, "x", duration=10) for i in range(1, 31)]
        self.assertIn("5m 00s", summarize(scenes))


if __name__ == "__main__":
    unittest.main()

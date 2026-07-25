"""Tests for prose -> shot list, and character consistency."""

import unittest

from soulclip.script_parser import parse_script
from soulclip.storyboard import (
    Storyboard, build, find_characters, split_story,
)

STORY = (
    "The old keeper Alden lived alone in a lighthouse on a black rock "
    "headland. Every night he climbed the spiral stair to wind the great "
    "lamp by hand. One evening a storm rolled in from the west. Alden heard "
    "a sound that did not belong to the water. A young woman named Mira "
    "clung to the broken mast. Alden hauled the signal lever. By dawn the "
    "storm had passed and Mira sat on the steps wrapped in a blanket."
)


class TestCharacters(unittest.TestCase):
    def test_finds_recurring_names(self):
        chars = find_characters(STORY)
        self.assertIn("Alden", chars)
        self.assertIn("Mira", chars)

    def test_counts_names_that_open_sentences(self):
        """'Alden ran...' must count — he is the main character."""
        self.assertGreaterEqual(find_characters(STORY)["Alden"].mentions, 3)

    def test_ignores_common_sentence_openers(self):
        chars = find_characters(STORY)
        for word in ("The", "Every", "One", "By", "A"):
            self.assertNotIn(word, chars)

    def test_description_is_a_usable_phrase(self):
        chars = find_characters(STORY)
        self.assertIn("keeper", chars["Alden"].description)
        self.assertIn("woman", chars["Mira"].description)

    def test_description_excludes_connectives(self):
        """'a young woman named Mira' must not yield 'young woman named'."""
        self.assertNotIn("named", find_characters(STORY)["Mira"].description)

    def test_description_does_not_cross_clauses(self):
        """'...wrapped in a blanket. Mira' must not yield 'a blanket'."""
        desc = find_characters(STORY)["Mira"].description
        for wrong in ("blanket", "storm", "passed"):
            self.assertNotIn(wrong, desc)

    def test_one_off_names_are_ignored(self):
        chars = find_characters("Bob walked once. The dog barked.")
        self.assertNotIn("Bob", chars)


class TestSplitting(unittest.TestCase):
    def test_respects_requested_count(self):
        self.assertEqual(len(split_story(STORY, scenes=4)), 4)

    def test_derives_count_from_target_seconds(self):
        self.assertEqual(len(split_story(STORY, scenes=None,
                                         target_seconds=30, clip_seconds=5)), 6)

    def test_never_splits_mid_sentence(self):
        for shot in split_story(STORY, scenes=4):
            self.assertTrue(shot[0].isupper(), f"starts mid-sentence: {shot!r}")

    def test_empty_story(self):
        self.assertEqual(split_story("   "), [])


class TestStoryboard(unittest.TestCase):
    def test_emits_parsable_script(self):
        board = build(STORY, target_seconds=40, clip_seconds=5)
        scenes = parse_script(board.to_script(), clip_seconds=5)
        self.assertGreaterEqual(len(scenes), 4)

    def test_character_description_is_carried_into_shots(self):
        """The whole point: the model must be re-told who Alden is."""
        board = build(STORY, target_seconds=40, clip_seconds=5)
        script = board.to_script()
        alden_shots = [s for s in script.split("\n\n") if "Alden" in s]
        self.assertTrue(alden_shots)
        self.assertTrue(
            any("Alden is" in s for s in alden_shots),
            "no shot re-describes Alden, so he will drift between clips",
        )

    def test_style_is_appended(self):
        board = build(STORY, scenes=3, style="watercolour anime")
        self.assertIn("watercolour anime", board.to_script())

    def test_characters_can_be_suppressed(self):
        board = build(STORY, scenes=3)
        self.assertNotIn("Alden is", board.to_script(with_characters=False))

    def test_unknown_backend_raises(self):
        from soulclip.storyboard import StoryboardError

        with self.assertRaises(StoryboardError):
            build(STORY, backend="nope")


if __name__ == "__main__":
    unittest.main()

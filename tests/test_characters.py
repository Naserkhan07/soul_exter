"""Tests for persistent character profiles and prompt injection."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from soulclip.capabilities import for_provider
from soulclip.characters import Character, CharacterBook, from_detected, slugify
from soulclip.prompts import PromptBuilder, infer_lighting, infer_shot
from soulclip.script_parser import parse_script


class TestCharacter(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_slugify(self):
        self.assertEqual(slugify("Old Keeper"), "old_keeper")
        self.assertEqual(slugify("Father!"), "father")

    def test_describe_builds_a_clause(self):
        c = Character(name="Father", age=42, gender="male",
                      appearance="black hair, trimmed beard",
                      clothes="white kurta")
        text = c.describe()
        self.assertIn("Father", text)
        self.assertIn("42-year-old male", text)
        self.assertIn("wearing white kurta", text)

    def test_describe_handles_sparse_profiles(self):
        self.assertEqual(Character(name="Ghost").describe(), "Ghost")

    def test_round_trip(self):
        c = Character(name="Mira", age=24, gender="female",
                      appearance="long dark hair", seed=99)
        c.save(self.tmp)
        loaded = Character.load(self.tmp / "mira")
        self.assertEqual(loaded.name, "Mira")
        self.assertEqual(loaded.seed, 99)
        self.assertEqual(loaded.age, 24)

    def test_unknown_fields_do_not_crash(self):
        """A profile from a newer version must still load."""
        d = self.tmp / "future"
        d.mkdir()
        (d / "profile.json").write_text(json.dumps(
            {"name": "Future", "appearance": "x", "hologram_mode": True}))
        loaded = Character.load(d)
        self.assertEqual(loaded.name, "Future")

    def test_reference_image_is_found(self):
        c = Character(name="Father")
        c.save(self.tmp)
        self.assertIsNone(c.reference)
        (self.tmp / "father" / "reference.png").write_bytes(b"\x89PNG")
        self.assertIsNotNone(c.reference)


class TestCharacterBook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = CharacterBook(self.tmp)
        self.book.add(Character(name="Father", age=42, gender="male",
                                appearance="black hair", seed=345234,
                                negative_prompt="extra limbs"))
        self.book.add(Character(name="Arjun", age=8, gender="male",
                                appearance="messy hair"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persists_to_disk(self):
        reloaded = CharacterBook(self.tmp)
        self.assertEqual(len(reloaded), 2)
        self.assertEqual(reloaded.get("father").seed, 345234)

    def test_lookup_is_case_insensitive(self):
        self.assertIsNotNone(self.book.get("FATHER"))
        self.assertIsNotNone(self.book.get("father"))

    def test_present_in_finds_named_characters(self):
        present = self.book.present_in("Father speaks to Arjun quietly.")
        self.assertEqual([c.name for c in present], ["Father", "Arjun"])

    def test_present_in_respects_word_boundaries(self):
        """'grandfather' must not match the 'Father' profile."""
        self.assertEqual(self.book.present_in("The grandfather clock ticks."),
                         [])

    def test_present_in_orders_by_appearance(self):
        present = self.book.present_in("Arjun runs, then Father follows.")
        self.assertEqual([c.name for c in present], ["Arjun", "Father"])

    def test_merged_negatives_deduplicate(self):
        self.book.add(Character(name="Mira", negative_prompt="extra limbs, blur"))
        merged = self.book.negative_prompts()
        self.assertEqual(merged.count("extra limbs"), 1)

    def test_from_detected_strips_articles(self):
        class Info:
            description = "an old keeper"
        chars = from_detected({"Alden": Info()})
        self.assertEqual(chars[0].appearance, "old keeper")


class TestPromptBuilder(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = CharacterBook(self.tmp)
        self.book.add(Character(
            name="Father", age=42, gender="male",
            appearance="black hair, trimmed beard",
            clothes="white kurta", seed=345234,
            negative_prompt="duplicate person"))
        self.scenes = parse_script(
            "Scene 1: Close-up of Father smiling inside a warmly lit room.\n\n"
            "Scene 2: Wide shot of the valley at dawn with mist.\n"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_injects_character_description(self):
        """The whole point: never make the user repeat this."""
        parts = PromptBuilder(self.book).build(self.scenes[0])
        self.assertIn("black hair", parts.text())
        self.assertIn("white kurta", parts.text())

    def test_absent_characters_are_not_injected(self):
        parts = PromptBuilder(self.book).build(self.scenes[1])
        self.assertNotIn("kurta", parts.text())

    def test_character_seed_wins_over_base_seed(self):
        b = PromptBuilder(self.book, base_seed=1000)
        self.assertEqual(b.build(self.scenes[0]).seed, 345234)
        self.assertEqual(b.build(self.scenes[1]).seed, 1002)

    def test_infers_shot_and_lighting(self):
        self.assertIn("close-up", infer_shot("A close-up of a face"))
        self.assertIn("wide", infer_shot("A wide establishing landscape"))
        self.assertIn("golden", infer_lighting("at dawn over the sea"))

    def test_base_negatives_always_present(self):
        parts = PromptBuilder(self.book).build(self.scenes[0])
        self.assertIn("blurry", parts.negative)

    def test_character_negatives_are_merged(self):
        parts = PromptBuilder(self.book).build(self.scenes[0])
        self.assertIn("duplicate person", parts.negative)

    def test_style_is_appended(self):
        b = PromptBuilder(self.book, style="Pixar-quality animation")
        self.assertIn("Pixar-quality", b.build(self.scenes[0]).text())

    def test_strips_parser_bookkeeping(self):
        scenes = parse_script(
            "Scene 1: A lighthouse beam sweeps out to sea. "
            "Setting: rain and wind on the headland.")
        text = PromptBuilder().build(scenes[0]).text()
        self.assertNotIn("Setting:", text)

    def test_capabilities_strip_unsupported_fields(self):
        """A provider without seed support must not be sent one."""
        parts = PromptBuilder(self.book).build(
            self.scenes[0], capabilities=for_provider("xai"))
        self.assertIsNone(parts.seed)
        self.assertEqual(parts.negative, "")

    def test_capable_provider_keeps_fields(self):
        parts = PromptBuilder(self.book).build(
            self.scenes[0], capabilities=for_provider("ltx"))
        self.assertEqual(parts.seed, 345234)
        self.assertTrue(parts.negative)


if __name__ == "__main__":
    unittest.main()

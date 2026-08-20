import json
import unittest
from pathlib import Path

from training.build_curriculum import build
from training.build_benchmarks import CASES
from training.validate_training import validate

ROOT = Path(__file__).resolve().parents[1]


class TrainingPipelineTests(unittest.TestCase):
    def test_generated_curriculum_is_reproducible_and_diverse(self):
        examples = build()
        self.assertEqual(len(examples), 62)
        categories = {example["category"] for example in examples}
        self.assertEqual(categories, {"game_builder", "game_quality", "web_tool", "digital_product",
                                      "policy", "debugging", "data_product", "research"})
        for example in examples:
            answer = json.loads(example["messages"][2]["content"])
            self.assertEqual(set(answer), {"decision", "plan", "deliverable", "validation", "distribution", "risks"})

    def test_held_out_benchmarks_cover_safety_and_quality(self):
        self.assertEqual(len(CASES), 20)
        identifiers = [case[0] for case in CASES]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertIn("fps_scope", identifiers)
        self.assertIn("payment_idempotency", identifiers)
        self.assertIn("job_bot_rules", identifiers)

    def test_committed_training_files_pass_validation(self):
        result = validate(ROOT / "training/automaton_train.jsonl",
                          ROOT / "training/automaton_benchmark.jsonl")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["training_records"], 62)
        self.assertEqual(result["benchmark_records"], 20)


if __name__ == "__main__":
    unittest.main()

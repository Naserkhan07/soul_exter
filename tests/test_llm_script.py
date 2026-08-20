import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from scripts.test_llm import main


class LLMConfigurationScriptTests(unittest.TestCase):
    def test_rejects_documentation_placeholders_without_network(self):
        env = {
            "LLM_BASE_URL": "https://random-name.trycloudflare.com/v1",
            "LLM_API_KEY": "<private-random-token>",
            "LLM_MODEL": "Qwen/Qwen2.5-3B-Instruct",
        }
        errors = io.StringIO()
        with patch.dict(os.environ, env, clear=True), redirect_stderr(errors):
            self.assertEqual(main(), 2)
        self.assertIn("placeholders", errors.getvalue())

    def test_rejects_url_without_v1(self):
        env = {"LLM_BASE_URL": "https://actual.trycloudflare.com", "LLM_API_KEY": "valid_token"}
        errors = io.StringIO()
        with patch.dict(os.environ, env, clear=True), redirect_stderr(errors):
            self.assertEqual(main(), 2)
        self.assertIn("/v1", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

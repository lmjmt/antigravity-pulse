import os
import sys
import unittest

SIDE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sidecars", "task_monitor"))
if SIDE_DIR not in sys.path:
    sys.path.insert(0, SIDE_DIR)

from core.models import UNKNOWN_MODEL_LABEL, get_model_family, normalize_model_name


class TestModelNormalization(unittest.TestCase):
    def test_strip_effort_from_human_names(self):
        self.assertEqual(normalize_model_name("Gemini 4 Neon (High)"), "Gemini 4 Neon")
        self.assertEqual(normalize_model_name("Gemini 4 Neon (XHigh)"), "Gemini 4 Neon")
        self.assertEqual(normalize_model_name("Gemini 3.8 Flash (Low)"), "Gemini 3.8 Flash")
        self.assertEqual(normalize_model_name("Claude Sonnet 4.6 (Thinking)"), "Claude Sonnet 4.6")
        self.assertEqual(normalize_model_name("GPT-OSS 120B (Medium)"), "GPT-OSS 120B")

    def test_preserve_non_effort_parentheticals(self):
        self.assertEqual(normalize_model_name("Orchestrator (Argon)"), "Orchestrator (Argon)")
        self.assertEqual(normalize_model_name(UNKNOWN_MODEL_LABEL), UNKNOWN_MODEL_LABEL)

    def test_normalize_slugs_and_merge_with_display(self):
        self.assertEqual(normalize_model_name("gemini-4-neon-xhigh"), "Gemini 4 Neon")
        self.assertEqual(normalize_model_name("gemini-3.8-flash-high"), "Gemini 3.8 Flash")
        self.assertEqual(normalize_model_name("gemini-3-1-pro-low"), "Gemini 3.1 Pro")
        self.assertEqual(normalize_model_name("claude-opus-5-5-high"), "Claude Opus 5.5")
        self.assertEqual(normalize_model_name("claude-sonnet-4-6"), "Claude Sonnet 4.6")
        self.assertEqual(normalize_model_name("gpt-oss-120b-medium"), "GPT-OSS 120B")

    def test_empty_and_none(self):
        self.assertEqual(normalize_model_name(None), "")
        self.assertEqual(normalize_model_name("  "), "")
        self.assertEqual(normalize_model_name("None"), "")

    def test_model_family(self):
        self.assertEqual(get_model_family("Gemini 4 Neon"), "Gemini")
        self.assertEqual(get_model_family("Claude Opus 5.5"), "Claude")
        self.assertEqual(get_model_family("GPT-OSS 120B"), "GPT")
        self.assertEqual(get_model_family("Orchestrator (Argon)"), "Orchestrator")
        self.assertEqual(get_model_family(UNKNOWN_MODEL_LABEL), "未记录")
        self.assertEqual(get_model_family("CustomLocalModel"), "其他")


if __name__ == "__main__":
    unittest.main()

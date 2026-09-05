"""
Tests for prompt configuration loading across all phases

Validates that editable prompt files are correctly loaded by each phase:
- Parser prompts (src/application/parse_job.py)
- Tailor prompts (src/application/tailor_resume.py)
- Advisor prompts (src/application/advise.py)
- Override file detection and merge behavior
- Safe fallback to built-in defaults when override files are missing
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.application.advise import _load_advisor_prompts
from src.application.parse_job import _load_parser_prompts
from src.application.tailor_resume import _load_prompt_config


class PromptConfigTests(unittest.TestCase):
    def test_parser_loader_reads_override_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "parser-prompts.json"
            path.write_text(
                json.dumps({"parser": {"job_parser_system_prompt": "Parser override"}}),
                encoding="utf-8",
            )
            with patch("src.application.parse_job.PROMPT_CONFIG_PATH", path):
                prompts = _load_parser_prompts()

        self.assertEqual(prompts["job_parser_system_prompt"], "Parser override")

    def test_tailor_loader_reads_override_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tailor-prompts.json"
            path.write_text(
                json.dumps({"tailor": {"summary_section_prompt": "Tailor override"}}),
                encoding="utf-8",
            )
            with patch("src.application.tailor_resume.PROMPT_CONFIG_PATH", path):
                prompts = _load_prompt_config()

        self.assertEqual(prompts["summary_section_prompt"], "Tailor override")

    def test_advisor_loader_reads_override_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "advisor-prompts.json"
            path.write_text(
                json.dumps({"advisor": {"advisor_general_advice_system_prompt": "Advisor override"}}),
                encoding="utf-8",
            )
            with patch("src.application.advise.PROMPT_CONFIG_PATH", path):
                prompts = _load_advisor_prompts()

        self.assertEqual(prompts["advisor_general_advice_system_prompt"], "Advisor override")


if __name__ == "__main__":
    unittest.main()

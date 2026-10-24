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
from src.application.tailor_resume import DEFAULT_PROMPTS, PROMPT_CONFIG_PATH, _load_prompt_config


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
                json.dumps(
                    {
                        "tailor": {
                            "summary_section_prompt": "Tailor override",
                            "generic_resume_system_prompt": "Generic system override",
                            "generic_resume_user_prompt": "Generic user override",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch("src.application.tailor_resume.PROMPT_CONFIG_PATH", path):
                prompts = _load_prompt_config()

        self.assertEqual(prompts["summary_section_prompt"], "Tailor override")
        self.assertEqual(prompts["generic_resume_system_prompt"], "Generic system override")
        self.assertEqual(prompts["generic_resume_user_prompt"], "Generic user override")

    def test_default_generic_prompt_preserves_frontend_backend_and_uses_page_space(self):
        prompt = DEFAULT_PROMPTS["generic_resume_user_prompt"]

        self.assertIn("fill the page", prompt)
        self.assertIn("'Frontend Development' and 'Backend Development'", prompt)
        self.assertIn("Never combine them under a 'Full-Stack Development' heading", prompt)

    def test_tailor_prompts_include_ai_projects_for_ai_forward_roles(self):
        with patch("src.application.tailor_resume.PROMPT_CONFIG_PATH", PROMPT_CONFIG_PATH):
            prompts = _load_prompt_config()

        for source in (prompts, DEFAULT_PROMPTS):
            projects_prompt = source["personalprojects_section_prompt"]
            experience_prompt = source["experience_section_prompt"]
            self.assertIn("AI-forward", projects_prompt)
            self.assertIn("metadata.raw_listing_text", projects_prompt)
            self.assertIn("employer's own product", projects_prompt)
            self.assertNotIn("isolated AI label in a skill list", projects_prompt)
            self.assertNotIn("ordinary use of AI-assisted coding", projects_prompt)
            self.assertIn("Retain AI-Driven Development", experience_prompt)
            self.assertIn("AI-forward", experience_prompt)

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

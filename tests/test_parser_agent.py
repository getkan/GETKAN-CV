import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.parser.agent import (
    JobParserState,
    _load_dotenv,
    extract_facts,
    fetch_or_load_listing,
    handoff_to_tailor,
    normalize_packet,
    validate_packet,
)
from src.parser.compatibility_score import calculate_compatibility_score


class JobParserAgentTests(unittest.TestCase):
    def test_calculate_compatibility_score_partial_long_requirement(self):
        score = calculate_compatibility_score(
            {
                "job": {
                    "title": "",
                    "domain": "",
                    "must_have": ["Strong programming skills with languages like Rust, Go, or Python"],
                    "nice_to_have": [],
                }
            }
        )
        self.assertGreaterEqual(score, 3)

    def test_calculate_compatibility_score_returns_valid_range(self):
        score = calculate_compatibility_score(
            {
                "job": {
                    "title": "Senior Backend Engineer",
                    "domain": "Cloud Infrastructure",
                    "must_have": ["Python", "Docker", "Kubernetes"],
                    "nice_to_have": ["Terraform", "Go"],
                }
            }
        )
        self.assertGreaterEqual(score, 1)
        self.assertLessEqual(score, 10)

    def test_parser_pipeline_extracts_and_normalizes_listing(self):
        listing_text = """
        Senior Software Engineer
        ExampleCo
        Austin, TX
        Full-time

        We are looking for a Senior Software Engineer with experience in Python, Django, and AWS.
        Responsibilities include building APIs, mentoring engineers, and improving platform reliability.
        Must have: Python, Django, AWS
        Nice to have: Kubernetes, Terraform
        """

        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/123", "listing_text": listing_text},
            "raw_listing_text": listing_text,
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        fetch_or_load_listing(state)

        with patch(
            "src.parser.agent._parse_job_with_openrouter",
            return_value={
                "title": "Senior Software Engineer",
                "company": "ExampleCo",
                "location": "Austin, TX",
                "employment_type": "Full-time",
                "description": "Build APIs and tooling",
                "must_have": ["Python", "Django", "AWS"],
                "nice_to_have": ["Kubernetes", "Terraform"],
                "responsibilities": ["Build APIs"],
                "domain": "saas",
            },
        ):
            extract_facts(state)
            normalize_packet(state)
            validate_packet(state)

        self.assertIn("title", state["normalized_packet"]["job"])
        self.assertEqual(state["normalized_packet"]["job"]["company"], "ExampleCo")
        self.assertIn("Python", state["normalized_packet"]["job"]["must_have"])
        self.assertIn("AWS", state["normalized_packet"]["job"]["must_have"])
        self.assertGreaterEqual(state["confidence"], 0.5)

    def test_load_dotenv_reads_repo_environment_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")
            os.environ.pop("OPENROUTER_API_KEY", None)
            _load_dotenv(env_path)
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "test-key")
            os.environ.pop("OPENROUTER_API_KEY", None)

    def test_extract_facts_prefers_openrouter_payload_when_available(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/789"},
            "raw_listing_text": "Principal Platform Engineer\nNorthwind\nRemote\n",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch(
            "src.parser.agent._parse_job_with_openrouter",
            return_value={
                "title": "Principal Platform Engineer",
                "company": "Northwind",
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Build platform tooling",
                "must_have": ["Python", "Kubernetes"],
                "nice_to_have": ["Terraform"],
                "responsibilities": ["Lead platform work"],
                "domain": "saas",
            },
        ):
            extract_facts(state)

        self.assertEqual(state["extracted_facts"]["company"], "Northwind")
        self.assertIn("Python", state["extracted_facts"]["must_have"])

    def test_handoff_writes_job_packet_to_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state: JobParserState = {
                "source": {"job_url": "https://example.com/jobs/456"},
                "raw_listing_text": "Staff Product Engineer\nAcme\nRemote\n",
                "extracted_facts": {
                    "title": "Staff Product Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "description": "Build products",
                    "must_have": ["TypeScript"],
                    "nice_to_have": ["React"],
                    "responsibilities": ["Ship features"],
                    "domain": "SaaS",
                },
                "normalized_packet": {},
                "confidence": 0.79,
            }

            result = handoff_to_tailor(state, output_dir=tmpdir)
            output_path = Path(tmpdir) / "job_packet.json"

            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["job"]["title"], "Staff Product Engineer")
            self.assertEqual(result["output_path"], str(output_path))

    def test_extract_facts_falls_back_when_openrouter_returns_unknown_values(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/999"},
            "raw_listing_text": "Title: Senior Software Engineer\nCompany: GitHub\nDescription: Build reliable billing systems\nPython AWS",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch(
            "src.parser.agent._parse_job_with_openrouter",
            return_value={
                "title": "unknown",
                "company": "unknown",
                "location": "unknown",
                "employment_type": "unknown",
                "description": "unknown",
                "must_have": [],
                "nice_to_have": [],
                "responsibilities": [],
                "domain": "unknown",
            },
        ):
            extract_facts(state)

        self.assertEqual(state["extracted_facts"]["title"], "Senior Software Engineer")
        self.assertEqual(state["extracted_facts"]["company"], "GitHub")
        self.assertIn("Python", state["extracted_facts"]["must_have"])
        self.assertIn("AWS", state["extracted_facts"]["must_have"])

    def test_extract_facts_uses_fallback_employment_type(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/1000"},
            "raw_listing_text": "Title: Senior Software Engineer\nEmployment Type: Full Time\nCompany: GitHub\n",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch(
            "src.parser.agent._parse_job_with_openrouter",
            return_value={
                "title": "unknown",
                "company": "unknown",
                "location": "unknown",
                "employment_type": "unknown",
                "description": "unknown",
                "must_have": [],
                "nice_to_have": [],
                "responsibilities": [],
                "domain": "unknown",
            },
        ):
            extract_facts(state)

        self.assertEqual(state["extracted_facts"]["employment_type"], "Full Time")


if __name__ == "__main__":
    unittest.main()

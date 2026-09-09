"""
Tests for src/application/parse_job.py

Validates the parsing phase of the resume tailoring workflow:
- Fetching and loading job listings from URLs or files
- Fact extraction using OpenRouter LLM
- Normalization and validation of job packets
- Compatibility scoring against the base resume
- Handoff to the tailoring phase with structured output
"""
import json
import io
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from src.application.parse_job import parse_job
from src.application.parse_job import (
    JobParserState,
    extract_facts,
    fetch_or_load_listing,
    handoff_to_tailor,
    normalize_packet,
    validate_packet,
)
from src.application.parse_job import calculate_compatibility_score
from src.infrastructure.environment import load_dotenv


class ParseJobTests(unittest.TestCase):
    def test_fetch_or_load_listing_prefers_jsonld_description_over_javascript_shell(self):
        payload = """
        <html><body>You need to enable JavaScript to run this app.</body>
        <script type="application/ld+json">
        {"@type":"JobPosting","description":"<p>Tools: React, TypeScript, and GraphQL</p>"}
        </script></html>
        """
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/structured", "listing_text": ""},
            "raw_listing_text": "",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        response = io.BytesIO(payload.encode("utf-8"))
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: None
        with patch("src.application.parse_job.urlopen", return_value=response):
            fetch_or_load_listing(state)

        self.assertIn("React", state["raw_listing_text"])
        self.assertIn("GraphQL", state["raw_listing_text"])
        self.assertNotIn("enable JavaScript", state["raw_listing_text"])

    def test_extract_facts_merges_only_source_supported_skills(self):
        state: JobParserState = {
            "source": {
                "job_url": "https://example.com/jobs/skills",
                "listing_html": "<p>Tools: JavaScript, Python, Django, React, React-Query, TypeScript, React Native, Git, REST, GraphQL, Claude, Cursor.</p>",
            },
            "raw_listing_text": "Tools: JavaScript, Python, Django, React, React-Query, TypeScript, React Native, Git, REST, GraphQL, Claude, Cursor.",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch(
            "src.application.parse_job._parse_job_with_openrouter",
            return_value={
                "title": "Frontend Engineer",
                "company": "ExampleCo",
                "description": "Build frontend systems",
                "must_have": ["JavaScript", "Go", "AI"],
                "nice_to_have": ["Go", "AI"],
            },
        ):
            extract_facts(state)

        must_have = state["extracted_facts"]["must_have"]
        self.assertIn("Python", must_have)
        self.assertIn("Django", must_have)
        self.assertIn("React", must_have)
        self.assertIn("React Query", must_have)
        self.assertIn("React Native", must_have)
        self.assertIn("GraphQL", must_have)
        self.assertIn("Claude", must_have)
        self.assertIn("Cursor", must_have)
        self.assertNotIn("Go", must_have)
        self.assertNotIn("AI", must_have)
        self.assertNotIn("Go", state["extracted_facts"]["nice_to_have"])
        self.assertNotIn("AI", state["extracted_facts"]["nice_to_have"])

    def test_heuristic_skill_matching_does_not_match_incidental_substrings(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/no-false-positive"},
            "raw_listing_text": "This role goes beyond implementation and supports daily operations.",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch("src.application.parse_job._parse_job_with_openrouter", return_value={}):
            extract_facts(state)

        self.assertNotIn("Go", state["extracted_facts"]["must_have"])
        self.assertNotIn("AI", state["extracted_facts"]["must_have"])
        self.assertNotIn("Go", state["extracted_facts"]["nice_to_have"])
        self.assertNotIn("AI", state["extracted_facts"]["nice_to_have"])

    def test_skill_normalization_requires_explicit_product_names(self):
        from src.application.parse_job import _source_skill_mentions

        source_text = "Solid understanding of APIs. React-Query is used in the frontend."

        mentions = _source_skill_mentions(source_text)

        self.assertIn("React Query", mentions)
        self.assertNotIn("SolidJS", mentions)
        self.assertNotIn("TanStack", mentions)

    def test_source_validation_rejects_ambiguous_and_unlisted_skills(self):
        from src.application.parse_job import _source_supported_skills

        source_text = "Solid understanding of APIs. React-Query is used in the frontend."

        supported = _source_supported_skills(["Solid", "SolidJS", "TanStack", "React Query", "Less"], source_text)

        self.assertEqual(supported, ["React Query"])

    def test_fetch_or_load_listing_handles_url_errors(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/failed", "listing_text": ""},
            "raw_listing_text": "unexpected",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch("src.application.parse_job.urlopen", side_effect=URLError("unavailable")):
            fetch_or_load_listing(state)

        self.assertEqual(state["raw_listing_text"], "")

    def test_parser_prompt_loader_reads_editable_prompt_file(self):
        from src.application.parse_job import _load_parser_prompts

        prompts = _load_parser_prompts()

        self.assertIn("Rules for must_have", prompts["job_parser_system_prompt"])

    def test_parse_job_runs_the_complete_parsing_workflow(self):
        def extract_facts_side_effect(state):
            state["extracted_facts"] = {
                "title": "Senior Software Engineer",
                "company": "ExampleCo",
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Build reliable services.",
                "must_have": ["Python"],
                "nice_to_have": [],
                "responsibilities": ["Ship software"],
                "domain": "SaaS",
            }
            return state

        with patch("src.application.parse_job.extract_facts", side_effect=extract_facts_side_effect):
            packet = parse_job(job_url="https://example.com/jobs/1", listing_text="Listing")

        self.assertEqual(packet["job"]["company"], "ExampleCo")
        self.assertEqual(packet["metadata"]["validation_errors"], [])
        self.assertEqual(packet["metadata"]["raw_listing_text"], "Listing")
        self.assertIn("compatibility_score", packet)

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
            "src.application.parse_job._parse_job_with_openrouter",
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
            load_dotenv(env_path)
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "test-key")
            os.environ.pop("OPENROUTER_API_KEY", None)

    def test_extract_facts_prefers_openrouter_payload_when_available(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/789"},
            "raw_listing_text": "Principal Platform Engineer\nNorthwind\nRemote\nPython Kubernetes",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch(
            "src.application.parse_job._parse_job_with_openrouter",
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
            output_path = Path(tmpdir) / "job" / "job_packet.json"
            raw_listing_path = Path(tmpdir) / "job" / "raw_listing_text.txt"

            self.assertTrue(output_path.exists())
            self.assertEqual(raw_listing_path.read_text(encoding="utf-8"), state["raw_listing_text"])
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
            "src.application.parse_job._parse_job_with_openrouter",
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
            "src.application.parse_job._parse_job_with_openrouter",
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

    def test_extract_facts_handles_unhashable_payload_values(self):
        state: JobParserState = {
            "source": {"job_url": "https://example.com/jobs/1001"},
            "raw_listing_text": "Title: Platform Engineer\nCompany: ExampleCo\n",
            "extracted_facts": {},
            "normalized_packet": {},
            "confidence": 0.0,
        }

        with patch(
            "src.application.parse_job._parse_job_with_openrouter",
            return_value={
                "title": ["Platform Engineer"],
                "company": "ExampleCo",
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Build platforms",
                "must_have": ["Python"],
                "nice_to_have": [],
                "responsibilities": [],
                "domain": "SaaS",
            },
        ):
            extract_facts(state)

        self.assertEqual(state["extracted_facts"]["company"], "ExampleCo")


if __name__ == "__main__":
    unittest.main()

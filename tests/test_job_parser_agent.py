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
from src.advisor.sections.ats_keyword_gaps import render_ats_keyword_gaps_section
from src.advisor.sections.general_advice import render_general_advice_section
from src.advisor.sections.interview_prep import render_interview_prep_section
from src.advisor.sections.portfolio_suggestions import render_portfolio_suggestions_section
from src.advisor.sections.job_titles import render_recommended_job_titles_section
from src.advisor.sections.resume_recommendation import render_resume_recommendation_section
from src.advisor.sections.skills import render_recommend_skills_section
from src.advisor.agent import _generate_recommendation_sections, generate_job_hunt_recommendations
from src.tailor.agent import _score_item, build_allowlist, build_tailored_payload
from src.main import calculate_compatibility_score, rebuild_all_job_packets, rebuild_from_job_packet, run
from src.main import clean_workspace_artifacts


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

    def test_rebuild_all_job_packets_rebuilds_every_packet_in_output_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            first_dir = output_root / "alpha"
            second_dir = output_root / "beta"
            first_dir.mkdir(parents=True, exist_ok=True)
            second_dir.mkdir(parents=True, exist_ok=True)
            (first_dir / "job_packet.json").write_text(
                json.dumps({"job": {"title": "Alpha Role", "company": "Acme", "must_have": ["Python"], "nice_to_have": ["Docker"]}}),
                encoding="utf-8",
            )
            (second_dir / "job_packet.json").write_text(
                json.dumps({"job": {"title": "Beta Role", "company": "Globex", "must_have": ["Kubernetes"], "nice_to_have": ["Go"]}}),
                encoding="utf-8",
            )

            with patch("src.main.build_tailored_payload", return_value={"compile": {"pdf_path": ""}}):
                result = rebuild_all_job_packets(str(output_root), None)

            self.assertEqual(result["packet_count"], 2)
            self.assertEqual([entry["job_name"] for entry in result["rebuilds"]], ["alpha", "beta"])
            self.assertTrue((first_dir / "tailored_resume.json").exists())
            self.assertTrue((second_dir / "tailored_resume.json").exists())

    def test_job_hunt_advisor_without_packets_writes_general_advice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            modules_dir = Path(tmpdir) / "modules"
            modules_dir.mkdir(parents=True, exist_ok=True)
            (modules_dir / "summary.tex").write_text("Senior engineer profile.", encoding="utf-8")
            (modules_dir / "experience.tex").write_text("Built APIs and services.", encoding="utf-8")
            (modules_dir / "personalprojects.tex").write_text("Projects.", encoding="utf-8")
            (modules_dir / "aboutme.tex").write_text("About me.", encoding="utf-8")

            with patch(
                "src.advisor.agent._generate_recommendation_sections",
                return_value=[
                    "## General Advice and Summary",
                    "",
                    "Summary: Keep the resume focused on backend work. Advice: Lead with impact and mirror packet keywords.",
                    "",
                    "## Skills",
                    "",
                    "| Skill | Must Haves | Good To Haves | Total |",
                    "| --- | ---: | ---: | ---: |",
                    "| Kubernetes | 0 | 1 | 1 |",
                    "| Python | 0 | 1 | 1 |",
                    "",
                    "## Recommended Job Titles",
                    "",
                    "- Senior Backend Engineer (score 9): Backend role aligned to APIs. Strong match on Python and Kubernetes",
                    "",
                    "## Resume Recommendation",
                    "",
                    "- Skills: Add stronger Kubernetes examples. The job packets emphasize orchestration (P1)",
                    "",
                    "## Interview Prep",
                    "",
                    "- Practice API design, Kubernetes, and backend ownership stories.",
                    "",
                    "## ATS Keyword Gaps",
                    "",
                    "- Terraform: mention infrastructure ownership more clearly.",
                    "",
                    "## Portfolio or Project Suggestions",
                    "",
                    "- Build a small Kubernetes deployment project with CI/CD.",
                ],
            ):
                result = generate_job_hunt_recommendations(output_root=output_root, resume_modules_dir=modules_dir)

            self.assertEqual(result["packet_count"], 0)
            self.assertEqual(result["skills"], ["Kubernetes", "Python"])
            recommendations_text = Path(result["recommendations_path"]).read_text(encoding="utf-8")
            self.assertLess(
                recommendations_text.index("## General Advice and Summary"),
                recommendations_text.index("## Skills"),
            )
            self.assertIn("## General Advice and Summary", recommendations_text)
            self.assertIn("## Skills", recommendations_text)
            self.assertIn("## Recommended Job Titles", recommendations_text)
            self.assertIn("## Resume Recommendation", recommendations_text)
            self.assertIn("## Interview Prep", recommendations_text)
            self.assertIn("## ATS Keyword Gaps", recommendations_text)
            self.assertIn("## Portfolio or Project Suggestions", recommendations_text)
            self.assertIn("| Skill | Must Haves | Good To Haves | Total |", recommendations_text)
            self.assertIn("Kubernetes", recommendations_text)

    def test_job_hunt_advisor_writes_recommendations_from_saved_packets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            packet_dir = output_root / "sample-role"
            packet_dir.mkdir(parents=True, exist_ok=True)
            (packet_dir / "job_packet.json").write_text(
                json.dumps(
                    {
                        "job": {
                            "title": "Staff Backend Engineer",
                            "domain": "developer tools",
                            "description": "Design backend APIs and cloud services",
                            "must_have": ["Python", "Kubernetes"],
                            "nice_to_have": ["Terraform", "GraphQL"],
                            "responsibilities": ["Own reliability and CI/CD pipelines"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            modules_dir = Path(tmpdir) / "modules"
            modules_dir.mkdir(parents=True, exist_ok=True)
            (modules_dir / "summary.tex").write_text("Experienced engineer with Python and API delivery.", encoding="utf-8")
            (modules_dir / "experience.tex").write_text("Built backend services and mentored engineers.", encoding="utf-8")
            (modules_dir / "personalprojects.tex").write_text("Project work in automation.", encoding="utf-8")
            (modules_dir / "aboutme.tex").write_text("Hands-on builder.", encoding="utf-8")
            (modules_dir / "skills.json").write_text(
                json.dumps(
                    {
                        "programming_languages": ["Python", "TypeScript"],
                        "devops_and_delivery": ["GitHub Actions", "Docker"],
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "src.advisor.agent._generate_recommendation_sections",
                return_value=[
                    "## General Advice and Summary",
                    "",
                    "- Summary: Focus on roles that combine backend delivery and platform work.",
                    "- Advice: Use packet language in the summary and top bullets.",
                    "",
                    "## Skills",
                    "",
                    "| Skill | Must Haves | Good To Haves | Total |",
                    "| --- | ---: | ---: | ---: |",
                    "| Kubernetes | 1 | 0 | 1 |",
                    "| Terraform | 0 | 1 | 1 |",
                    "",
                    "## Recommended Job Titles",
                    "",
                    "- Staff Backend Engineer (score 10): Backend platform role. Highest packet match",
                    "",
                    "## Resume Recommendation",
                    "",
                    "- Summary: Tighten summary around backend impact. The packets emphasize backend ownership (P1)",
                    "",
                    "## Interview Prep",
                    "",
                    "- Review backend architecture, reliability, and CI/CD examples.",
                    "",
                    "## ATS Keyword Gaps",
                    "",
                    "- GraphQL: add clearer evidence if you have it.",
                    "",
                    "## Portfolio or Project Suggestions",
                    "",
                    "- Add a reliability-focused project that shows production tradeoffs.",
                ],
            ):
                result = generate_job_hunt_recommendations(output_root=output_root, resume_modules_dir=modules_dir)

            self.assertEqual(result["packet_count"], 1)
            self.assertTrue(Path(result["recommendations_path"]).exists())
            self.assertEqual(result["skills"], ["Kubernetes", "Terraform"])
            recommendations_text = Path(result["recommendations_path"]).read_text(encoding="utf-8")
            self.assertLess(
                recommendations_text.index("## General Advice and Summary"),
                recommendations_text.index("## Skills"),
            )
            self.assertIn("## General Advice and Summary", recommendations_text)
            self.assertIn("## Skills", recommendations_text)
            self.assertIn("## Recommended Job Titles", recommendations_text)
            self.assertIn("## Interview Prep", recommendations_text)
            self.assertIn("## ATS Keyword Gaps", recommendations_text)
            self.assertIn("## Portfolio or Project Suggestions", recommendations_text)
            self.assertIn("| Kubernetes | 1 | 0 | 1 |", recommendations_text)
            self.assertIn("Kubernetes", recommendations_text)

    def test_advisor_section_renderers_return_expected_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            modules_dir = Path(tmpdir) / "modules"
            modules_dir.mkdir(parents=True, exist_ok=True)
            (modules_dir / "summary.tex").write_text("Backend engineer with Python and APIs.", encoding="utf-8")
            (modules_dir / "experience.tex").write_text("Delivered services.", encoding="utf-8")
            (modules_dir / "personalprojects.tex").write_text("Automation and tooling.", encoding="utf-8")
            (modules_dir / "aboutme.tex").write_text("Hands-on builder.", encoding="utf-8")

            titles = render_recommended_job_titles_section(
                rows=[
                    {
                        "job_title": "Backend Engineer",
                        "description": "Works on APIs",
                        "rationale": "Matches API delivery",
                        "compatibility_score": 5,
                    }
                ]
            )
            skills = render_recommend_skills_section(
                skill_rows=[
                    {"skill": "Kubernetes", "must_haves": 1, "good_to_haves": 0, "total": 1},
                    {"skill": "Python", "must_haves": 1, "good_to_haves": 0, "total": 1},
                ],
                skills=["Kubernetes", "Python"],
            )
            resume_recs = render_resume_recommendation_section(
                rows=[
                    {"area": "Summary", "recommendation": "Lead with backend impact", "reason": "Matches packet emphasis", "priority": 1}
                ]
            )
            interview_prep = render_interview_prep_section(items=["Practice backend ownership stories."])
            ats_gaps = render_ats_keyword_gaps_section(items=["Kubernetes: mention deployment ownership."])
            portfolio = render_portfolio_suggestions_section(items=["Build a small deployment pipeline demo."])
            general = render_general_advice_section(
                summary="Focus on backend engineering and platform delivery.",
                general_advice="Keep the summary targeted to the strongest role fit. Mirror key packet keywords in the top third of the resume.",
            )

            self.assertIn("## Recommended Job Titles", titles["lines"][0])
            self.assertIn("- Backend Engineer (score 5): Works on APIs. Matches API delivery", "\n".join(titles["lines"]))
            self.assertEqual(skills["skills"], ["Kubernetes", "Python"])
            self.assertIn("| Python | 1 | 0 |", "\n".join(skills["lines"]))
            self.assertIn("## Resume Recommendation", resume_recs["lines"][0])
            self.assertIn("- Summary: Lead with backend impact. Matches packet emphasis (P1)", "\n".join(resume_recs["lines"]))
            self.assertIn("## Interview Prep", interview_prep["lines"][0])
            self.assertIn("Practice backend ownership stories", "\n".join(interview_prep["lines"]))
            self.assertIn("## ATS Keyword Gaps", ats_gaps["lines"][0])
            self.assertIn("Kubernetes", "\n".join(ats_gaps["lines"]))
            self.assertIn("## Portfolio or Project Suggestions", portfolio["lines"][0])
            self.assertIn("deployment pipeline demo", "\n".join(portfolio["lines"]))
            self.assertIn("## General Advice and Summary", general["lines"][0])

    def test_advisor_combines_openrouter_calls_into_single_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            modules_dir = Path(tmpdir) / "modules"
            modules_dir.mkdir(parents=True, exist_ok=True)
            (modules_dir / "summary.tex").write_text("Backend engineer with Python and APIs.", encoding="utf-8")
            (modules_dir / "experience.tex").write_text("Delivered services.", encoding="utf-8")
            (modules_dir / "personalprojects.tex").write_text("Automation and tooling.", encoding="utf-8")
            (modules_dir / "aboutme.tex").write_text("Hands-on builder.", encoding="utf-8")

            packets = [
                {
                    "job": {
                        "title": "Senior Backend Engineer",
                        "company": "Acme",
                        "domain": "developer tools",
                        "description": "Build APIs",
                        "must_have": ["Python", "Kubernetes"],
                        "nice_to_have": ["Terraform"],
                        "responsibilities": ["Own reliability"],
                    }
                }
            ]

            with patch(
                "src.advisor.agent._post_openrouter_json",
                return_value={
                    "summary": "Focus on backend engineering and platform delivery.",
                    "general_advice": "Keep the summary targeted to the strongest role fit. Mirror key packet keywords in the top third of the resume.",
                    "skills": ["Python", "Kubernetes", "Python"],
                    "recommended_job_titles": [
                        {"job_title": "Backend Engineer", "description": "Works on APIs", "rationale": "Matches API delivery"}
                    ],
                    "resume_recommendations": [
                        {"area": "Summary", "recommendation": "Lead with backend impact", "reason": "Matches packet emphasis", "priority": 1}
                    ],
                    "interview_prep": ["Practice backend ownership stories."],
                    "ats_keyword_gaps": ["Kubernetes: mention deployment ownership."],
                    "portfolio_suggestions": ["Build a small deployment pipeline demo."],
                },
            ) as openrouter_mock:
                lines = _generate_recommendation_sections(resume_modules_dir=modules_dir, packets=packets, model_name="mock")

            self.assertEqual(openrouter_mock.call_count, 1)
            self.assertLess(lines.index("## General Advice and Summary"), lines.index("## Skills"))
            self.assertLess(lines.index("## Skills"), lines.index("## Recommended Job Titles"))
            self.assertIn(
                "Summary: Focus on backend engineering and platform delivery.",
                "\n".join(lines),
            )
            self.assertIn("| Python | 1 | 0 |", "\n".join(lines))

    def test_category_boosts_raise_testing_bullet_score(self):
        item = "Established testing framework with Jest and Vue Test Utils for unit and integration test coverage"
        baseline = _score_item(item, [])
        boosted = _score_item(
            item,
            [],
            category_skills={"testing_and_quality": ["jest", "vue test utils", "unit testing", "integration testing"]},
            category_boosts={"testing_and_quality": 3},
        )
        self.assertGreater(boosted, baseline)

    def test_build_allowlist_uses_skills_file(self):
        state = {
            "job_packet": {},
            "source_modules": {},
            "allowlist": [],
            "prompts": {},
            "model_output": {},
            "violations": [],
            "compile_log": "",
        }
        build_allowlist(state)

        allowlist = [item.lower() for item in state["allowlist"]]
        self.assertIn("javascript", allowlist)
        self.assertIn("laravel", allowlist)
        self.assertIn("github actions", allowlist)
        self.assertIn("jest", allowlist)

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

    def test_run_uses_current_working_directory_for_default_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = Path(tmpdir) / "listing.txt"
            listing_path.write_text("Example listing", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch("src.main.fetch_or_load_listing"), patch("src.main.extract_facts"), patch("src.main.normalize_packet"), patch("src.main.validate_packet"), patch(
                    "src.main.handoff_to_tailor", return_value={"output_path": str(Path(tmpdir) / "job_packet.json")}
                ), patch("src.main.build_tailored_payload", return_value={"ok": True}):
                    exit_code = run("demo-job", str(listing_path), None, None, None)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            output_dir = Path(tmpdir) / "output" / "demo-job"
            self.assertTrue(output_dir.exists())
            self.assertTrue((output_dir / "tailored_resume.json").exists())

    def test_run_writes_source_history_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = Path(tmpdir) / "listing.txt"
            listing_path.write_text("Example listing", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch("src.main.fetch_or_load_listing"), patch("src.main.extract_facts"), patch("src.main.normalize_packet"), patch("src.main.validate_packet"), patch(
                    "src.main.handoff_to_tailor", return_value={"output_path": str(Path(tmpdir) / "job_packet.json")}
                ), patch("src.main.build_tailored_payload", return_value={"ok": True, "compile": {"pdf_path": ""}}):
                    exit_code = run("demo-job", str(listing_path), "https://example.com/jobs/1", None, "gpt-4o-mini")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            log_path = Path(tmpdir) / "log" / "source_history.jsonl"
            self.assertTrue(log_path.exists())

    def test_clean_workspace_artifacts_removes_output_and_log_contents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            log_dir = Path(tmpdir) / "log"
            (output_dir / "sample" / "nested").mkdir(parents=True, exist_ok=True)
            (output_dir / "sample" / "nested" / "file.txt").write_text("data", encoding="utf-8")
            (log_dir / "source_history.jsonl").parent.mkdir(parents=True, exist_ok=True)
            (log_dir / "source_history.jsonl").write_text("entry", encoding="utf-8")

            result = clean_workspace_artifacts(output_root=str(output_dir), log_root=str(log_dir))

            self.assertEqual(result["output_dir"], str(output_dir))
            self.assertEqual(result["log_dir"], str(log_dir))
            self.assertTrue(output_dir.exists())
            self.assertTrue(log_dir.exists())
            self.assertEqual(list(output_dir.iterdir()), [])
            self.assertEqual(list(log_dir.iterdir()), [])

    def test_run_recompile_mode_skips_parsing_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output" / "demo-job"
            output_dir.mkdir(parents=True, exist_ok=True)

            with patch("src.main.fetch_or_load_listing") as fetch_mock, patch("src.main.extract_facts") as extract_mock, patch(
                "src.main.normalize_packet"
            ) as normalize_mock, patch("src.main.validate_packet") as validate_mock, patch("src.main.handoff_to_tailor") as handoff_mock, patch(
                "src.main.recompile_existing_output",
                return_value={"summary": str(output_dir / "tailored_resume.json"), "compile": {"pdf_path": str(output_dir / "demo-job.pdf"), "page_count": 1}},
            ) as recompile_mock:
                exit_code = run("demo-job", None, None, str(output_dir), None, recompile_existing=True)

            self.assertEqual(exit_code, 0)
            recompile_mock.assert_called_once()
            fetch_mock.assert_not_called()
            extract_mock.assert_not_called()
            normalize_mock.assert_not_called()
            validate_mock.assert_not_called()
            handoff_mock.assert_not_called()

    def test_run_build_basic_mode_skips_parsing_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.fetch_or_load_listing") as fetch_mock, patch("src.main.extract_facts") as extract_mock, patch(
                "src.main.normalize_packet"
            ) as normalize_mock, patch("src.main.validate_packet") as validate_mock, patch("src.main.handoff_to_tailor") as handoff_mock, patch(
                "src.main.build_basic_resume",
                return_value={"output_dir": str(Path(tmpdir) / "output" / "general"), "pdf": str(Path(tmpdir) / "output" / "general" / "resume.pdf"), "compile_log": ""},
            ) as basic_mock:
                exit_code = run(None, None, None, str(Path(tmpdir) / "output" / "general"), None, build_basic=True)

            self.assertEqual(exit_code, 0)
            basic_mock.assert_called_once()
            fetch_mock.assert_not_called()
            extract_mock.assert_not_called()
            normalize_mock.assert_not_called()
            validate_mock.assert_not_called()
            handoff_mock.assert_not_called()

    def test_run_job_hunt_advice_mode_skips_parsing_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.fetch_or_load_listing") as fetch_mock, patch("src.main.extract_facts") as extract_mock, patch(
                "src.main.normalize_packet"
            ) as normalize_mock, patch("src.main.validate_packet") as validate_mock, patch("src.main.handoff_to_tailor") as handoff_mock, patch(
                "src.main.generate_job_hunt_recommendations",
                return_value={
                    "recommendations_path": str(Path(tmpdir) / "output" / "job_hunt_recommendations.md"),
                    "packet_count": 2,
                    "missing_skills": [],
                    "matched_skills": [],
                },
            ) as advice_mock:
                exit_code = run(None, None, None, str(Path(tmpdir) / "output"), None, job_hunt_advice=True)

            self.assertEqual(exit_code, 0)
            advice_mock.assert_called_once()
            fetch_mock.assert_not_called()
            extract_mock.assert_not_called()
            normalize_mock.assert_not_called()
            validate_mock.assert_not_called()
            handoff_mock.assert_not_called()

    def test_run_job_hunt_advice_mode_passes_explicit_packet_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = str(Path(tmpdir) / "job_packet.json")
            with patch("src.main.generate_job_hunt_recommendations", return_value={"recommendations_path": "x", "packet_count": 0}) as advice_mock:
                exit_code = run(None, None, None, str(Path(tmpdir) / "output"), None, job_hunt_advice=True, job_packet_files=[packet_path])

            self.assertEqual(exit_code, 0)
            advice_mock.assert_called_once()
            _, kwargs = advice_mock.call_args
            self.assertEqual(kwargs.get("job_packet_files"), [packet_path])

    def test_run_batch_urls_from_file_auto_generates_job_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                list_file = Path(tmpdir) / "urls.txt"
                list_file.write_text("https://example.com/job-a\nhttps://example.com/job-b\n", encoding="utf-8")

                def normalize_side_effect(state):
                    url = state.get("source", {}).get("job_url", "")
                    if "job-a" in url:
                        state["normalized_packet"] = {
                            "job": {
                                "company": "Acme",
                                "title": "Senior Backend Engineer",
                                "must_have": ["Python"],
                                "nice_to_have": ["Docker"],
                                "domain": "SaaS",
                            }
                        }
                    else:
                        state["normalized_packet"] = {
                            "job": {
                                "company": "Acme",
                                "title": "Senior Backend Engineer",
                                "must_have": ["Python"],
                                "nice_to_have": ["Kubernetes"],
                                "domain": "SaaS",
                            }
                        }

                def handoff_side_effect(state, output_dir):
                    return {"output_path": str(Path(output_dir) / "job_packet.json")}

                def payload_side_effect(job_packet, job_name, output_dir, model_name=None):
                    return {"compile": {"pdf_path": str(Path(output_dir) / f"{job_name}.pdf")}}

                with patch("src.main.fetch_or_load_listing"), patch("src.main.extract_facts"), patch("src.main.normalize_packet", side_effect=normalize_side_effect), patch(
                    "src.main.validate_packet"
                ), patch("src.main.handoff_to_tailor", side_effect=handoff_side_effect) as handoff_mock, patch(
                    "src.main.build_tailored_payload", side_effect=payload_side_effect
                ) as payload_mock:
                    exit_code = run(
                        None,
                        None,
                        None,
                        None,
                        None,
                        url_list_file=str(list_file),
                    )

                self.assertEqual(exit_code, 0)
                self.assertEqual(handoff_mock.call_count, 2)
                self.assertEqual(payload_mock.call_count, 2)

                log_path = Path(tmpdir) / "log" / "source_history.jsonl"
                self.assertTrue(log_path.exists())
                entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertGreaterEqual(len(entries), 2)
                last_two = entries[-2:]
                names = [entry["job_name"] for entry in last_two]
                self.assertEqual(names[0], "acme-senior-backend-engineer")
                self.assertEqual(names[1], "acme-senior-backend-engineer-2")
            finally:
                os.chdir(previous_cwd)

    def test_rebuild_from_job_packet_generates_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = Path(tmpdir) / "job_packet.json"
            packet_path.write_text(
                json.dumps(
                    {
                        "job": {
                            "title": "Senior Frontend Engineer",
                            "company": "Acme",
                            "must_have": ["React", "TypeScript"],
                            "nice_to_have": ["Playwright"],
                            "domain": "SaaS",
                        }
                    }
                ),
                encoding="utf-8",
            )

            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch(
                    "src.main.build_tailored_payload",
                    return_value={"compile": {"pdf_path": str(Path(tmpdir) / "output" / "demo-job" / "demo-job.pdf")}},
                ):
                    result = rebuild_from_job_packet(str(packet_path), "demo-job", None, "gpt-4o-mini")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(result.get("mode"), "rebuild")
            self.assertEqual(result.get("job_name"), "demo-job")
            self.assertTrue(Path(result["output_dir"]).exists())
            self.assertTrue(Path(result["job_packet"]).exists())
            self.assertTrue(Path(result["summary"]).exists())
            self.assertEqual(result.get("model_name"), "gpt-4o-mini")

    def test_build_tailored_payload_writes_summary_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = build_tailored_payload(
                {
                    "job": {
                        "title": "Senior Software Engineer",
                        "company": "GitHub",
                        "location": "Remote",
                        "employment_type": "Full-time",
                        "description": "Build billing and platform systems",
                        "must_have": ["Python", "AWS", "Kubernetes"],
                        "nice_to_have": ["TypeScript"],
                        "responsibilities": ["Lead backend architecture"],
                        "domain": "developer tools",
                    },
                    "metadata": {},
                },
                job_name="demo-job",
                output_dir=tmpdir,
            )

            self.assertIn("summary.tex", payload["model_output"]["tailored_modules"])
            self.assertIn("Senior Software Engineer", payload["model_output"]["tailored_modules"]["summary.tex"])
            self.assertNotIn("relevance_notes.txt", payload["model_output"]["tailored_modules"])
            self.assertNotIn("experience_highlights.tex", payload["model_output"]["tailored_modules"])
            self.assertIn("experience.tex", payload["model_output"]["tailored_modules"])
            self.assertIn("personalprojects.tex", payload["model_output"]["tailored_modules"])
            self.assertIn("aboutme.tex", payload["model_output"]["tailored_modules"])
            self.assertIn("Bachelor of Arts in Computer Science", payload["model_output"]["tailored_modules"]["aboutme.tex"])
            self.assertIn("Bachelor of Arts in Economics", payload["model_output"]["tailored_modules"]["aboutme.tex"])
            self.assertTrue(Path(tmpdir, "resume", "modules", "summary.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "modules", "experience.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "modules", "personalprojects.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "modules", "aboutme.tex").exists())
            self.assertTrue(Path(tmpdir, "demo-job.pdf").exists())
            self.assertTrue(Path(tmpdir, "tailored_resume.json").exists())

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

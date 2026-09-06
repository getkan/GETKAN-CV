"""
Tests for src/application/advise.py

Validates the job hunt advisory phase:
- Aggregation and analysis of saved job packets
- Skill gap identification and prioritization
- Job title recommendations with compatibility scoring
- Resume and interview preparation suggestions
- ATS keyword gap detection
- Portfolio/project suggestions based on market demand
- Section-level rendering (markdown output)
- Integration with the CLI advice workflow
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.application.advise import (
    _generate_recommendation_sections,
    generate_job_hunt_recommendations,
    render_ats_keyword_gaps_section,
    render_general_advice_section,
    render_interview_prep_section,
    render_portfolio_suggestions_section,
    render_recommend_skills_section,
    render_recommended_job_titles_section,
    render_resume_recommendation_section,
)
from src.cli import run


class AdviseTests(unittest.TestCase):
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
                "src.application.advise._generate_recommendation_sections",
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
                "src.application.advise._generate_recommendation_sections",
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
                    {"skill": "Kubernetes", "must_haves": 3, "good_to_haves": 0, "total": 3},
                    {"skill": "Python", "must_haves": 4, "good_to_haves": 0, "total": 4},
                ]
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
            self.assertIn("| Python | 4 | 0 |", "\n".join(skills["lines"]))
            self.assertIn("## Resume Recommendation", resume_recs["lines"][0])
            self.assertIn("- Summary: Lead with backend impact. Matches packet emphasis (P1)", "\n".join(resume_recs["lines"]))
            self.assertIn("## Interview Prep", interview_prep["lines"][0])
            self.assertIn("Practice backend ownership stories", "\n".join(interview_prep["lines"]))
            self.assertIn("## ATS Keyword Gaps", ats_gaps["lines"][0])
            self.assertIn("Kubernetes", "\n".join(ats_gaps["lines"]))
            self.assertIn("## Portfolio or Project Suggestions", portfolio["lines"][0])
            self.assertIn("deployment pipeline demo", "\n".join(portfolio["lines"]))
            self.assertIn("## General Advice and Summary", general["lines"][0])

    def test_advisor_skills_only_renders_three_or_more_must_haves(self):
        skills = render_recommend_skills_section(
            skill_rows=[
                {"skill": "Python", "must_haves": 3, "good_to_haves": 1, "total": 4},
                {"skill": "Terraform", "must_haves": 2, "good_to_haves": 4, "total": 6},
                {"skill": "GraphQL", "must_haves": 0, "good_to_haves": 3, "total": 3},
            ]
        )

        rendered = "\n".join(skills["lines"])
        self.assertEqual(skills["skills"], ["Python"])
        self.assertIn("| Python | 3 | 1 | 4 |", rendered)
        self.assertNotIn("Terraform", rendered)
        self.assertNotIn("GraphQL", rendered)

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
                "src.application.advise._post_openrouter_json",
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
            self.assertIn("| None identified | 0 | 0 | 0 |", "\n".join(lines))

    def test_run_job_hunt_advice_mode_skips_parsing_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.cli.parse_job") as parse_job_mock, patch(
                "src.cli.generate_job_hunt_recommendations",
                return_value={
                    "recommendations_path": str(Path(tmpdir) / "output" / "job_hunt_recommendations.md"),
                    "packet_count": 2,
                    "missing_skills": [],
                    "matched_skills": [],
                },
            ) as advice_mock:
                exit_code = run(None, None, str(Path(tmpdir) / "output"), None, job_hunt_advice=True)

            self.assertEqual(exit_code, 0)
            advice_mock.assert_called_once()
            parse_job_mock.assert_not_called()

    def test_run_job_hunt_advice_mode_passes_explicit_packet_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = str(Path(tmpdir) / "job_packet.json")
            with patch("src.cli.generate_job_hunt_recommendations", return_value={"recommendations_path": "x", "packet_count": 0}) as advice_mock:
                exit_code = run(None, None, str(Path(tmpdir) / "output"), None, job_hunt_advice=True, job_packet_files=[packet_path])

            self.assertEqual(exit_code, 0)
            advice_mock.assert_called_once()
            _, kwargs = advice_mock.call_args
            self.assertEqual(kwargs.get("job_packet_files"), [packet_path])


if __name__ == "__main__":
    unittest.main()

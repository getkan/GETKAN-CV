"""
Tests for src/application/tailor_resume.py and src/application/deterministic_tailor.py

Validates the tailoring phase of the resume tailoring workflow:
- Module rewriting using deterministic rules and/or LLM via OpenRouter
- One-page layout fitting with progressive constraint profiles
- Allowlist filtering and skill-based prioritization
- LaTeX compilation to PDF with xelatex
- Artifact generation and output organization
- Integration with the CLI and rebuild workflows
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.application.deterministic_tailor import _score_item, build_allowlist
from src.application.tailor_resume import build_tailored_payload, tailor_modules
from src.cli import clean_workspace_artifacts, rebuild_all_job_packets, rebuild_from_job_packet, run


TAILORED_CV_TEX = r"""\documentclass[11pt, letterpaper]{../getkan-cv}
\geometry{left=1.4cm, top=.8cm, right=1.4cm, bottom=1.8cm, footskip=.5cm}
\fontdir[fonts/]
\colorlet{awesome}{awesome-red}
\setbool{acvSectionColorHighlight}{true}
\name{Nicholas}{Getka}
\position{Senior Software Engineer}
\email{nicholas.getka@gmail.com}
\recipient{GitHub}{Hiring Team}
\letterdate{\today}
\lettertitle{Curriculum Vitae}
\letteropening{Dear Hiring Team,}
\letterclosing{Sincerely,}
\begin{document}
\makecvheader[C]
\makecvfooter{\today}{Nicholas Getka~~~·~~~Letter of Introduction}{\thepage}
\makelettertitle
\begin{cvletter}
I am excited about this Senior Engineer role because it connects with my full-stack engineering experience.
\end{cvletter}
\makeletterclosing
\end{document}
"""


class TailorResumeTests(unittest.TestCase):
    def test_tailor_modules_propagates_openrouter_errors(self):
        state = {
            "job_packet": {},
            "source_modules": {},
            "prompts": {
                "resume_customizer_system_prompt": "System prompt",
                "resume_customizer_user_prompt_template": "Job: {job_packet}",
            },
        }

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.application.tailor_resume.post_json_schema",
            side_effect=RuntimeError("OpenRouter unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenRouter unavailable"):
                tailor_modules(state)

    def test_tailor_modules_requires_openrouter_configuration(self):
        state = {
            "job_packet": {},
            "source_modules": {},
            "prompts": {},
        }

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                tailor_modules(state)

    def test_tailor_modules_uses_openrouter_output_when_configured(self):
        module_names = ("summary.tex", "experience.tex", "personalprojects.tex", "aboutme.tex")
        state = {
            "job_packet": {"job": {"title": "Senior Engineer"}},
            "source_modules": {name: f"source {name}" for name in module_names},
            "prompts": {
                "resume_customizer_system_prompt": "System prompt",
                "resume_customizer_user_prompt_template": "Job: {job_packet}",
                "cv_letter_prompt": "Tailor the CV letter",
            },
            "layout_profile": {},
            "source_cv_tex": "Source CV",
        }
        response = json.dumps({"tailored_modules": {name: f"AI {name}" for name in module_names}, "tailored_cv_tex": TAILORED_CV_TEX})

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.application.tailor_resume.post_json_schema",
            return_value=response,
        ) as openrouter_mock:
            tailor_modules(state)

        openrouter_mock.assert_called_once()
        self.assertIn("Tailor the CV letter", openrouter_mock.call_args.kwargs["user_prompt"])
        self.assertEqual(state["model_output"]["tailored_modules"]["summary.tex"], "AI summary.tex")
        self.assertEqual(state["model_output"]["tailored_cv_tex"], TAILORED_CV_TEX)

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

    def test_build_tailored_payload_writes_summary_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            response = json.dumps(
                {
                    "tailored_modules": {
                        "summary.tex": "\\begin{cvparagraph}\nSenior Software Engineer\n\\end{cvparagraph}",
                        "experience.tex": "\\cvsection{Experience}",
                        "personalprojects.tex": "\\cvsection{Personal Projects}",
                        "aboutme.tex": "Bachelor of Arts in Computer Science\nBachelor of Arts in Economics",
                    },
                    "tailored_cv_tex": TAILORED_CV_TEX,
                }
            )
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
                "src.application.tailor_resume.post_json_schema",
                return_value=response,
            ):
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
            self.assertIn("Senior Engineer role", payload["model_output"]["tailored_cv_tex"])
            self.assertTrue(Path(tmpdir, "resume", "modules", "summary.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "modules", "experience.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "modules", "personalprojects.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "modules", "aboutme.tex").exists())
            self.assertTrue(Path(tmpdir, "resume", "cv.tex").exists())
            self.assertIn("Senior Engineer role", Path(tmpdir, "resume", "cv.tex").read_text(encoding="utf-8"))
            if shutil.which("xelatex"):
                self.assertTrue(Path(tmpdir, "demo-job.pdf").exists())
                self.assertTrue(Path(tmpdir, "demo-job-cv.pdf").exists())
            else:
                self.assertEqual(payload["compile"]["pdf_path"], "")
                self.assertEqual(payload["compile"]["cv_pdf_path"], "")
            self.assertTrue(Path(tmpdir, "tailored_resume.json").exists())

    def test_run_uses_current_working_directory_for_default_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = Path(tmpdir) / "listing.txt"
            listing_path.write_text("Example listing", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch(
                    "src.cli.parse_job",
                    return_value={"job": {"company": "Acme", "title": "Senior Engineer"}},
                ), patch("src.cli.build_tailored_payload", return_value={"ok": True}):
                    exit_code = run(str(listing_path), None, None, None)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            output_dir = Path(tmpdir) / "output" / "acme-senior-engineer"
            self.assertTrue(output_dir.exists())
            self.assertTrue((output_dir / "tailored_resume.json").exists())

    def test_run_writes_source_history_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = Path(tmpdir) / "listing.txt"
            listing_path.write_text("Example listing", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch(
                    "src.cli.parse_job",
                    return_value={"job": {"company": "Acme", "title": "Senior Engineer"}},
                ), patch("src.cli.build_tailored_payload", return_value={"ok": True, "compile": {"pdf_path": ""}}):
                    exit_code = run(str(listing_path), "https://example.com/jobs/1", None, "gpt-4o-mini")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            log_path = Path(tmpdir) / "log" / "success_history.jsonl"
            self.assertTrue(log_path.exists())

    def test_run_writes_failed_output_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = Path(tmpdir) / "listing.txt"
            listing_path.write_text("Example listing", encoding="utf-8")

            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch(
                    "src.cli.parse_job",
                    return_value={
                        "job": {"company": "", "title": ""},
                        "metadata": {
                            "source_url": "https://example.com/jobs/1",
                            "validation_errors": ["Missing job title", "Missing company"],
                        },
                    },
                ), patch("src.cli.build_tailored_payload") as payload_mock:
                    exit_code = run(str(listing_path), "https://example.com/jobs/1", None, None)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(exit_code, 0)
            payload_mock.assert_not_called()

            failed_root = Path(tmpdir) / "output" / "failed"
            self.assertTrue((failed_root / "1" / "job_packet.json").exists())
            self.assertEqual(
                (failed_root / "failed.txt").read_text(encoding="utf-8").strip(),
                "https://example.com/jobs/1",
            )
            self.assertTrue((Path(tmpdir) / "log" / "failed_history.jsonl").exists())
            self.assertFalse((Path(tmpdir) / "log" / "success_history.jsonl").exists())

    def test_run_batch_urls_from_file_auto_generates_job_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                list_file = Path(tmpdir) / "urls.txt"
                list_file.write_text("https://example.com/job-a\nhttps://example.com/job-b\n", encoding="utf-8")

                def parse_job_side_effect(*, job_url, listing_text=""):
                    url = job_url or ""
                    if "job-a" in url:
                        return {
                            "job": {
                                "company": "Acme",
                                "title": "Senior Backend Engineer",
                                "must_have": ["Python"],
                                "nice_to_have": ["Docker"],
                                "domain": "SaaS",
                            }
                        }
                    else:
                        return {
                            "job": {
                                "company": "Acme",
                                "title": "Senior Backend Engineer",
                                "must_have": ["Python"],
                                "nice_to_have": ["Kubernetes"],
                                "domain": "SaaS",
                            }
                        }

                def payload_side_effect(job_packet, job_name, output_dir, model_name=None):
                    return {"compile": {"pdf_path": str(Path(output_dir) / f"{job_name}.pdf")}}

                with patch("src.cli.parse_job", side_effect=parse_job_side_effect) as parse_job_mock, patch(
                    "src.cli.build_tailored_payload", side_effect=payload_side_effect
                ) as payload_mock:
                    exit_code = run(
                        None,
                        None,
                        None,
                        None,
                        url_list_file=str(list_file),
                    )

                self.assertEqual(exit_code, 0)
                self.assertEqual(parse_job_mock.call_count, 2)
                self.assertEqual(payload_mock.call_count, 2)

                log_path = Path(tmpdir) / "log" / "success_history.jsonl"
                self.assertTrue(log_path.exists())
                entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertGreaterEqual(len(entries), 2)
                last_two = entries[-2:]
                names = [entry["job_name"] for entry in last_two]
                self.assertEqual(names[0], "acme-senior-backend-engineer")
                self.assertEqual(names[1], "acme-senior-backend-engineer-2")
            finally:
                os.chdir(previous_cwd)

    def test_run_recompile_mode_skips_parsing_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output" / "demo-job"
            output_dir.mkdir(parents=True, exist_ok=True)

            with patch("src.cli.parse_job") as parse_job_mock, patch(
                "src.cli.recompile_existing_output",
                return_value={"summary": str(output_dir / "tailored_resume.json"), "compile": {"pdf_path": str(output_dir / "demo-job.pdf"), "page_count": 1}},
            ) as recompile_mock:
                exit_code = run(None, None, str(output_dir), None, recompile_existing=True)

            self.assertEqual(exit_code, 0)
            recompile_mock.assert_called_once()
            parse_job_mock.assert_not_called()

    def test_run_build_basic_mode_skips_parsing_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.cli.parse_job") as parse_job_mock, patch(
                "src.cli.build_basic_resume",
                return_value={"output_dir": str(Path(tmpdir) / "output" / "general"), "pdf": str(Path(tmpdir) / "output" / "general" / "resume.pdf"), "compile_log": ""},
            ) as basic_mock:
                exit_code = run(None, None, str(Path(tmpdir) / "output" / "general"), None, build_basic=True)

            self.assertEqual(exit_code, 0)
            basic_mock.assert_called_once()
            parse_job_mock.assert_not_called()

    def test_rebuild_from_job_packet_generates_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_dir = Path(tmpdir) / "demo-job"
            packet_dir.mkdir(parents=True, exist_ok=True)
            packet_path = packet_dir / "job_packet.json"
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
                    "src.cli.build_tailored_payload",
                    return_value={"compile": {"pdf_path": str(Path(tmpdir) / "output" / "demo-job" / "demo-job.pdf")}},
                ):
                    result = rebuild_from_job_packet(str(packet_path), None, "gpt-4o-mini")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(result.get("mode"), "rebuild")
            self.assertEqual(result.get("job_name"), "demo-job")
            self.assertTrue(Path(result["output_dir"]).exists())
            self.assertTrue(Path(result["job_packet"]).exists())
            self.assertTrue(Path(result["summary"]).exists())
            self.assertEqual(result.get("model_name"), "gpt-4o-mini")

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

            with patch("src.cli.build_tailored_payload", return_value={"compile": {"pdf_path": ""}}):
                result = rebuild_all_job_packets(str(output_root), None)

            self.assertEqual(result["packet_count"], 2)
            self.assertEqual([entry["job_name"] for entry in result["rebuilds"]], ["alpha", "beta"])
            self.assertTrue((first_dir / "tailored_resume.json").exists())
            self.assertTrue((second_dir / "tailored_resume.json").exists())

    def test_clean_workspace_artifacts_removes_output_and_log_contents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            log_dir = Path(tmpdir) / "log"
            (output_dir / "sample" / "nested").mkdir(parents=True, exist_ok=True)
            (output_dir / "sample" / "nested" / "file.txt").write_text("data", encoding="utf-8")
            (log_dir / "success_history.jsonl").parent.mkdir(parents=True, exist_ok=True)
            (log_dir / "success_history.jsonl").write_text("entry", encoding="utf-8")

            result = clean_workspace_artifacts(output_root=str(output_dir), log_root=str(log_dir))

            self.assertEqual(result["output_dir"], str(output_dir))
            self.assertEqual(result["log_dir"], str(log_dir))
            self.assertTrue(output_dir.exists())
            self.assertTrue(log_dir.exists())
            self.assertEqual(list(output_dir.iterdir()), [])
            self.assertEqual(list(log_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, TypedDict

from src.infrastructure.latex import render_env_placeholders as _render_env_placeholders
from src.infrastructure.openrouter import post_json_schema
from src.infrastructure.prompt_config import load_prompt_config

class ResumeTailorState(TypedDict, total=False):
    job_packet: dict[str, Any]
    source_modules: dict[str, Any]
    source_letter_tex: str
    prompts: dict[str, str]
    model_output: dict[str, Any]
    violations: list[str]
    compile_log: str
    layout_profile: dict[str, int]
    model_name: str


PROMPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "infrastructure" / "prompts.json"
DEFAULT_PROMPTS: dict[str, str] = {
    "resume_customizer_system_prompt": (
        "You are an expert resume customizer. You will receive job information and existing "
        "resume files. Customize the resume to better match the target role while preserving "
        "truthfulness. Never invent achievements, skills, responsibilities, metrics, dates, "
        "titles, certifications, or technologies that are not already present in the source "
        "resume. Prioritize relevance, clarity, and concise professional language."
    ),
    "resume_customizer_user_prompt_template": (
        "Using only the information already present in the resume files, tailor the resume for "
        "this target role. Remove or de-emphasize low-relevance content, keep and strengthen "
        "high-relevance content, and rewrite selected bullets for clarity and impact. Keep "
        "wording natural and human-readable. Do not copy long phrases from the job "
        "description. Do not add new facts. Job information:\n\n{job_packet}"
    ),
    "additional_prompt": "Highlighted relevance to {skills} using existing experience while preserving factual accuracy.",
    "summary_section_prompt": "Keep the summary mostly intact and only adjust technology mentions based on overlap with experience evidence.",
    "experience_section_prompt": "Preserve original job grouping and order. Remove or reword bullets in place without mixing roles.",
    "personalprojects_section_prompt": (
        "Use fixed project priority independent of job description and only include the intro header when multiple projects are present. "
        "Priority order: getkan-cv||linux enthusiast||mystic type-writer||notesboard plus plus"
    ),
    "aboutme_section_prompt": "Always include required education facts in About Me.",
    "letter_prompt": (
        "Customize the supplied letter.tex as a short employer-facing letter of introduction for the target role. "
        "Keep the existing LaTeX styling, header, footer, letter metadata commands, cvletter environment, and closing structure. "
        "Tailor the paragraphs toward the company, role, domain, and strongest relevant evidence from the resume modules. "
        "Do not invent facts, metrics, dates, technologies, credentials, or personal details. Return a complete compilable letter.tex document."
    ),
}

def render_env_placeholders(text: str) -> str:
    return _render_env_placeholders(text, Path(__file__).resolve().parents[2])


def _load_prompt_config() -> dict[str, str]:
    return load_prompt_config(PROMPT_CONFIG_PATH, DEFAULT_PROMPTS, section="tailor")


def load_context(state: ResumeTailorState) -> ResumeTailorState:
    repo_root = Path(__file__).resolve().parents[2]
    modules_root = repo_root / "resume" / "modules"
    missing = [name for name in ("summary.tex", "experience.tex", "personalprojects.tex", "aboutme.tex") if not (modules_root / name).exists()]
    if missing or not (repo_root / "resume" / "letter.tex").exists():
        raise FileNotFoundError(
            f"Base resume source is incomplete under {repo_root / 'resume'}. "
            "Copy resume.example/ to resume/ and fill in your details before tailoring."
        )
    state["source_modules"] = {
        "summary.tex": (modules_root / "summary.tex").read_text(encoding="utf-8"),
        "experience.tex": (modules_root / "experience.tex").read_text(encoding="utf-8"),
        "personalprojects.tex": (modules_root / "personalprojects.tex").read_text(encoding="utf-8"),
        "aboutme.tex": (modules_root / "aboutme.tex").read_text(encoding="utf-8"),
    }
    state["source_letter_tex"] = (repo_root / "resume" / "letter.tex").read_text(encoding="utf-8")
    state["prompts"] = _load_prompt_config()
    return state


def _extract_json_payload(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _tailor_modules_with_openrouter(state: ResumeTailorState) -> ResumeTailorState:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    prompts = state["prompts"]
    source_modules = state["source_modules"]
    profile = state.get("layout_profile", {})
    module_names = ("summary.tex", "experience.tex", "personalprojects.tex", "aboutme.tex")
    user_prompt = prompts["resume_customizer_user_prompt_template"].format(
        job_packet=json.dumps(state["job_packet"], indent=2),
    )
    section_prompts = {
        "summary.tex": prompts.get("summary_section_prompt", ""),
        "experience.tex": prompts.get("experience_section_prompt", ""),
        "personalprojects.tex": prompts.get("personalprojects_section_prompt", ""),
        "aboutme.tex": prompts.get("aboutme_section_prompt", ""),
    }
    user_prompt += "\n\nSection instructions:\n" + "\n".join(
        f"{name}: {instruction}" for name, instruction in section_prompts.items()
    )
    user_prompt += "\nletter.tex: " + prompts.get("letter_prompt", "")
    user_prompt += "\n\nOne-page layout profile:\n" + json.dumps(profile)
    user_prompt += "\n\nSource TeX modules:\n" + json.dumps(
        {name: source_modules.get(name, "") for name in module_names},
        indent=2,
    )
    user_prompt += "\n\nSource letter.tex:\n" + state.get("source_letter_tex", "")
    schema = {
        "type": "object",
        "properties": {
            "tailored_modules": {
                "type": "object",
                "properties": {name: {"type": "string"} for name in module_names},
                "required": list(module_names),
                "additionalProperties": False,
            },
            "tailored_letter_tex": {"type": "string"},
        },
        "required": ["tailored_modules", "tailored_letter_tex"],
        "additionalProperties": False,
    }
    response = post_json_schema(
        api_key=api_key,
        model=state.get("model_name") or os.getenv("OPENROUTER_MODEL_TAILOR") or os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.7-sonnet"),
        system_prompt=prompts["resume_customizer_system_prompt"],
        user_prompt=user_prompt,
        schema_name="tailored_resume_modules",
        schema=schema,
        title="GETKAN-CV Resume Tailor",
        timeout=60,
        strict=True,
    )

    response_payload = _extract_json_payload(response)
    modules = response_payload.get("tailored_modules")
    if not isinstance(modules, dict) or any(not isinstance(modules.get(name), str) for name in module_names):
        raise RuntimeError("OpenRouter returned an invalid tailored resume module payload")
    tailored_letter_tex = response_payload.get("tailored_letter_tex")
    if not isinstance(tailored_letter_tex, str) or not tailored_letter_tex.strip():
        raise RuntimeError("OpenRouter returned an invalid tailored letter payload")
    state["model_output"] = {
        "tailored_modules": {name: modules[name] for name in module_names},
        "tailored_letter_tex": tailored_letter_tex,
    }
    return state


def tailor_modules(state: ResumeTailorState) -> ResumeTailorState:
    return _tailor_modules_with_openrouter(state)


def validate_output(state: ResumeTailorState) -> ResumeTailorState:
    state["violations"] = []
    return state


def write_artifacts(state: ResumeTailorState, output_dir: str | Path, job_name: str) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    legacy_tex_root = destination / "tex"
    if legacy_tex_root.exists() and legacy_tex_root.is_dir():
        shutil.rmtree(legacy_tex_root)

    # Remove legacy artifacts from older runs.
    for legacy_name in ["relevance_notes.txt", "summary.tex", "experience_highlights.tex", "experience.tex", "personalprojects.tex"]:
        legacy_path = destination / legacy_name
        if legacy_path.exists():
            legacy_path.unlink()

    resume_root = destination / "resume"
    modules_out = resume_root / "modules"
    modules_out.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[2]
    source_modules = repo_root / "resume" / "modules"
    source_resume = repo_root / "resume" / "resume.tex"
    source_letter = repo_root / "resume" / "letter.tex"
    source_fonts = repo_root / "resume" / "fonts"
    class_file = repo_root / "getkan-cv.cls"

    for module in source_modules.glob("*.tex"):
        shutil.copy2(module, modules_out / module.name)

    for name, content in state["model_output"].get("tailored_modules", {}).items():
        if not name.endswith(".tex"):
            continue
        module_path = modules_out / name
        module_path.write_text(content, encoding="utf-8")

    resume_target = resume_root / "resume.tex"
    resume_target.write_text(source_resume.read_text(encoding="utf-8"), encoding="utf-8")
    letter_target = resume_root / "letter.tex"
    letter_target.write_text(state["model_output"].get("tailored_letter_tex") or source_letter.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(class_file, resume_root / class_file.name)
    if source_fonts.exists():
        shutil.copytree(source_fonts, resume_root / "fonts", dirs_exist_ok=True)

    # Ensure copied resume uses local class and font directories.
    resume_text = resume_target.read_text(encoding="utf-8")
    resume_text = resume_text.replace("\\documentclass[11pt, letterpaper]{../getkan-cv}", "\\documentclass[11pt, letterpaper]{getkan-cv}")
    resume_text = resume_text.replace("\\fontdir[../fonts/]", "\\fontdir[fonts/]")
    resume_text = render_env_placeholders(resume_text)
    resume_target.write_text(resume_text, encoding="utf-8")

    letter_text = letter_target.read_text(encoding="utf-8")
    letter_text = letter_text.replace("\\documentclass[11pt, letterpaper]{../getkan-cv}", "\\documentclass[11pt, letterpaper]{getkan-cv}")
    letter_text = letter_text.replace("\\fontdir[../fonts/]", "\\fontdir[fonts/]")
    letter_text = render_env_placeholders(letter_text)
    letter_target.write_text(letter_text, encoding="utf-8")

    job_destination = destination / "job"
    job_destination.mkdir(parents=True, exist_ok=True)
    output_path = job_destination / "tailored_resume.json"
    output_path.write_text(json.dumps(state["model_output"], indent=2), encoding="utf-8")
    return {
        "output_path": str(output_path),
        "resume_root": str(resume_root),
        "resume_tex": str(resume_target),
        "letter_tex": str(letter_target),
        "output_dir": str(destination),
        "job_name": job_name,
    }


def _compile_tex_to_pdf(xelatex: str, source_root: Path, tex_filename: str, output_pdf: Path) -> tuple[bool, list[str]]:
    logs: list[str] = []
    for pass_index in range(2):
        result = subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", tex_filename],
            cwd=source_root,
            capture_output=True,
            text=True,
        )
        logs.append(f"{tex_filename} pass {pass_index + 1} exit={result.returncode}")
        if result.stdout:
            logs.append(result.stdout[-1200:])
        if result.stderr:
            logs.append(result.stderr[-1200:])
        if result.returncode != 0:
            return False, logs

    compiled_pdf = source_root / f"{Path(tex_filename).stem}.pdf"
    if compiled_pdf.exists():
        shutil.copy2(compiled_pdf, output_pdf)
    return True, logs


def compile_and_summarize(state: ResumeTailorState, artifacts: dict[str, Any]) -> dict[str, Any]:
    xelatex = shutil.which("xelatex")
    if not xelatex:
        return {"compile_log": "xelatex not available on PATH", "summary": "Tailoring completed, PDF compile skipped", "pdf_path": "", "cv_pdf_path": ""}

    resume_tex = Path(artifacts["resume_tex"])
    letter_tex = Path(artifacts.get("letter_tex") or resume_tex.with_name("letter.tex"))
    source_root = Path(artifacts.get("resume_root") or artifacts.get("tex_root") or resume_tex.parent)
    output_dir = Path(artifacts.get("output_dir") or source_root.parent)
    job_name = str(artifacts.get("job_name") or output_dir.name)
    safe_job_name = re.sub(r"[^A-Za-z0-9._-]", "-", job_name).strip("-") or "resume"
    published_pdf = output_dir / f"{safe_job_name}.pdf"
    published_cv_pdf = output_dir / f"{safe_job_name}-cv.pdf"
    logs: list[str] = []

    if resume_tex.exists():
        resume_tex.write_text(render_env_placeholders(resume_tex.read_text(encoding="utf-8")), encoding="utf-8")
    if letter_tex.exists():
        letter_tex.write_text(render_env_placeholders(letter_tex.read_text(encoding="utf-8")), encoding="utf-8")

    resume_ok, resume_logs = _compile_tex_to_pdf(xelatex, source_root, "resume.tex", published_pdf)
    logs.extend(resume_logs)
    if not resume_ok:
        return {"compile_log": "\n".join(logs), "summary": "Tailoring completed, resume PDF compile failed", "pdf_path": "", "cv_pdf_path": ""}

    cv_pdf_path = ""
    if letter_tex.exists():
        letter_ok, letter_logs = _compile_tex_to_pdf(xelatex, source_root, "letter.tex", published_cv_pdf)
        logs.extend(letter_logs)
        if not letter_ok:
            return {
                "compile_log": "\n".join(logs),
                "summary": "Tailoring completed, CV PDF compile failed",
                "pdf_path": str(published_pdf if published_pdf.exists() else ""),
                "cv_pdf_path": "",
            }
        cv_pdf_path = str(published_cv_pdf if published_cv_pdf.exists() else "")

    return {
        "compile_log": "\n".join(logs),
        "summary": "Tailoring completed and PDFs compiled",
        "pdf_path": str(published_pdf if published_pdf.exists() else ""),
        "cv_pdf_path": cv_pdf_path,
    }


def _pdf_page_count(pdf_path: str) -> int | None:
    if not pdf_path:
        return None
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return None
    try:
        result = subprocess.run([pdfinfo, pdf_path], capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"(?m)^Pages:\s*(\d+)", result.stdout)
    if not match:
        return None
    return int(match.group(1))


def recompile_existing_output(output_dir: str | Path) -> dict[str, Any]:
    destination = Path(output_dir)
    resume_root = destination / "resume"
    legacy_tex_root = destination / "tex"
    source_root = resume_root if (resume_root / "resume.tex").exists() else legacy_tex_root
    resume_tex = source_root / "resume.tex"
    if not resume_tex.exists():
        raise FileNotFoundError(f"Expected resume source not found: {resume_tex}")

    # Keep recompile mode resilient if font assets were moved or cleaned up.
    repo_root = Path(__file__).resolve().parents[2]
    source_fonts = repo_root / "resume" / "fonts"
    if source_fonts.exists():
        shutil.copytree(source_fonts, source_root / "fonts", dirs_exist_ok=True)

    artifacts = {
        "output_path": str(destination / "tailored_resume.json"),
        "resume_root": str(source_root),
        "resume_tex": str(resume_tex),
        "letter_tex": str(source_root / "letter.tex"),
        "output_dir": str(destination),
        "job_name": destination.name,
    }

    compile_result = compile_and_summarize({}, artifacts)
    page_count = _pdf_page_count(compile_result.get("pdf_path", ""))
    if page_count is not None:
        compile_result["page_count"] = page_count

    summary_path = destination / "tailored_resume.json"
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload["compile"] = compile_result
                summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "output_dir": str(destination),
        "artifacts": artifacts,
        "compile": compile_result,
        "summary": str(summary_path),
    }


def build_tailored_payload(job_packet: dict[str, Any], job_name: str, output_dir: str | Path, model_name: str | None = None) -> dict[str, Any]:
    state: ResumeTailorState = {
        "job_packet": job_packet,
        "source_modules": {},
        "model_output": {},
        "violations": [],
        "compile_log": "",
        "model_name": model_name or "",
    }
    load_context(state)
    layout_profiles = [
        {
            "summary_sentences": 2,
            "experience_cvitems_limit": 1,
            "experience_cvsubitems_limit": 4,
            "personalprojects_limit": 2,
            "aboutme_limit": 1,
            "item_word_limit": 28,
        },
        {
            "summary_sentences": 2,
            "experience_cvitems_limit": 1,
            "experience_cvsubitems_limit": 3,
            "personalprojects_limit": 1,
            "aboutme_limit": 1,
            "item_word_limit": 24,
        },
        {
            "summary_sentences": 1,
            "experience_cvitems_limit": 1,
            "experience_cvsubitems_limit": 2,
            "personalprojects_limit": 1,
            "aboutme_limit": 0,
            "item_word_limit": 18,
        },
    ]

    compile_result: dict[str, Any] = {"summary": "Tailoring completed, PDF compile skipped", "pdf_path": "", "compile_log": ""}
    artifacts: dict[str, Any] = {}
    selected_page_count: int | None = None

    for profile in layout_profiles:
        state["layout_profile"] = profile
        tailor_modules(state)
        validate_output(state)
        artifacts = write_artifacts(state, output_dir, job_name=job_name)
        compile_result = compile_and_summarize(state, artifacts)
        selected_page_count = _pdf_page_count(compile_result.get("pdf_path", ""))
        if selected_page_count is not None and selected_page_count <= 1:
            break

    if selected_page_count is not None:
        compile_result["page_count"] = selected_page_count

    return {
        "job_name": job_name,
        "model_name": model_name or "default",
        "job_packet": job_packet,
        "artifacts": artifacts,
        "model_output": state["model_output"],
        "compile": compile_result,
    }

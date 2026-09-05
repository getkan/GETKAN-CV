from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, TypedDict

from src.infrastructure.openrouter import post_json_schema
from src.infrastructure.prompt_config import load_prompt_config

class ResumeTailorState(TypedDict, total=False):
    job_packet: dict[str, Any]
    source_modules: dict[str, Any]
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
    "aboutme_required_items": "Bachelor of Arts in Computer Science||Bachelor of Arts in Economics",
}

_ENV_TOKEN_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _load_env_values() -> dict[str, str]:
    values: dict[str, str] = dict(os.environ)
    repo_root = Path(__file__).resolve().parents[2]
    dotenv_candidates = [Path.cwd() / ".env", repo_root / ".env"]

    for env_path in dotenv_candidates:
        if not env_path.exists():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def render_env_placeholders(text: str) -> str:
    env_values = _load_env_values()

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return env_values.get(key, match.group(0))

    return _ENV_TOKEN_PATTERN.sub(_replace, text)


def _load_prompt_config() -> dict[str, str]:
    return load_prompt_config(PROMPT_CONFIG_PATH, DEFAULT_PROMPTS, section="tailor")


def load_context(state: ResumeTailorState) -> ResumeTailorState:
    repo_root = Path(__file__).resolve().parents[2]
    modules_root = repo_root / "resume" / "modules"
    state["source_modules"] = {
        "summary.tex": (modules_root / "summary.tex").read_text(encoding="utf-8"),
        "experience.tex": (modules_root / "experience.tex").read_text(encoding="utf-8"),
        "personalprojects.tex": (modules_root / "personalprojects.tex").read_text(encoding="utf-8"),
        "aboutme.tex": (modules_root / "aboutme.tex").read_text(encoding="utf-8"),
    }
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
    user_prompt += "\n\nOne-page layout profile:\n" + json.dumps(profile)
    user_prompt += "\n\nSource TeX modules:\n" + json.dumps(
        {name: source_modules.get(name, "") for name in module_names},
        indent=2,
    )
    schema = {
        "type": "object",
        "properties": {
            "tailored_modules": {
                "type": "object",
                "properties": {name: {"type": "string"} for name in module_names},
                "required": list(module_names),
                "additionalProperties": False,
            }
        },
        "required": ["tailored_modules"],
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

    modules = _extract_json_payload(response).get("tailored_modules")
    if not isinstance(modules, dict) or any(not isinstance(modules.get(name), str) for name in module_names):
        raise RuntimeError("OpenRouter returned an invalid tailored resume module payload")
    state["model_output"] = {"tailored_modules": {name: modules[name] for name in module_names}}
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
    shutil.copy2(class_file, resume_root / class_file.name)
    if source_fonts.exists():
        shutil.copytree(source_fonts, resume_root / "fonts", dirs_exist_ok=True)

    # Ensure copied resume uses local class and font directories.
    resume_text = resume_target.read_text(encoding="utf-8")
    resume_text = resume_text.replace("\\documentclass[11pt, letterpaper]{../getkan-cv}", "\\documentclass[11pt, letterpaper]{getkan-cv}")
    resume_text = resume_text.replace("\\fontdir[../fonts/]", "\\fontdir[fonts/]")
    resume_text = render_env_placeholders(resume_text)
    resume_target.write_text(resume_text, encoding="utf-8")

    output_path = destination / "tailored_resume.json"
    output_path.write_text(json.dumps(state["model_output"], indent=2), encoding="utf-8")
    return {
        "output_path": str(output_path),
        "resume_root": str(resume_root),
        "resume_tex": str(resume_target),
        "output_dir": str(destination),
        "job_name": job_name,
    }


def compile_and_summarize(state: ResumeTailorState, artifacts: dict[str, Any]) -> dict[str, Any]:
    xelatex = shutil.which("xelatex")
    if not xelatex:
        return {"compile_log": "xelatex not available on PATH", "summary": "Tailoring completed, PDF compile skipped", "pdf_path": ""}

    resume_tex = Path(artifacts["resume_tex"])
    source_root = Path(artifacts.get("resume_root") or artifacts.get("tex_root") or resume_tex.parent)
    output_dir = Path(artifacts.get("output_dir") or source_root.parent)
    job_name = str(artifacts.get("job_name") or output_dir.name)
    safe_job_name = re.sub(r"[^A-Za-z0-9._-]", "-", job_name).strip("-") or "resume"
    output_pdf = source_root / "resume.pdf"
    published_pdf = output_dir / f"{safe_job_name}.pdf"
    logs: list[str] = []

    if resume_tex.exists():
        resume_tex.write_text(render_env_placeholders(resume_tex.read_text(encoding="utf-8")), encoding="utf-8")

    for pass_index in range(2):
        result = subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
            cwd=source_root,
            capture_output=True,
            text=True,
        )
        logs.append(f"pass {pass_index + 1} exit={result.returncode}")
        if result.stdout:
            logs.append(result.stdout[-1200:])
        if result.stderr:
            logs.append(result.stderr[-1200:])
        if result.returncode != 0:
            return {"compile_log": "\n".join(logs), "summary": "Tailoring completed, PDF compile failed", "pdf_path": ""}

    if output_pdf.exists():
        shutil.copy2(output_pdf, published_pdf)

    return {
        "compile_log": "\n".join(logs),
        "summary": "Tailoring completed and PDF compiled",
        "pdf_path": str(published_pdf if published_pdf.exists() else ""),
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

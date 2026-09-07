
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.infrastructure.environment import load_dotenv
from src.infrastructure.openrouter import post_json_schema
from src.infrastructure.prompt_config import load_prompt_config

RESUME_MODULE_NAMES = ("summary.tex", "experience.tex", "personalprojects.tex", "aboutme.tex")
PROMPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "infrastructure" / "prompts.json"


def _normalize_skill(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    cleaned = re.sub(r"^[\-\*\d\.)\(\s]+", "", cleaned)
    cleaned = cleaned.strip(" ,.;:")
    return cleaned


def _section_paragraph(summary: str, advice: str) -> str:
    parts: list[str] = []
    summary_text = _normalize_skill(summary)
    if summary_text:
        parts.append(f"Summary: {summary_text}.")

    advice_text = _normalize_skill(advice)
    if advice_text:
        parts.append(f"Advice: {advice_text}.")

    if not parts:
        parts.append("Summary: Add job packets to generate a tailored summary and advice.")

    return " ".join(parts)


def render_general_advice_section(*, summary: str, general_advice: str) -> dict[str, Any]:
    paragraph = _section_paragraph(summary, general_advice)
    return {
        "heading": "## General Advice and Summary",
        "lines": ["## General Advice and Summary", "", paragraph],
        "summary": summary,
        "general_advice": general_advice,
    }


def render_recommend_skills_section(*, skill_rows: list[dict[str, int]]) -> dict[str, Any]:
    rendered_rows = _qualifying_skill_rows(skill_rows)
    return {
        "heading": "## Skills",
        "lines": _skill_table_lines(skill_rows),
        "skills": [str(row["skill"]) for row in rendered_rows],
    }


def render_portfolio_suggestions_section(*, items: list[str]) -> dict[str, Any]:
    return {"heading": "## Portfolio or Project Suggestions", "lines": _bullet_lines(items, "## Portfolio or Project Suggestions", "No portfolio or project suggestions yet."), "items": items}


def _job_titles_bullet_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["## Recommended Job Titles", ""]
    if not rows:
        lines.append("- No job packets provided.")
        return lines

    for row in rows:
        summary = f"{row['description']}. {row['rationale']}".strip()
        lines.append(f"- {row['job_title']} (score {row['compatibility_score']}): {summary}")
    return lines


def render_recommended_job_titles_section(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"heading": "## Recommended Job Titles", "lines": _job_titles_bullet_lines(rows), "rows": rows}


def render_interview_prep_section(*, items: list[str]) -> dict[str, Any]:
    return {"heading": "## Interview Prep", "lines": _bullet_lines(items, "## Interview Prep", "Review the packets, role fit, and recent project stories."), "items": items}


def _recommendation_bullet_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["## Resume Recommendation", ""]
    if not rows:
        lines.append("- No resume recommendations available.")
        return lines

    for row in rows:
        summary = f"{row['recommendation']}. {row['reason']}".strip()
        lines.append(f"- {row['area']}: {summary} (P{row['priority']})")
    return lines


def render_resume_recommendation_section(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"heading": "## Resume Recommendation", "lines": _recommendation_bullet_lines(rows), "rows": rows}


def render_ats_keyword_gaps_section(*, items: list[str]) -> dict[str, Any]:
    return {"heading": "## ATS Keyword Gaps", "lines": _bullet_lines(items, "## ATS Keyword Gaps", "No major ATS gaps identified."), "items": items}


def _most_compatible_jobs_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["## Most Compatible Jobs", ""]
    if not rows:
        lines.append("- No job packets provided.")
        return lines

    for row in rows:
        title = row.get("title") or "unknown"
        company = row.get("company") or "unknown"
        score = row.get("compatibility_score") or 0
        lines.append(f"- {title} at {company} (score {score})")
    return lines


def render_most_compatible_jobs_section(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"heading": "## Most Compatible Jobs", "lines": _most_compatible_jobs_lines(rows), "rows": rows}


SKILL_STOPWORDS = {
    "experience",
    "knowledge",
    "skills",
    "ability",
    "communication",
    "team",
    "teams",
    "preferred",
    "required",
    "plus",
}

DEFAULT_ADVISOR_PROMPTS: dict[str, str] = {
    "advisor_general_advice_system_prompt": (
        "You are a senior career advisor. Return only valid JSON with summary, general_advice, recommended_job_titles, resume_recommendations, interview_prep, ats_keyword_gaps, and portfolio_suggestions. No markdown."
    ),
    "advisor_general_advice_user_prompt_template": (
        "Using the resume corpus and job packets, produce one concise summary and short bullets for every section. Keep the output practical and brief. Job titles should fit the resume and the packet compatibility. Resume recommendations should improve hireability without inventing experience. Interview prep, ATS keyword gaps, and portfolio suggestions should be short and specific.\n\n"
        "Resume corpus:\n{resume_corpus}\n\nJob packets summary:\n{job_packets}"
    ),
    "advisor_recommendations_bundle_system_prompt": (
        "You are a senior career advisor. Return only valid JSON with summary, general_advice, recommended_job_titles, resume_recommendations, interview_prep, ats_keyword_gaps, and portfolio_suggestions. No markdown."
    ),
    "advisor_recommendations_bundle_user_prompt_template": (
        "Using the resume corpus and job packets, produce one concise summary and short bullets for every section. Keep the output practical and brief. Job titles should fit the resume and the packet compatibility. Resume recommendations should improve hireability without inventing experience. Interview prep, ATS keyword gaps, and portfolio suggestions should be short and specific.\n\n"
        "Resume corpus:\n{resume_corpus}\n\nJob packets summary:\n{job_packets}"
    ),
    "advisor_job_titles_system_prompt": (
        "You are a senior career advisor. Return only valid JSON with a recommended_job_titles array of concise role titles and short descriptions, no markdown."
    ),
    "advisor_job_titles_user_prompt_template": (
        "Based on the resume corpus, the job packets, and the compatibility scores below, recommend job titles that best match the current resume. Include title, description, and a short rationale for each.\n\n"
        "Resume corpus:\n{resume_corpus}\n\nJob packets summary:\n{job_packets}"
    ),
    "advisor_resume_recommendation_system_prompt": (
        "You are a senior career advisor. Return only valid JSON with a resume_recommendations array of concise resume improvement suggestions, no markdown."
    ),
    "advisor_resume_recommendation_user_prompt_template": (
        "Based on the current resume corpus and job packets, recommend resume changes that improve hireability without inventing more work experience. Focus on sections, bullets, wording, and skills presentation.\n\n"
        "Resume corpus:\n{resume_corpus}\n\nJob packets summary:\n{job_packets}"
    ),
}


def _load_advisor_prompts() -> dict[str, str]:
    return load_prompt_config(PROMPT_CONFIG_PATH, DEFAULT_ADVISOR_PROMPTS, section="advisor")


def _is_skill_candidate(value: str) -> bool:
    lowered = value.lower()
    if not lowered:
        return False
    if lowered in SKILL_STOPWORDS:
        return False
    if len(lowered) < 2 or len(lowered) > 48:
        return False
    return True


def _collect_job_packets(output_root: Path) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for packet_path in sorted(output_root.rglob("job_packet.json")):
        if "failed" in packet_path.relative_to(output_root).parts:
            continue
        try:
            payload = json.loads(packet_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("job"), dict):
            packets.append(payload)
    return packets


def _collect_job_packets_from_files(packet_files: list[str] | None) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for raw_path in packet_files or []:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("job"), dict):
            packets.append(payload)
    return packets


def _build_resume_corpus(resume_modules_dir: Path) -> str:
    chunks: list[str] = []
    for name in RESUME_MODULE_NAMES:
        path = resume_modules_dir / name
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_json_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {}

    cleaned = _strip_code_fences(content)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact_job_packets(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_packets: list[dict[str, Any]] = []
    for payload in packets[:40]:
        job = payload.get("job", {}) if isinstance(payload, dict) else {}
        compact_packets.append(
            {
                "title": str(job.get("title") or ""),
                "company": str(job.get("company") or ""),
                "domain": str(job.get("domain") or ""),
                "must_have": [str(item) for item in (job.get("must_have") or [])][:20],
                "nice_to_have": [str(item) for item in (job.get("nice_to_have") or [])][:20],
                "responsibilities": [str(item) for item in (job.get("responsibilities") or [])][:20],
                "description": str(job.get("description") or "")[:1200],
            }
        )
    return compact_packets


def _unique_skills(skills: list[str]) -> list[str]:
    unique_skills: list[str] = []
    seen: set[str] = set()
    for raw_skill in skills:
        skill = _normalize_skill(str(raw_skill))
        if not skill:
            continue
        key = skill.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_skills.append(skill)
    return unique_skills


def _count_skill_mentions(skill: str, packets: list[dict[str, Any]]) -> dict[str, int]:
    normalized_skill = _normalize_skill(skill).lower()
    must_have_count = 0
    good_to_have_count = 0

    for payload in packets:
        job = payload.get("job", {}) if isinstance(payload, dict) else {}
        must_have_items = {_normalize_skill(str(item)).lower() for item in (job.get("must_have") or []) if _normalize_skill(str(item))}
        nice_to_have_items = {_normalize_skill(str(item)).lower() for item in (job.get("nice_to_have") or []) if _normalize_skill(str(item))}

        if normalized_skill in must_have_items:
            must_have_count += 1
        if normalized_skill in nice_to_have_items:
            good_to_have_count += 1

    return {
        "skill": _normalize_skill(skill),
        "must_haves": must_have_count,
        "good_to_haves": good_to_have_count,
        "total": must_have_count + good_to_have_count,
    }


def _build_skill_rows_from_packets(packets: list[dict[str, Any]]) -> list[dict[str, int]]:
    compiled_skills: list[str] = []
    for payload in packets:
        job = payload.get("job", {}) if isinstance(payload, dict) else {}
        raw_skills = [
            *[str(item) for item in (job.get("must_have") or [])],
            *[str(item) for item in (job.get("nice_to_have") or [])],
        ]
        for raw_skill in raw_skills:
            skill = _normalize_skill(raw_skill)
            if not _is_skill_candidate(skill):
                continue
            compiled_skills.append(skill)

    skills = _unique_skills(compiled_skills)
    skill_rows = [_count_skill_mentions(skill, packets) for skill in skills]
    skill_rows = [row for row in skill_rows if row["total"] > 0]
    skill_rows.sort(key=lambda row: (-row["total"], -row["must_haves"], -row["good_to_haves"], row["skill"].lower()))
    return skill_rows


def _qualifying_skill_rows(skill_rows: list[dict[str, int]]) -> list[dict[str, int]]:
    return [row for row in skill_rows if int(row["must_haves"]) >= 3][:20]


def _skill_table_lines(skill_rows: list[dict[str, int]]) -> list[str]:
    lines = ["## Skills", "", "| Skill | Must Haves | Good To Haves | Total |", "| --- | ---: | ---: | ---: |"]
    filtered_rows = _qualifying_skill_rows(skill_rows)
    if not filtered_rows:
        lines.append("| None identified | 0 | 0 | 0 |")
        return lines

    for row in filtered_rows:
        lines.append(
            f"| {row['skill']} | {row['must_haves']} | {row['good_to_haves']} | {row['total']} |"
        )
    return lines


def _parse_skill_rows_from_table_lines(lines: list[str]) -> list[dict[str, int]]:
    skill_rows: list[dict[str, int]] = []
    for line in lines:
        if not line.startswith("| ") or line.startswith("| Skill") or line.startswith("| ---") or line.startswith("| None identified"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != 4:
            continue
        try:
            must_haves = int(parts[1])
            good_to_haves = int(parts[2])
            total = int(parts[3])
        except ValueError:
            continue
        skill_rows.append(
            {
                "skill": parts[0],
                "must_haves": must_haves,
                "good_to_haves": good_to_haves,
                "total": total,
            }
        )
    return skill_rows


def _compact_packets_with_scores(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored_packets: list[dict[str, Any]] = []
    for payload, compact in zip(packets, _compact_job_packets(packets)):
        scored_packets.append({**compact, "compatibility_score": int(payload.get("compatibility_score") or 0)})
    scored_packets.sort(key=lambda item: (-int(item.get("compatibility_score") or 0), str(item.get("title") or "").lower()))
    return scored_packets


def _bullet_lines(items: list[str], heading: str, placeholder: str, prefix: str = "- ") -> list[str]:
    lines = [heading, ""]
    if not items:
        lines.append(f"{prefix}{placeholder}")
        return lines
    for item in items:
        text = _normalize_skill(str(item))
        if text:
            lines.append(f"{prefix}{text}")
    return lines


def _post_openrouter_json(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    message = post_json_schema(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_name=schema_name,
        schema=schema,
        title="GETKAN-CV Job Hunt Advisor",
        timeout=60,
        strict=True,
    )
    payload = _extract_json_payload(message)
    if not payload:
        raise RuntimeError("OpenRouter did not return valid advisor JSON")
    return payload


def _generate_recommendation_sections(
    *,
    resume_modules_dir: str | Path | None,
    packets: list[dict[str, Any]],
    model_name: str | None,
) -> list[str]:
    modules_dir = Path(resume_modules_dir) if resume_modules_dir else (Path(__file__).resolve().parents[2] / "resume" / "modules")
    model = model_name or os.getenv("OPENROUTER_MODEL_ADVISOR") or os.getenv("OPENROUTER_MODEL") or "openai/gpt-4o-mini"

    if not packets:
        sections = [
            render_general_advice_section(
                summary="The current resume shows experience worth tailoring, but job packets are needed for targeted guidance.",
                general_advice=(
                    "Lead with the roles you want and the impact you have shipped. "
                    "Mirror the language from target jobs in your summary and bullets. "
                    "Keep the strongest evidence near the top of the resume."
                ),
            ),
            render_most_compatible_jobs_section(rows=[]),
            render_recommend_skills_section(skill_rows=[]),
            render_recommended_job_titles_section(rows=[]),
            render_resume_recommendation_section(rows=[]),
            render_interview_prep_section(items=[]),
            render_ats_keyword_gaps_section(items=[]),
            render_portfolio_suggestions_section(items=[]),
        ]

        lines: list[str] = []
        for index, section in enumerate(sections):
            lines.extend(section["lines"])
            if index != len(sections) - 1:
                lines.append("")
        return lines

    prompts = _load_advisor_prompts()
    resume_corpus = _build_resume_corpus(modules_dir)
    compact_packets = _compact_packets_with_scores(packets)
    payload = _post_openrouter_json(
        model=model,
        system_prompt=prompts["advisor_recommendations_bundle_system_prompt"],
        user_prompt=prompts["advisor_recommendations_bundle_user_prompt_template"].format(
            resume_corpus=resume_corpus,
            job_packets=json.dumps(compact_packets, ensure_ascii=False),
        ),
        schema_name="advisor_recommendations_bundle",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "general_advice": {"type": "string"},
                "recommended_job_titles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "job_title": {"type": "string"},
                            "description": {"type": "string"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["job_title", "description", "rationale"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 5,
                },
                "resume_recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "area": {"type": "string"},
                            "recommendation": {"type": "string"},
                            "reason": {"type": "string"},
                            "priority": {"type": "integer"},
                        },
                        "required": ["area", "recommendation", "reason", "priority"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 6,
                },
                "interview_prep": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 0,
                    "maxItems": 8,
                },
                "ats_keyword_gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 0,
                    "maxItems": 8,
                },
                "portfolio_suggestions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 0,
                    "maxItems": 6,
                },
            },
            "required": [
                "summary",
                "general_advice",
                "recommended_job_titles",
                "resume_recommendations",
                "interview_prep",
                "ats_keyword_gaps",
                "portfolio_suggestions",
            ],
            "additionalProperties": False,
        },
    )

    summary = _normalize_skill(str(payload.get("summary") or ""))
    general_advice = _normalize_skill(str(payload.get("general_advice") or ""))

    skill_rows = _build_skill_rows_from_packets(packets)

    scored_packets = _compact_packets_with_scores(packets)
    most_compatible_rows = scored_packets[:5]

    job_title_rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("recommended_job_titles", [])[:5]):
        if not isinstance(item, dict):
            continue
        job_title_text = _normalize_skill(str(item.get("job_title") or ""))
        source = next(
            (
                packet
                for packet in scored_packets
                if job_title_text and job_title_text.lower() == str(packet.get("title") or "").strip().lower()
            ),
            {},
        )
        job_title_rows.append(
            {
                "job_title": job_title_text,
                "description": _normalize_skill(str(item.get("description") or "")),
                "rationale": _normalize_skill(str(item.get("rationale") or "")),
                "compatibility_score": int(source.get("compatibility_score") or 0),
            }
        )
    job_title_rows.sort(key=lambda row: (-row["compatibility_score"], row["job_title"].lower()))

    resume_rows: list[dict[str, Any]] = []
    for item in payload.get("resume_recommendations", [])[:6]:
        if not isinstance(item, dict):
            continue
        resume_rows.append(
            {
                "area": _normalize_skill(str(item.get("area") or "")),
                "recommendation": _normalize_skill(str(item.get("recommendation") or "")),
                "reason": _normalize_skill(str(item.get("reason") or "")),
                "priority": int(item.get("priority") or 0),
            }
        )
    resume_rows.sort(key=lambda row: (-row["priority"], row["area"].lower()))

    sections = [
        render_general_advice_section(summary=summary, general_advice=general_advice),
        render_most_compatible_jobs_section(rows=most_compatible_rows),
        render_recommend_skills_section(skill_rows=skill_rows),
        render_recommended_job_titles_section(rows=job_title_rows),
        render_resume_recommendation_section(rows=resume_rows),
        render_interview_prep_section(items=[str(item) for item in payload.get("interview_prep", [])]),
        render_ats_keyword_gaps_section(items=[str(item) for item in payload.get("ats_keyword_gaps", [])]),
        render_portfolio_suggestions_section(items=[str(item) for item in payload.get("portfolio_suggestions", [])]),
    ]

    lines: list[str] = []
    for index, section in enumerate(sections):
        lines.extend(section["lines"])
        if index != len(sections) - 1:
            lines.append("")
    return lines


def generate_job_hunt_recommendations(
    output_root: str | Path,
    resume_modules_dir: str | Path | None = None,
    recommendations_filename: str = "job_hunt_recommendations.md",
    job_packet_files: list[str] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    output_path = Path(output_root)
    output_path.mkdir(parents=True, exist_ok=True)

    explicit_packets = _collect_job_packets_from_files(job_packet_files)
    packets = explicit_packets or _collect_job_packets(output_path)
    recommendations_path = output_path / recommendations_filename

    skills_table_lines = _generate_recommendation_sections(
        resume_modules_dir=resume_modules_dir,
        packets=packets,
        model_name=model_name,
    )
    skill_rows = _parse_skill_rows_from_table_lines(skills_table_lines)
    skill_names = [row["skill"] for row in skill_rows]

    if not packets:
        lines = [
            "# Job Hunt Recommendations",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Advisor model: {model_name or 'default'}",
            "Job packets analyzed: 0",
            "",
        ]
        lines.extend(skills_table_lines)
        lines.append("")
        recommendations_path.write_text("\n".join(lines), encoding="utf-8")
        return {
            "recommendations_path": str(recommendations_path),
            "packet_count": 0,
            "skills": skill_names,
            "skill_rows": skill_rows,
            "job_titles": [],
            "resume_recommendations": [],
        }

    lines: list[str] = []
    lines.append("# Job Hunt Recommendations")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Advisor model: {model_name or 'default'}")
    lines.append(f"Job packets analyzed: {len(packets)}")
    lines.append("")
    lines.extend(skills_table_lines)
    lines.append("")

    recommendations_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "recommendations_path": str(recommendations_path),
        "packet_count": len(packets),
        "skills": skill_names,
        "skill_rows": skill_rows,
        "job_titles": [],
        "resume_recommendations": [],
    }

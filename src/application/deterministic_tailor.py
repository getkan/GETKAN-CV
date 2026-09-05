"""Legacy deterministic resume tailoring. Not used by the OpenRouter workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.application.tailor_resume import DEFAULT_PROMPTS, ResumeTailorState

DEFAULT_SKILLS: dict[str, list[str]] = {
    "programming_languages": ["JavaScript", "PHP", "Python", "TypeScript"],
    "application_frameworks": ["Vue", "React", "Laravel"],
    "devops_and_delivery": ["Git", "Docker", "GitHub Actions"],
    "testing_and_quality": ["Jest", "Vue Test Utils", "Unit Testing", "Integration Testing", "Test Strategy"],
}
SKILLS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "resume" / "modules" / "skills.json"

def _load_skills_config() -> dict[str, list[str]]:
    if not SKILLS_CONFIG_PATH.exists():
        return dict(DEFAULT_SKILLS)

    try:
        payload = json.loads(SKILLS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SKILLS)

    if not isinstance(payload, dict):
        return dict(DEFAULT_SKILLS)

    normalized: dict[str, list[str]] = {}
    for category, items in payload.items():
        if not isinstance(category, str) or not isinstance(items, list):
            continue
        cleaned_items = [str(item).strip() for item in items if str(item).strip()]
        if cleaned_items:
            normalized[category] = cleaned_items

    return normalized or dict(DEFAULT_SKILLS)


def build_allowlist(state: ResumeTailorState) -> ResumeTailorState:
    skills_payload = _load_skills_config()
    flattened: list[str] = []
    seen: set[str] = set()
    for items in skills_payload.values():
        for skill in items:
            key = skill.lower()
            if key in seen:
                continue
            seen.add(key)
            flattened.append(skill)
    state["allowlist"] = flattened
    state["skills_catalog"] = skills_payload
    return state


def _normalize_keywords(items: list[str] | None) -> list[str]:
    return [item.strip() for item in (items or []) if item and str(item).strip()]


def _clean_unknown(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    if cleaned.lower() in {"unknown", "unavailable", "n/a", "na", "none", "null"}:
        return ""
    return cleaned


def _escape_latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    escaped = value
    for source, target in replacements.items():
        escaped = escaped.replace(source, target)
    return escaped


def _strip_latex_markup(value: str) -> str:
    text = value
    text = re.sub(r"(?m)^\s*%.*$", " ", text)
    text = text.replace(r"\&", "&")
    text = text.replace(r"\%", "%")
    text = text.replace(r"\_", "_")
    text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textit\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("%", " ")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_latex_items(text: str) -> list[str]:
    matches = re.findall(r"\\item\s*\{((?:[^{}]|\{[^{}]*\})*)\}", text, flags=re.S)
    items: list[str] = []
    for raw in matches:
        cleaned = _strip_latex_markup(raw)
        if cleaned:
            items.append(cleaned)
    return items


def _extract_summary_text(source_summary_tex: str) -> str:
    match = re.search(r"\\begin\{cvparagraph\}(.*?)\\end\{cvparagraph\}", source_summary_tex, flags=re.S)
    if not match:
        return ""
    return _strip_latex_markup(match.group(1))


def _job_keywords(job_packet: dict[str, Any]) -> list[str]:
    job = job_packet.get("job", {})
    must_have = _normalize_keywords(job.get("must_have"))
    nice_to_have = _normalize_keywords(job.get("nice_to_have"))
    title_tokens = re.findall(r"[A-Za-z][A-Za-z+#]{2,}", str(job.get("title") or ""))
    ignored_tokens = {"senior", "software", "engineer", "individual", "contributor", "professional"}
    title_tokens = [token for token in title_tokens if token.lower() not in ignored_tokens]
    merged = must_have + nice_to_have + title_tokens
    keywords: list[str] = []
    seen: set[str] = set()
    for item in merged:
        cleaned = _clean_unknown(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(cleaned)
    return keywords


def _parse_additional_prompt_terms(additional_prompt: str) -> list[str]:
    if not additional_prompt or "{skills}" in additional_prompt:
        return []
    parts = re.split(r"[,;]", additional_prompt)
    terms: list[str] = []
    for raw in parts:
        term = raw.strip()
        if not term:
            continue
        if len(term.split()) > 4:
            continue
        terms.append(term)
    return terms


def _parse_prompt_items(value: str) -> list[str]:
    if not value:
        return []
    parts = [item.strip() for item in value.split("||")]
    return [item for item in parts if item]


def _extract_personalprojects_priority_order(section_prompt: str) -> list[str]:
    match = re.search(r"(?i)priority\s*order\s*:\s*([^\n]+)", section_prompt or "")
    if match:
        parsed = _parse_prompt_items(match.group(1).strip())
        if parsed:
            return [item.lower() for item in parsed]
    return ["getkan-cv", "linux enthusiast", "mystic type-writer", "notesboard plus plus"]


def _normalize_category_skills(skills_catalog: dict[str, list[str]]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for category, skills in (skills_catalog or {}).items():
        cleaned = [str(skill).strip().lower() for skill in skills if str(skill).strip()]
        if cleaned:
            normalized[category] = cleaned
    return normalized


def _derive_category_boosts(
    job_packet: dict[str, Any],
    category_skills: dict[str, list[str]],
    keywords: list[str],
) -> dict[str, int]:
    job = job_packet.get("job", {})
    text_parts: list[str] = [
        str(job.get("title") or ""),
        str(job.get("description") or ""),
        " ".join(_normalize_keywords(job.get("must_have"))),
        " ".join(_normalize_keywords(job.get("nice_to_have"))),
        " ".join(_normalize_keywords(job.get("responsibilities"))),
        " ".join(keywords),
    ]
    corpus = " ".join(text_parts).lower()

    boosts: dict[str, int] = {}
    for category, skills in category_skills.items():
        match_count = 0
        for skill in skills:
            if _keyword_in_text(skill, corpus):
                match_count += 1
        if match_count > 0:
            boosts[category] = min(4, 1 + match_count)
    return boosts


def _keyword_in_text(keyword: str, text: str) -> bool:
    escaped = re.escape(keyword)
    if re.search(r"[^A-Za-z0-9]", keyword):
        return escaped.lower() in text.lower()
    pattern = rf"\b{escaped}\b"
    return re.search(pattern, text, flags=re.I) is not None


def _score_item(
    item: str,
    keywords: list[str],
    category_skills: dict[str, list[str]] | None = None,
    category_boosts: dict[str, int] | None = None,
) -> int:
    lowered = item.lower()
    score = 0
    for keyword in keywords:
        if _keyword_in_text(keyword, lowered):
            score += 3
    for booster in ["api", "backend", "frontend", "architecture", "testing", "cloud", "performance", "reliability", "mentored", "lead"]:
        if booster in lowered:
            score += 1

    if category_skills and category_boosts:
        for category, boost in category_boosts.items():
            if boost <= 0:
                continue
            skills = category_skills.get(category, [])
            if any(_keyword_in_text(skill, lowered) for skill in skills):
                score += boost * 2
    return score


def _compact_text(value: str, max_words: int) -> str:
    words = value.split()
    if len(words) <= max_words:
        return value

    shortened = " ".join(words[:max_words]).rstrip(" ,;:")
    if not shortened.endswith("."):
        shortened += "."
    return shortened


def _rewrite_item(item: str, keywords: list[str], additional_prompt: str, max_words: int = 30) -> str:
    cleaned = _strip_latex_markup(item)
    if not cleaned:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    cleaned = first_sentence or cleaned
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _compact_text(cleaned, max_words=max_words)
    if cleaned and not cleaned.endswith("."):
        cleaned += "."
    return cleaned


def _format_skill_list(skills: list[str]) -> str:
    if not skills:
        return ""
    if len(skills) == 1:
        return skills[0]
    if len(skills) == 2:
        return f"{skills[0]} and {skills[1]}"
    return f"{', '.join(skills[:-1])}, and {skills[-1]}"


def _tailor_items_in_text(
    text: str,
    keywords: list[str],
    limit: int | None = None,
    max_words: int = 30,
    category_skills: dict[str, list[str]] | None = None,
    category_boosts: dict[str, int] | None = None,
) -> str:
    item_pattern = re.compile(r"(?m)^(\s*)\\item\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
    matches = list(item_pattern.finditer(text))
    if not matches:
        return text

    scored = []
    for idx, match in enumerate(matches):
        raw_item = match.group(2)
        score = _score_item(
            _strip_latex_markup(raw_item),
            keywords,
            category_skills=category_skills,
            category_boosts=category_boosts,
        )
        scored.append((idx, score))

    keep_indices = [idx for idx, score in scored if score > 0]
    if not keep_indices:
        keep_indices = [max(scored, key=lambda row: row[1])[0]]

    if limit is not None and len(keep_indices) > limit:
        keep_indices = [idx for idx, _ in sorted(scored, key=lambda row: row[1], reverse=True)[:limit]]
        keep_indices.sort()

    keep_set = set(keep_indices)
    out_parts: list[str] = []
    cursor = 0

    for idx, match in enumerate(matches):
        out_parts.append(text[cursor:match.start()])
        if idx in keep_set:
            indent = match.group(1)
            rewritten = _rewrite_item(match.group(2), keywords, "", max_words=max_words)
            out_parts.append(f"{indent}\\item {{{_escape_latex(rewritten)}}}")
        cursor = match.end()

    out_parts.append(text[cursor:])
    rebuilt = "".join(out_parts)
    rebuilt = re.sub(r"\n[ \t]*\n+", "\n", rebuilt)
    return rebuilt


def _tailor_experience_module(
    source_experience_tex: str,
    keywords: list[str],
    cvitems_limit: int = 2,
    cvsubitems_limit: int = 4,
    max_words: int = 30,
    category_skills: dict[str, list[str]] | None = None,
    category_boosts: dict[str, int] | None = None,
) -> str:
    block_pattern = re.compile(
        r"\\begin\{(cvitems|cvsubitems)\}[^\n]*\n.*?\\end\{\1\}",
        flags=re.S,
    )

    rebuilt_parts: list[str] = []
    cursor = 0

    for match in block_pattern.finditer(source_experience_tex):
        rebuilt_parts.append(source_experience_tex[cursor:match.start()])
        env_name = match.group(1)
        block = match.group(0)
        limit = cvitems_limit if env_name == "cvitems" else cvsubitems_limit
        tailored_block = _tailor_items_in_text(
            block,
            keywords,
            limit=limit,
            max_words=max_words,
            category_skills=category_skills,
            category_boosts=category_boosts,
        )

        # Drop empty item environments to avoid vertical gaps in rendered output.
        if re.search(r"(?m)^\s*\\item\s*\{", tailored_block):
            rebuilt_parts.append(tailored_block)

        cursor = match.end()

    rebuilt_parts.append(source_experience_tex[cursor:])
    rebuilt = "".join(rebuilt_parts)
    rebuilt = re.sub(r"\n[ \t]*\n+", "\n", rebuilt)
    return rebuilt


def _project_priority_key(text: str) -> str | None:
    lowered = text.lower()
    if "getkan-cv" in lowered:
        return "getkan-cv"
    if "linux enthusiast" in lowered or "linxu enthusiast" in lowered:
        return "linux enthusiast"
    if "mystic type-writer" in lowered or "mystic type writer" in lowered:
        return "mystic type-writer"
    if "notesboard plus plus" in lowered:
        return "notesboard plus plus"
    return None


def _render_personalprojects_tex(
    selected_items: list[str],
    include_header: bool,
    include_ai_sentence: bool,
) -> str:
    header_text = "I take pride in programming as a craft and continuously strive to improve my skills with personal projects."
    if include_ai_sentence:
        header_text += " With the rapid advancements in AI, I have been particularly focused on experimenting with various AI tools."

    lines: list[str] = [
        "%-------------------------------------------------------------------------------",
        "%\tSECTION TITLE",
        "%-------------------------------------------------------------------------------",
        "\\cvsection{Personal Projects}",
        "%-------------------------------------------------------------------------------",
        "%\tCONTENT",
        "%-------------------------------------------------------------------------------",
        "\\begin{cventries}",
        "  %---------------------------------------------------------",
        "  \\cventry",
        "  {} % Affiliation/role",
        "  {} % Organization/group",
        "  {} % Location",
        "  {} % Date(s)",
        "  {",
        "    \\vspace{-10mm}",
    ]

    if include_header:
        lines.extend(
            [
                "    \\begin{cvitems}",
                f"      \\item {{{_escape_latex(header_text)}}}",
                "    \\end{cvitems}",
            ]
        )

    if selected_items:
        lines.append("    \\begin{cvsubitems}")
        for item in selected_items:
            lines.append(f"      \\item {{{_escape_latex(item)}}}")
        lines.append("    \\end{cvsubitems}")

    lines.extend(["  }", "\\end{cventries}"])
    return "\n".join(lines) + "\n"


def _tailor_personalprojects_module(
    source_personalprojects_tex: str,
    keywords: list[str],
    limit: int = 2,
    max_words: int = 26,
    priority_order: list[str] | None = None,
) -> str:
    _ = keywords  # Selection order is intentionally fixed and independent of job description.
    order = priority_order or ["getkan-cv", "linux enthusiast", "mystic type-writer", "notesboard plus plus"]
    order = [item.lower() for item in order]
    item_pattern = re.compile(r"\\item\s*\{((?:[^{}]|\{[^{}]*\})*)\}", flags=re.S)
    raw_items = item_pattern.findall(source_personalprojects_tex)

    normalized_by_key: dict[str, str] = {}
    for raw in raw_items:
        cleaned = _rewrite_item(raw, [], "", max_words=max_words)
        if not cleaned:
            continue
        key = _project_priority_key(cleaned)
        if key and key not in normalized_by_key:
            normalized_by_key[key] = cleaned

    capped_limit = max(0, limit)
    selected_keys = [key for key in order if key in normalized_by_key][:capped_limit]
    selected_items = [normalized_by_key[key] for key in selected_keys]

    if not selected_items:
        return _tailor_items_in_text(source_personalprojects_tex, [], limit=1, max_words=max_words)

    include_header = len(selected_items) > 1
    include_ai_sentence = "getkan-cv" in selected_keys
    return _render_personalprojects_tex(selected_items, include_header, include_ai_sentence)


def _tailor_aboutme_module(
    source_aboutme_tex: str,
    keywords: list[str],
    limit: int = 1,
    max_words: int = 20,
    required_items: list[str] | None = None,
    category_skills: dict[str, list[str]] | None = None,
    category_boosts: dict[str, int] | None = None,
) -> str:
    item_pattern = re.compile(r"(?m)^(\s*)\\item\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
    matches = list(item_pattern.finditer(source_aboutme_tex))
    if not matches:
        return source_aboutme_tex

    required_lower = [item.lower() for item in (required_items or [])]

    scored: list[tuple[int, int, str]] = []
    required_indices: set[int] = set()
    for idx, match in enumerate(matches):
        cleaned_raw = _strip_latex_markup(match.group(2))
        rewritten = _rewrite_item(match.group(2), keywords, "", max_words=max_words)
        scored.append(
            (
                idx,
                _score_item(
                    cleaned_raw,
                    keywords,
                    category_skills=category_skills,
                    category_boosts=category_boosts,
                ),
                rewritten,
            )
        )
        if any(required and required in cleaned_raw.lower() for required in required_lower):
            required_indices.add(idx)

    keep_indices = set(required_indices)
    remaining_slots = max(0, limit - len(keep_indices))
    if remaining_slots > 0:
        extra = [idx for idx, score, _ in sorted(scored, key=lambda row: row[1], reverse=True) if idx not in keep_indices]
        keep_indices.update(extra[:remaining_slots])

    if not keep_indices:
        keep_indices.add(max(scored, key=lambda row: row[1])[0])

    out_parts: list[str] = []
    cursor = 0
    for idx, match in enumerate(matches):
        out_parts.append(source_aboutme_tex[cursor:match.start()])
        if idx in keep_indices:
            indent = match.group(1)
            rewritten = _rewrite_item(match.group(2), keywords, "", max_words=max_words)
            out_parts.append(f"{indent}\\item {{{_escape_latex(rewritten)}}}")
        cursor = match.end()

    out_parts.append(source_aboutme_tex[cursor:])
    rebuilt = "".join(out_parts)
    rebuilt = re.sub(r"\n\s*\\begin\{cvitems\}[^\n]*\n\s*\\end\{cvitems\}\n", "\n", rebuilt)
    rebuilt = re.sub(r"\n[ \t]*\n+", "\n", rebuilt)
    return rebuilt


def _build_summary_text(
    source_summary: str,
    source_experience_text: str,
    keywords: list[str],
    job_packet: dict[str, Any],
    max_sentences: int = 2,
) -> str:
    summary = source_summary.strip()
    if not summary:
        summary = "Senior software engineer with proven delivery experience across the software lifecycle."

    experience_text = source_experience_text.lower()
    relevant_techs = [kw for kw in keywords if _keyword_in_text(kw, experience_text)]
    tech_phrase = _format_skill_list(relevant_techs[:4])

    if tech_phrase:
        summary = re.sub(
            r"(?i)(beginning\s+with\s+a\s+focus\s+on\s+frontend\s+development,\s*)(.*?)(\s*,\s*and\s*transitioning)",
            lambda m: f"{m.group(1)}{tech_phrase}{m.group(3)}",
            summary,
        )

    sentence_parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", summary) if part.strip()]
    compact_summary = " ".join(sentence_parts[: max(1, max_sentences)])
    return re.sub(r"\s+", " ", compact_summary).strip()


def _render_summary_tex(summary_text: str) -> str:
    return f"\\begin{{cvparagraph}}\n    {_escape_latex(summary_text)}\n\\end{{cvparagraph}}"


def _tailor_modules_deterministically(state: ResumeTailorState) -> ResumeTailorState:
    job_packet = state.get("job_packet", {})
    source_modules = state.get("source_modules", {})
    prompts = state.get("prompts", dict(DEFAULT_PROMPTS))
    allowlist = state.get("allowlist", [])
    skills_catalog = state.get("skills_catalog", dict(DEFAULT_SKILLS))
    additional_prompt = prompts.get("additional_prompt", DEFAULT_PROMPTS["additional_prompt"])
    profile = state.get("layout_profile", {})
    experience_cvitems_limit = int(profile.get("experience_cvitems_limit", 2))
    experience_cvsubitems_limit = int(profile.get("experience_cvsubitems_limit", 4))
    personalprojects_limit = int(profile.get("personalprojects_limit", 2))
    aboutme_limit = int(profile.get("aboutme_limit", 1))
    item_word_limit = int(profile.get("item_word_limit", 30))
    summary_sentences = int(profile.get("summary_sentences", 2))
    personalprojects_section_prompt = prompts.get(
        "personalprojects_section_prompt", DEFAULT_PROMPTS["personalprojects_section_prompt"]
    )
    personalprojects_priority_order = _extract_personalprojects_priority_order(personalprojects_section_prompt)
    aboutme_required_items = _parse_prompt_items(
        prompts.get("aboutme_required_items", DEFAULT_PROMPTS["aboutme_required_items"])
    )

    keywords = _job_keywords(job_packet)
    category_skills = _normalize_category_skills(skills_catalog)
    manual_terms = _parse_additional_prompt_terms(additional_prompt)
    prioritized_keywords = manual_terms + [keyword for keyword in keywords if keyword.lower() in {item.lower() for item in allowlist}] + [
        keyword for keyword in keywords if keyword.lower() not in {item.lower() for item in allowlist}
    ]
    dedup_keywords: list[str] = []
    seen: set[str] = set()
    for keyword in prioritized_keywords:
        key = keyword.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup_keywords.append(keyword)

    category_boosts = _derive_category_boosts(job_packet, category_skills, dedup_keywords)

    source_experience_text = source_modules.get("experience.tex", "")
    source_personalprojects_text = source_modules.get("personalprojects.tex", "")
    source_aboutme_text = source_modules.get("aboutme.tex", "")
    source_summary_text = _extract_summary_text(source_modules.get("summary.tex", ""))

    tailored_experience = _tailor_experience_module(
        source_experience_text,
        dedup_keywords,
        cvitems_limit=experience_cvitems_limit,
        cvsubitems_limit=experience_cvsubitems_limit,
        max_words=item_word_limit,
        category_skills=category_skills,
        category_boosts=category_boosts,
    )
    tailored_personalprojects = _tailor_personalprojects_module(
        source_personalprojects_text,
        dedup_keywords,
        limit=personalprojects_limit,
        max_words=max(16, item_word_limit - 4),
        priority_order=personalprojects_priority_order,
    )

    tailored_aboutme = _tailor_aboutme_module(
        source_aboutme_text,
        dedup_keywords,
        limit=aboutme_limit,
        max_words=max(14, item_word_limit - 8),
        required_items=aboutme_required_items,
        category_skills=category_skills,
        category_boosts=category_boosts,
    )
    summary_text = _build_summary_text(
        source_summary_text,
        source_experience_text,
        dedup_keywords,
        job_packet,
        max_sentences=summary_sentences,
    )

    state["model_output"] = {
        "tailored_modules": {
            "summary.tex": _render_summary_tex(summary_text),
            "experience.tex": tailored_experience,
            "personalprojects.tex": tailored_personalprojects,
            "aboutme.tex": tailored_aboutme,
        },
        "recommendations": {
            "positioning": ["Prioritize bullets showing ownership, reliability, and cross-functional delivery impact."],
            "project_suggestions": [f"Highlight projects touching {', '.join(dedup_keywords[:3]) if dedup_keywords else 'core software delivery'}"],
            "gap_analysis": ["Add quantified outcomes (latency, uptime, delivery speed, or cost savings) where possible."],
        },
    }
    return state



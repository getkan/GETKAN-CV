from __future__ import annotations

from typing import Any

from src.advisor.common import normalize_text


def _unique_skills(skills: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        cleaned = normalize_text(skill)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


def _count_skill_mentions(skill: str, packets: list[dict[str, Any]]) -> dict[str, int]:
    normalized_skill = normalize_text(skill).lower()
    must_have_count = 0
    good_to_have_count = 0

    for payload in packets:
        job = payload.get("job", {}) if isinstance(payload, dict) else {}
        must_have_items = {normalize_text(str(item)).lower() for item in (job.get("must_have") or []) if normalize_text(str(item))}
        nice_to_have_items = {normalize_text(str(item)).lower() for item in (job.get("nice_to_have") or []) if normalize_text(str(item))}

        if normalized_skill in must_have_items:
            must_have_count += 1
        if normalized_skill in nice_to_have_items:
            good_to_have_count += 1

    return {
        "skill": normalize_text(skill),
        "must_haves": must_have_count,
        "good_to_haves": good_to_have_count,
    }


def _skill_table_lines(skill_rows: list[dict[str, int]]) -> list[str]:
    lines = ["## Skills", "", "| Skill | Must Haves | Good To Haves |", "| --- | ---: | ---: |"]
    if not skill_rows:
        lines.append("| None identified | 0 | 0 |")
        return lines

    for row in skill_rows:
        if row["must_haves"] == 0:
            continue

        lines.append(f"| {row['skill']} | {row['must_haves']} | {row['good_to_haves']} |")
    return lines


def render_recommend_skills_section(*, skill_rows: list[dict[str, int]], skills: list[str] | None = None) -> dict[str, Any]:
    return {
        "heading": "## Skills",
        "lines": _skill_table_lines(skill_rows),
        "skills": skills or [row["skill"] for row in skill_rows],
        "skill_rows": skill_rows,
    }


def parse_skill_rows_from_table_lines(lines: list[str]) -> list[dict[str, int]]:
    skill_rows: list[dict[str, int]] = []
    for line in lines:
        if not line.startswith("| ") or line.startswith("| Skill") or line.startswith("| ---") or line.startswith("| None identified"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != 3:
            continue
        skill_rows.append(
            {
                "skill": parts[0],
                "must_haves": int(parts[1]),
                "good_to_haves": int(parts[2]),
            }
        )
    return skill_rows

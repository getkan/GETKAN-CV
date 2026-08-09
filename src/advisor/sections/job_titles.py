from __future__ import annotations

from typing import Any


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

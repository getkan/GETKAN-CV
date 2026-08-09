from __future__ import annotations

from typing import Any


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

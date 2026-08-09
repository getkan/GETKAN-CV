from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.config.settings import COMPATIBILITY_BORDERLINE_HIGH, COMPATIBILITY_BORDERLINE_LOW, RESUME_MODULE_NAMES

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.json"


def _load_scorer_prompts() -> dict[str, str]:
    defaults = {
        "compatibility_scorer_system_prompt": (
            "You are a career compatibility assessor. Given a resume summary and a job's required/preferred skills, "
            "rate the candidate's compatibility on a scale of 1-10. Consider transferable skills, seniority, and "
            "related technologies — not just exact keyword matches. Return only valid JSON with a single key "
            "'compatibility_score' (integer 1-10)."
        ),
        "compatibility_scorer_user_prompt_template": (
            "Resume summary:\n{resume_summary}\n\n"
            "Job title: {title}\n"
            "Job domain: {domain}\n"
            "Must-have skills: {must_have}\n"
            "Nice-to-have skills: {nice_to_have}\n\n"
            "Rate compatibility 1-10. Consider that experience with one framework/language often transfers to another "
            "(e.g. Vue.js experience is relevant to React roles). Seniority and leadership experience also matter."
        ),
    }
    if not _PROMPTS_PATH.exists():
        return defaults
    try:
        payload = json.loads(_PROMPTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    for key, default_value in defaults.items():
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            defaults[key] = value
    return defaults


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _resume_summary() -> str:
    """Build a concise resume summary for the LLM prompt."""
    repo_root = Path(__file__).resolve().parents[2]
    modules_dir = repo_root / "resume" / "modules"
    parts: list[str] = []
    for name in RESUME_MODULE_NAMES:
        path = modules_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)[:3000]


def _llm_adjust_score(
    baseline_score: int,
    job_packet: dict[str, Any],
    model_name: str | None = None,
) -> int:
    """Call OpenRouter to adjust a borderline baseline score."""
    if requests is None:
        return baseline_score

    _load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return baseline_score

    job = job_packet.get("job", {}) if isinstance(job_packet, dict) else {}
    model = model_name or os.getenv("OPENROUTER_MODEL_ADVISOR") or os.getenv("OPENROUTER_MODEL") or "openai/gpt-4o-mini"
    prompts = _load_scorer_prompts()

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/GETKAN-CV",
                "X-Title": "GETKAN-CV Compatibility Scorer",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompts["compatibility_scorer_system_prompt"]},
                    {
                        "role": "user",
                        "content": prompts["compatibility_scorer_user_prompt_template"].format(
                            resume_summary=_resume_summary(),
                            title=str(job.get("title") or "unknown"),
                            domain=str(job.get("domain") or "unknown"),
                            must_have=", ".join(str(item) for item in (job.get("must_have") or [])),
                            nice_to_have=", ".join(str(item) for item in (job.get("nice_to_have") or [])),
                        ),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "compatibility_score",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "compatibility_score": {"type": "integer", "minimum": 1, "maximum": 10},
                            },
                            "required": ["compatibility_score"],
                            "additionalProperties": False,
                        },
                    },
                },
                "temperature": 0.1,
            },
            timeout=30,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]["content"]
        payload = json.loads(message)
        llm_score = int(payload.get("compatibility_score", baseline_score))
        avg_score = (baseline_score + llm_score) / 2
        return max(1, min(10, int(round(avg_score))))
    except Exception:
        return baseline_score


def _contains_keyword(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword)
    if re.search(r"[^A-Za-z0-9]", keyword):
        return escaped.lower() in text.lower()
    return re.search(rf"\b{escaped}\b", text, flags=re.I) is not None


def _resume_match_corpus() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    modules_dir = repo_root / "resume" / "modules"
    parts: list[str] = []
    for name in RESUME_MODULE_NAMES:
        path = modules_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))

    skills_path = modules_dir / "skills.json"
    if skills_path.exists():
        try:
            payload = json.loads(skills_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for values in payload.values():
                    if isinstance(values, list):
                        parts.append(" ".join(str(item) for item in values))
        except (json.JSONDecodeError, OSError):
            pass
    return "\n".join(parts).lower()


def _known_skill_terms() -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    skills_path = repo_root / "resume" / "modules" / "skills.json"
    terms: list[str] = []
    if skills_path.exists():
        try:
            payload = json.loads(skills_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for values in payload.values():
                    if isinstance(values, list):
                        for item in values:
                            cleaned = str(item).strip().lower()
                            if cleaned:
                                terms.append(cleaned)
        except (json.JSONDecodeError, OSError):
            pass

    # Add common role terms that frequently appear inside long requirement sentences.
    terms.extend(
        [
            "api",
            "json:api",
            "backend",
            "frontend",
            "distributed systems",
            "microservices",
            "mysql",
            "postgresql",
            "redis",
            "observability",
            "opentelemetry",
            "ci/cd",
            "websockets",
            "kubernetes",
            "docker",
            "go",
            "python",
            "php",
            "laravel",
            "react",
            "vue",
            "typescript",
            "javascript",
        ]
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _extract_requirement_terms(requirement: str, known_terms: list[str]) -> list[str]:
    text = (requirement or "").strip().lower()
    if not text:
        return []

    candidates: list[str] = []

    # Skill-aware extraction first so multiword technologies are preserved.
    for term in known_terms:
        if _contains_keyword(text, term):
            candidates.append(term)

    # Split long requirements into smaller chunks.
    chunked = re.split(r"[,;/]|\band\b|\bor\b|\bwith\b|\bsuch as\b|\bincluding\b|\blike\b", text)
    for chunk in chunked:
        cleaned = re.sub(r"\s+", " ", chunk).strip(" .:-")
        if len(cleaned) < 3:
            continue
        if len(cleaned.split()) > 8:
            continue
        candidates.append(cleaned)

    # Single-token fallback for common terms/acronyms.
    for token in re.findall(r"[a-z0-9+#\.:-]{2,}", text):
        if token in {"years", "experience", "strong", "skills", "ability", "understanding"}:
            continue
        if token.isdigit():
            continue
        candidates.append(token)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _requirement_match_score(corpus: str, requirement: str, known_terms: list[str]) -> float:
    req = (requirement or "").strip().lower()
    if not req:
        return 0.0

    # Full phrase match gets full credit.
    if _contains_keyword(corpus, req):
        return 1.0

    terms = _extract_requirement_terms(req, known_terms)
    if not terms:
        return 0.0

    matches = sum(1 for term in terms if _contains_keyword(corpus, term))
    ratio = matches / len(terms)
    return min(0.95, ratio)


def calculate_compatibility_score(job_packet: dict[str, Any]) -> int:
    job = job_packet.get("job", {}) if isinstance(job_packet, dict) else {}
    must_have = [str(item).strip() for item in (job.get("must_have") or []) if str(item).strip()]
    nice_to_have = [str(item).strip() for item in (job.get("nice_to_have") or []) if str(item).strip()]
    title = str(job.get("title") or "")
    domain = str(job.get("domain") or "")

    corpus = _resume_match_corpus()
    known_terms = _known_skill_terms()

    must_ratio = 0.0
    if must_have:
        must_scores = [_requirement_match_score(corpus, item, known_terms) for item in must_have]
        must_ratio = sum(must_scores) / len(must_scores)

    nice_ratio = 0.0
    if nice_to_have:
        nice_scores = [_requirement_match_score(corpus, item, known_terms) for item in nice_to_have]
        nice_ratio = sum(nice_scores) / len(nice_scores)

    title_tokens = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z+#]{2,}", f"{title} {domain}")
        if token.lower() not in {"senior", "software", "engineer"}
    ]
    title_ratio = 0.0
    if title_tokens:
        title_matches = sum(1 for token in title_tokens if _contains_keyword(corpus, token.lower()))
        title_ratio = title_matches / len(title_tokens)

    weighted_ratio = (must_ratio * 0.7) + (nice_ratio * 0.2) + (title_ratio * 0.1)
    if not must_have and not nice_to_have and not title_tokens:
        weighted_ratio = 0.45

    score = int(round(1 + (weighted_ratio * 9)))
    return max(1, min(10, score))


def calculate_hybrid_compatibility_score(
    job_packet: dict[str, Any],
    model_name: str | None = None,
) -> int:
    """Keyword baseline + optional LLM adjustment for borderline scores.

    The deterministic keyword score is always computed first. If it falls in
    the borderline range (based on settings), an LLM call refines it by considering
    transferable skills and seniority. Otherwise the keyword score is returned
    as-is (no API cost for clear-cut cases).
    """

    if not job_packet or job_packet.get("metadata", {}).get("validation_errors", []):
        return None  # Invalid job packet, cannot compute score.

    baseline = calculate_compatibility_score(job_packet)
    if COMPATIBILITY_BORDERLINE_LOW <= baseline <= COMPATIBILITY_BORDERLINE_HIGH:
        return _llm_adjust_score(baseline, job_packet, model_name=model_name)
    return baseline

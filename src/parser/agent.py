from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .skills import normalize_skill_items as _normalize_skill_items

try:
    import requests
except ImportError:  # pragma: no cover - exercised in minimal environments
    requests = None


class JobParserState(TypedDict):
    source: dict[str, Any]
    raw_listing_text: str
    extracted_facts: dict[str, Any]
    normalized_packet: dict[str, Any]
    confidence: float


PROMPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "prompts" / "parser" / "prompts.json"
DEFAULT_PARSER_PROMPTS: dict[str, str] = {
    "job_parser_system_prompt": (
        "You extract structured job posting data. Return valid JSON with keys: "
        "title, company, location, employment_type, description, must_have, "
        "nice_to_have, responsibilities, domain."
    ),
    "job_parser_user_prompt_template": (
        "Parse the following job listing into JSON. "
        "Use empty arrays for missing skill lists and unknown for missing values.\n\n"
        "{listing_text}"
    ),
}


def _load_parser_prompts() -> dict[str, str]:
    prompts = dict(DEFAULT_PARSER_PROMPTS)
    if not PROMPT_CONFIG_PATH.exists():
        return prompts

    try:
        payload = json.loads(PROMPT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return prompts

    if not isinstance(payload, dict):
        return prompts

    for key, default_value in DEFAULT_PARSER_PROMPTS.items():
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            prompts[key] = value
        else:
            prompts[key] = default_value
    return prompts


def fetch_or_load_listing(state: JobParserState) -> JobParserState:
    source = state.get("source", {})
    listing_text = (source.get("listing_text") or "").strip()

    if listing_text:
        state["raw_listing_text"] = listing_text
        return state

    job_url = source.get("job_url")
    if not job_url:
        state["raw_listing_text"] = ""
        return state

    try:
        request = Request(job_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8", errors="ignore")

        # Keep original HTML for structured extraction fallback.
        source["listing_html"] = payload
        state["source"] = source

        cleaned = re.sub(r"<script.*?</script>", " ", payload, flags=re.S | re.I)
        cleaned = re.sub(r"<style.*?</style>", " ", cleaned, flags=re.S | re.I)
        cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
        cleaned = unescape(cleaned)
        cleaned = re.sub(r"\s+", "\n", cleaned).strip()
        state["raw_listing_text"] = cleaned
    except (HTTPError, URLError, ValueError):
        state["raw_listing_text"] = ""

    return state


def _clean_unknown(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if cleaned.lower() in {"unknown", "unavailable", "n/a", "na", "none", "null"}:
        return ""
    return cleaned




def _clean_list(items: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        cleaned = _clean_unknown(str(raw))
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(p|div|ul|li|span|strong|b|em|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<(p|div|ul|li|span|strong|b|em|h[1-6])[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join([line for line in lines if line])


def _extract_section(description_html: str, heading: str) -> str:
    pattern = rf"(?is)<strong>\s*{re.escape(heading)}\s*</strong>\s*<br\s*/?>\s*<br\s*/?>(.*?)(?=<br\s*/?>\s*<strong>|$)"
    match = re.search(pattern, description_html)
    if not match:
        return ""
    return _strip_html(match.group(1)).strip()


def _normalize_employment_type(value: str) -> str:
    cleaned = _clean_unknown(value)
    if not cleaned:
        return ""
    normalized = cleaned.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.title()


def _load_dotenv(env_path: str | Path | None = None) -> None:
    path = Path(env_path) if env_path else Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _extract_json_payload(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content

    if not isinstance(content, str):
        return None

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_job_with_openrouter(listing_text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    model = os.getenv("OPENROUTER_MODEL_PARSER") or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    prompts = _load_parser_prompts()
    system_prompt = prompts["job_parser_system_prompt"]
    user_prompt = prompts["job_parser_user_prompt_template"].format(listing_text=listing_text)

    if requests is None:
        raise RuntimeError("requests is required for job parsing")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "job_packet",
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "location": {"type": "string"},
                        "employment_type": {"type": "string"},
                        "description": {"type": "string"},
                        "must_have": {"type": "array", "items": {"type": "string"}},
                        "nice_to_have": {"type": "array", "items": {"type": "string"}},
                        "responsibilities": {"type": "array", "items": {"type": "string"}},
                        "domain": {"type": "string"},
                    },
                    "required": ["title", "company", "description"],
                },
            },
        },
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/GETKAN-CV",
                "X-Title": "GETKAN-CV Job Parser",
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_payload(message)
        if not parsed:
            raise RuntimeError("OpenRouter did not return valid JSON")
        return parsed
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("OpenRouter request failed") from exc


def _extract_jsonld_job_postings(text: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for match in re.finditer(r"<script[^>]*type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", text, flags=re.S | re.I):
        snippet = match.group(1)
        try:
            payload = json.loads(snippet)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            if payload.get("@type") == "JobPosting":
                postings.append(payload)
            elif isinstance(payload.get("@graph"), list):
                for item in payload["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        postings.append(item)
    return postings


def _heuristic_fallback(text: str) -> dict[str, Any]:
    lowered = text.lower()
    title = ""
    company = ""
    location = ""
    description = ""
    must_have: list[str] = []
    nice_to_have: list[str] = []
    responsibilities: list[str] = []
    employment_type = ""

    job_postings = _extract_jsonld_job_postings(text)
    if job_postings:
        posting = job_postings[0]
        title = (posting.get("title") or "").strip() or title
        organization = posting.get("hiringOrganization") or {}
        company = (organization.get("name") or posting.get("company") or "").strip()
        location_payload = posting.get("jobLocation") or posting.get("jobLocationType") or ""
        if isinstance(location_payload, dict):
            address = location_payload.get("address") or {}
            location_tuple = (
                address.get("addressCountry")
                or address.get("addressLocality")
                or address.get("addressRegion")
                or location_payload.get("name")
                or ""
            )
            location = _clean_unknown(str(location_tuple))
        elif isinstance(location_payload, str):
            location = _clean_unknown(location_payload)

        employment_type = _normalize_employment_type(str(posting.get("employmentType") or ""))

        description_html = posting.get("description") or ""
        overview_section = _extract_section(description_html, "Overview")
        about_section = _extract_section(description_html, "About GitHub")
        if overview_section and about_section:
            description = f"{about_section}\n\n{overview_section}"
        elif overview_section:
            description = overview_section
        elif about_section:
            description = about_section
        else:
            description = _strip_html(description_html)

        if isinstance(posting.get("skills"), list):
            for skill in posting["skills"]:
                if isinstance(skill, str):
                    must_have.append(skill)

        if isinstance(posting.get("qualifications"), list):
            for qualification in posting["qualifications"]:
                if isinstance(qualification, str):
                    must_have.append(qualification)

        if not must_have:
            qualifications = _extract_section(description_html, "Qualifications")
            qualifications_lower = qualifications.lower()
            for keyword in [
                "python",
                "go",
                "rust",
                "java",
                "javascript",
                "react",
                "azure",
                "cloud",
                "c++",
                "c#",
                "ruby",
            ]:
                if keyword in qualifications_lower:
                    must_have.append("Azure" if keyword == "azure" else keyword.upper() if keyword in {"c++", "c#"} else keyword.title())

        if isinstance(posting.get("responsibilities"), list):
            responsibilities = [item for item in posting.get("responsibilities") if isinstance(item, str)]
        elif isinstance(posting.get("responsibilities"), str):
            responsibilities_html = posting.get("responsibilities") or ""
            responsibilities = []
            for bullet in re.findall(r"<li[^>]*>(.*?)</li>", responsibilities_html, flags=re.S | re.I):
                cleaned = re.sub(r"<[^>]+>", " ", bullet)
                cleaned = re.sub(r"&nbsp;", " ", cleaned)
                cleaned = unescape(cleaned)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    responsibilities.append(cleaned)

            if not responsibilities:
                cleaned = re.sub(r"<[^>]+>", " ", responsibilities_html)
                cleaned = re.sub(r"&nbsp;", " ", cleaned)
                cleaned = unescape(cleaned)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    responsibilities = [cleaned]

        if not responsibilities and description_html:
            cleaned_description = re.sub(r"<br\s*/?>", "\n", description_html, flags=re.I)
            cleaned_description = re.sub(r"</(p|div|ul|li|span|strong|b|em)>", "\n", cleaned_description, flags=re.I)
            cleaned_description = re.sub(r"<(p|div|ul|li|span|strong|b|em)[^>]*>", " ", cleaned_description, flags=re.I)
            cleaned_description = re.sub(r"&nbsp;", " ", cleaned_description)
            cleaned_description = unescape(cleaned_description)
            cleaned_description = re.sub(r"\s+", " ", cleaned_description).strip()
            lines = [line.strip() for line in cleaned_description.split("\n") if line.strip()]
            if lines:
                responsibilities = lines[:8]

    title_patterns = [
        r"(?im)^\s*(?:title|role|position)\s*[:\-]\s*([A-Za-z][A-Za-z0-9 .,&/()\-]{2,80})",
        r"(?im)^\s*([A-Za-z][A-Za-z0-9 .,&/()\-]{2,80})\s*(?:at|for|with)\s+[A-Za-z][A-Za-z0-9 .,&/()\-]{2,30}$",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, text)
        if match and not title:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            break

    if not title:
        for pattern in [r"(?i)title[^\n]{0,40}([A-Za-z][A-Za-z0-9 .,&/()-]{2,80})", r"(?i)job[^\n]{0,40}([A-Za-z][A-Za-z0-9 .,&/()-]{2,80})"]:
            match = re.search(pattern, text)
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()
                break

    if not title:
        title = "Unknown"

    if not company and "github" in lowered:
        company = "GitHub"
    if not location and "united states" in lowered:
        location = "United States"

    if not employment_type:
        employment_match = re.search(r"(?im)employment\s*type\s*[:\-]\s*([^\n]{2,60})", text)
        if employment_match:
            employment_type = _normalize_employment_type(employment_match.group(1))

    if not employment_type and "full time" in lowered:
        employment_type = "Full Time"

    if not description:
        description_match = re.search(r"(?is)(?:about|summary|description)[^\n]{0,200}([A-Za-z][^\n]{20,220})", text)
        if description_match:
            description = re.sub(r"\s+", " ", description_match.group(1)).strip()

    if not description:
        description = ""

    if not must_have:
        for keyword in ["python", "java", "javascript", "typescript", "react", "aws", "kubernetes", "docker", "terraform", "graphql", "postgres", "redis", "distributed systems"]:
            if keyword in lowered:
                must_have.append(keyword.title() if keyword != "aws" else "AWS")

    if not nice_to_have:
        for keyword in ["go", "rust", "machine learning", "ai", "microservices", "linux", "ci/cd", "observability"]:
            if keyword in lowered:
                nice_to_have.append(keyword.title() if keyword != "ci/cd" else "CI/CD")

    if not responsibilities and ("responsibilities" in lowered or "what you will do" in lowered):
        responsibilities.append("Own delivery of core software features")

    return {
        "title": _clean_unknown(title),
        "company": _clean_unknown(company),
        "location": _clean_unknown(location),
        "employment_type": employment_type,
        "description": _clean_unknown(description),
        "must_have": _normalize_skill_items(must_have),
        "nice_to_have": _normalize_skill_items(nice_to_have),
        "responsibilities": _clean_list(responsibilities),
        "domain": "",
    }


def extract_facts(state: JobParserState) -> JobParserState:
    text = (state.get("raw_listing_text") or "").strip()
    if not text:
        state["extracted_facts"] = {}
        return state

    source = state.get("source") or {}
    html_text = (source.get("listing_html") or "").strip()

    try:
        payload = _parse_job_with_openrouter(text, state.get("source"))
    except RuntimeError:
        payload = {}

    fallback_payload = _heuristic_fallback(html_text or text)
    def _pick_value(primary: Any, fallback: Any) -> Any:
        def _is_placeholder(value: Any) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                stripped = value.strip()
                return not stripped or stripped.lower() == "unknown"
            return value in (None, "", [], {})

        if not _is_placeholder(primary):
            return primary

        if not _is_placeholder(fallback):
            return fallback

        return primary or fallback or ""

    merged_payload = {
        "title": _pick_value(payload.get("title"), fallback_payload.get("title")),
        "company": _pick_value(payload.get("company"), fallback_payload.get("company")),
        "location": _pick_value(payload.get("location"), fallback_payload.get("location")),
        "employment_type": _pick_value(payload.get("employment_type"), fallback_payload.get("employment_type")),
        "description": _pick_value(payload.get("description"), fallback_payload.get("description")),
        "must_have": (payload.get("must_have") or fallback_payload.get("must_have") or []),
        "nice_to_have": (payload.get("nice_to_have") or fallback_payload.get("nice_to_have") or []),
        "responsibilities": (payload.get("responsibilities") or fallback_payload.get("responsibilities") or []),
        "domain": _pick_value(payload.get("domain"), fallback_payload.get("domain")),
    }

    state["extracted_facts"] = {
        "title": _clean_unknown(str(merged_payload.get("title") or "")),
        "company": _clean_unknown(str(merged_payload.get("company") or "")),
        "location": _clean_unknown(str(merged_payload.get("location") or "")),
        "employment_type": _normalize_employment_type(str(merged_payload.get("employment_type") or "")),
        "description": _clean_unknown(str(merged_payload.get("description") or "")),
        "must_have": _normalize_skill_items(merged_payload.get("must_have") or []),
        "nice_to_have": _normalize_skill_items(merged_payload.get("nice_to_have") or []),
        "responsibilities": _clean_list(merged_payload.get("responsibilities") or []),
        "domain": _clean_unknown(str(merged_payload.get("domain") or "")),
    }
    return state


def normalize_packet(state: JobParserState) -> JobParserState:
    if not state.get("extracted_facts"):
        extract_facts(state)

    extracted = state.get("extracted_facts", {})
    job = {
        "title": extracted.get("title") or "",
        "company": extracted.get("company") or "",
        "location": extracted.get("location") or "",
        "employment_type": extracted.get("employment_type") or "",
        "description": extracted.get("description") or "",
        "must_have": extracted.get("must_have") or [],
        "nice_to_have": extracted.get("nice_to_have") or [],
        "responsibilities": extracted.get("responsibilities") or [],
        "domain": extracted.get("domain") or "",
    }

    confidence = 0.0
    if job["title"]:
        confidence += 0.3
    if job["company"]:
        confidence += 0.2
    if job["location"]:
        confidence += 0.1
    if job["description"]:
        confidence += 0.2
    if job["must_have"] or job["nice_to_have"]:
        confidence += 0.1
    if job["responsibilities"]:
        confidence += 0.1

    state["normalized_packet"] = {
        "job": job,
        "metadata": {
            "source_url": (state.get("source") or {}).get("job_url", ""),
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "confidence": round(min(confidence, 1.0), 2),
            "field_attribution": {},
        },
    }
    state["confidence"] = state["normalized_packet"]["metadata"]["confidence"]
    return state


def validate_packet(state: JobParserState) -> JobParserState:
    if not state.get("normalized_packet"):
        normalize_packet(state)

    job = state["normalized_packet"].get("job", {})
    metadata = state["normalized_packet"].setdefault("metadata", {})
    validation_errors: list[str] = []

    if not job.get("title"):
        validation_errors.append("Missing job title")
    if not job.get("company"):
        validation_errors.append("Missing company")
    if not job.get("description"):
        validation_errors.append("Missing description")

    if validation_errors:
        metadata["validation_errors"] = validation_errors
        state["confidence"] = max(0.0, state["confidence"] - 0.1)
    else:
        metadata["validation_errors"] = []

    return state


def handoff_to_tailor(state: JobParserState, output_dir: str | Path | None = None) -> dict[str, Any]:
    if not state.get("normalized_packet"):
        normalize_packet(state)
        validate_packet(state)

    destination = Path(output_dir or "output/tailored/default")
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / "job_packet.json"
    output_path.write_text(json.dumps(state["normalized_packet"], indent=2), encoding="utf-8")

    return {
        "output_path": str(output_path),
        "job_packet": state["normalized_packet"],
    }
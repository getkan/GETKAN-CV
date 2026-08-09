from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser.agent import JobParserState, extract_facts, fetch_or_load_listing, handoff_to_tailor, normalize_packet, validate_packet, calculate_compatibility_score
from src.advisor.agent import generate_job_hunt_recommendations
from src.tailor.agent import build_tailored_payload, recompile_existing_output, render_env_placeholders
from src.cli_parser import build_parser


ROLE_DEFAULT_MODELS: dict[str, str] = {
    "PARSER": "openai/gpt-4o-mini",
    "TAILOR": "anthropic/claude-3.7-sonnet",
    "ADVISOR": "openai/gpt-4.1-mini",
}


def load_listing_from_file(file_path: Optional[str]) -> str:
    if not file_path:
        return ""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    return path.read_text(encoding="utf-8")


def load_urls_from_file(list_file_path: str) -> list[str]:
    path = Path(list_file_path)
    if not path.exists():
        raise FileNotFoundError(f"URL list file not found: {list_file_path}")
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    if not urls:
        raise ValueError("URL list file is empty")
    return urls


def _load_dotenv() -> None:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _resolve_model_for_role(role: str, cli_override: Optional[str]) -> Optional[str]:
    if cli_override:
        return cli_override

    _load_dotenv()
    role_key = f"OPENROUTER_MODEL_{role.upper()}"
    return os.getenv(role_key) or os.getenv("OPENROUTER_MODEL") or ROLE_DEFAULT_MODELS.get(role.upper())


def append_source_log(job_name: str, file_path: Optional[str], job_url: Optional[str], compatibility_score: int, model_name: Optional[str] = None) -> str:
    log_dir = Path.cwd() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "source_history.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_name": job_name,
        "url": job_url or "",
        "file": str(Path(file_path).resolve()) if file_path else "",
        "compatibility_score": compatibility_score,
        "model_name": model_name or "",
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return str(log_path)


def _clear_directory_contents(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for entry in directory.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink(missing_ok=True)


def clean_workspace_artifacts(output_root: Optional[str] = None, log_root: Optional[str] = None) -> dict[str, str]:
    output_dir = Path(output_root) if output_root else Path.cwd() / "output"
    log_dir = Path(log_root) if log_root else Path.cwd() / "log"
    _clear_directory_contents(output_dir)
    _clear_directory_contents(log_dir)
    return {"output_dir": str(output_dir), "log_dir": str(log_dir)}


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned or "job"


def _auto_job_name(job_packet: dict[str, Any], job_url: str, used_names: set[str]) -> str:
    job = job_packet.get("job", {}) if isinstance(job_packet, dict) else {}
    company = str(job.get("company") or "").strip()
    title = str(job.get("title") or "").strip()

    parts: list[str] = []
    if company and company.lower() != "unknown":
        parts.append(company)
    if title and title.lower() != "unknown":
        parts.append(title)

    if not parts:
        from urllib.parse import urlparse

        parsed = urlparse(job_url)
        tail = parsed.path.rstrip("/").split("/")[-1] if parsed.path else ""
        if tail:
            parts.append(tail)
        elif parsed.netloc:
            parts.append(parsed.netloc)
        else:
            parts.append("job")

    base = _slugify("-".join(parts))
    candidate = base
    index = 2
    while candidate in used_names:
        candidate = f"{base}-{index}"
        index += 1
    used_names.add(candidate)
    return candidate


def _run_single_tailor(
    job_name: str,
    file_path: Optional[str],
    job_url: Optional[str],
    output_root: Path,
    model_name: Optional[str],
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    resolved_tailor_model = _resolve_model_for_role("TAILOR", model_name)

    listing_text = load_listing_from_file(file_path)
    state: JobParserState = {
        "source": {"job_url": job_url, "listing_text": listing_text},
        "raw_listing_text": listing_text,
        "extracted_facts": {},
        "normalized_packet": {},
        "confidence": 0.0,
    }

    fetch_or_load_listing(state)
    extract_facts(state)
    normalize_packet(state)
    validate_packet(state)
    calculate_compatibility_score(state)

    compatibility_score = state["normalized_packet"].get("compatibility_score", 0)
    source_log_path = append_source_log(job_name, file_path, job_url, compatibility_score, model_name=resolved_tailor_model)

    handoff_result = handoff_to_tailor(state, output_dir=output_root)
    payload = build_tailored_payload(state["normalized_packet"], job_name=job_name, output_dir=str(output_root), model_name=resolved_tailor_model)
    payload["compatibility_score"] = compatibility_score

    summary_path = output_root / "tailored_resume.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "job_name": job_name,
        "output_dir": str(output_root),
        "job_packet": handoff_result["output_path"],
        "summary": str(summary_path),
        "pdf": payload.get("compile", {}).get("pdf_path", ""),
        "compatibility_score": compatibility_score,
        "source_log": source_log_path,
    }


def build_basic_resume(output_dir: Optional[str]) -> dict[str, str]:
    repo_root = Path(__file__).resolve().parent.parent
    resume_dir = repo_root / "resume"
    destination = Path(output_dir) if output_dir else Path.cwd() / "output" / "general"
    destination.mkdir(parents=True, exist_ok=True)
    resume_output_root = destination / "resume"
    resume_output_root.mkdir(parents=True, exist_ok=True)

    shutil.copy2(repo_root / "getkan-cv.cls", resume_output_root / "getkan-cv.cls")
    shutil.copytree(resume_dir / "modules", resume_output_root / "modules", dirs_exist_ok=True)
    fonts_dir = resume_dir / "fonts"
    if fonts_dir.exists():
        shutil.copytree(fonts_dir, resume_output_root / "fonts", dirs_exist_ok=True)

    resume_text = (resume_dir / "resume.tex").read_text(encoding="utf-8")
    resume_text = resume_text.replace("\\documentclass[11pt, letterpaper]{../getkan-cv}", "\\documentclass[11pt, letterpaper]{getkan-cv}")
    resume_text = resume_text.replace("\\fontdir[../fonts/]", "\\fontdir[fonts/]")
    resume_text = render_env_placeholders(resume_text)
    (resume_output_root / "resume.tex").write_text(resume_text, encoding="utf-8")

    xelatex = shutil.which("xelatex")
    if not xelatex:
        raise RuntimeError("xelatex not available on PATH")

    logs: list[str] = []
    for pass_index in range(2):
        result = subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
            cwd=resume_output_root,
            capture_output=True,
            text=True,
        )
        logs.append(f"pass {pass_index + 1} exit={result.returncode}")
        if result.stdout:
            logs.append(result.stdout[-1200:])
        if result.stderr:
            logs.append(result.stderr[-1200:])
        if result.returncode != 0:
            raise RuntimeError("Basic resume compile failed")

    compiled_pdf = resume_output_root / "resume.pdf"
    pdf_path = destination / "resume.pdf"
    if compiled_pdf.exists():
        shutil.copy2(compiled_pdf, pdf_path)
    return {
        "output_dir": str(destination),
        "pdf": str(pdf_path if pdf_path.exists() else ""),
        "compile_log": "\n".join(logs),
    }


def rebuild_from_job_packet(
    job_packet_file: str,
    job_name: Optional[str],
    output_dir: Optional[str],
    model_name: Optional[str],
) -> dict[str, Any]:
    packet_path = Path(job_packet_file)
    if not packet_path.exists() or not packet_path.is_file():
        raise FileNotFoundError(f"Job packet file not found: {job_packet_file}")

    try:
        packet_payload = json.loads(packet_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Invalid job packet JSON: {job_packet_file}") from exc

    if not isinstance(packet_payload, dict) or not isinstance(packet_payload.get("job"), dict):
        raise ValueError("Job packet must be a JSON object with a top-level 'job' object")

    inferred_name = packet_path.parent.name if packet_path.name == "job_packet.json" else packet_path.stem
    effective_name = _slugify(job_name or inferred_name)
    output_root = Path(output_dir) if output_dir else (Path.cwd() / "output" / effective_name)
    output_root.mkdir(parents=True, exist_ok=True)

    resolved_tailor_model = _resolve_model_for_role("TAILOR", model_name)
    compatibility_score = packet_payload.get("compatibility_score", 0)
    packet_payload["compatibility_score"] = compatibility_score
    source_log_path = append_source_log(
        effective_name,
        str(packet_path.resolve()),
        None,
        compatibility_score,
        model_name=resolved_tailor_model,
    )

    output_packet_path = output_root / "job_packet.json"
    output_packet_path.write_text(json.dumps(packet_payload, indent=2), encoding="utf-8")

    payload = build_tailored_payload(packet_payload, job_name=effective_name, output_dir=str(output_root), model_name=resolved_tailor_model)
    payload["compatibility_score"] = compatibility_score
    summary_path = output_root / "tailored_resume.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "mode": "rebuild",
        "job_name": effective_name,
        "job_packet_file": str(packet_path.resolve()),
        "output_dir": str(output_root),
        "job_packet": str(output_packet_path),
        "summary": str(summary_path),
        "pdf": payload.get("compile", {}).get("pdf_path", ""),
        "compatibility_score": compatibility_score,
        "source_log": source_log_path,
        "model_name": resolved_tailor_model or "",
    }


def rebuild_all_job_packets(output_dir: Optional[str] = None, model_name: Optional[str] = None) -> dict[str, Any]:
    output_root = Path(output_dir) if output_dir else (Path.cwd() / "output")
    packet_files = sorted(output_root.rglob("job_packet.json"))
    if not packet_files:
        raise FileNotFoundError(f"No job_packet.json files found under: {output_root}")

    rebuilds: list[dict[str, Any]] = []
    for packet_path in packet_files:
        packet_output_dir = packet_path.parent
        inferred_name = packet_output_dir.name if packet_path.name == "job_packet.json" else packet_path.stem
        rebuilds.append(
            rebuild_from_job_packet(
                str(packet_path),
                inferred_name,
                str(packet_output_dir),
                model_name,
            )
        )

    return {
        "mode": "rebuild-all",
        "output_dir": str(output_root),
        "packet_count": len(rebuilds),
        "rebuilds": rebuilds,
    }


def run(
    job_name: Optional[str],
    file_path: Optional[str],
    job_url: Optional[str],
    output_dir: Optional[str],
    model_name: Optional[str],
    build_basic: bool = False,
    recompile_existing: bool = False,
    job_hunt_advice: bool = False,
    job_packet_files: list[str] | None = None,
    url_list_file: str | None = None,
) -> int:
    if job_hunt_advice:
        advisor_model = _resolve_model_for_role("ADVISOR", model_name)
        advice_output_root = Path(output_dir) if output_dir else Path.cwd() / "output"
        recommendations = generate_job_hunt_recommendations(advice_output_root, job_packet_files=job_packet_files, model_name=advisor_model)
        print(
            json.dumps(
                {
                    "output_dir": str(advice_output_root),
                    "recommendations": recommendations.get("recommendations_path", ""),
                    "job_packet_count": recommendations.get("packet_count", 0),
                    "model_name": advisor_model or "",
                    "mode": "job-hunt-advice",
                },
                indent=2,
            )
        )
        return 0

    if build_basic:
        basic_result = build_basic_resume(output_dir)
        print(
            json.dumps(
                {
                    "output_dir": basic_result["output_dir"],
                    "pdf": basic_result["pdf"],
                    "mode": "build-basic",
                },
                indent=2,
            )
        )
        return 0

    if url_list_file:
        if job_name:
            raise ValueError("Do not provide job_name when using -l/--url-list-file")
        if file_path:
            raise ValueError("-f/--file is not supported with -l/--url-list-file")
        if job_url:
            raise ValueError("-u/--url cannot be combined with -l/--url-list-file")

        job_urls = load_urls_from_file(url_list_file)

        output_base = Path(output_dir) if output_dir else Path.cwd() / "output"
        output_base.mkdir(parents=True, exist_ok=True)

        used_names: set[str] = set()
        batch_results: list[dict[str, Any]] = []
        resolved_tailor_model = _resolve_model_for_role("TAILOR", model_name)
        for url in job_urls:
            staging_state: JobParserState = {
                "source": {"job_url": url, "listing_text": ""},
                "raw_listing_text": "",
                "extracted_facts": {},
                "normalized_packet": {},
                "confidence": 0.0,
            }
            fetch_or_load_listing(staging_state)
            extract_facts(staging_state)
            normalize_packet(staging_state)
            validate_packet(staging_state)
            calculate_compatibility_score(staging_state)

            auto_name = _auto_job_name(staging_state.get("normalized_packet", {}), url, used_names)
            output_root = output_base / auto_name
            output_root.mkdir(parents=True, exist_ok=True)

            # Score is already embedded in the packet by normalize_packet.
            compatibility_score = staging_state["normalized_packet"].get("compatibility_score", 0)
            source_log_path = append_source_log(auto_name, None, url, compatibility_score, model_name=resolved_tailor_model)
            handoff_result = handoff_to_tailor(staging_state, output_dir=output_root)
            payload = build_tailored_payload(staging_state["normalized_packet"], job_name=auto_name, output_dir=str(output_root), model_name=resolved_tailor_model)
            payload["compatibility_score"] = compatibility_score
            summary_path = output_root / "tailored_resume.json"
            summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            batch_results.append(
                {
                    "job_name": auto_name,
                    "url": url,
                    "output_dir": str(output_root),
                    "job_packet": handoff_result["output_path"],
                    "summary": str(summary_path),
                    "pdf": payload.get("compile", {}).get("pdf_path", ""),
                    "compatibility_score": compatibility_score,
                    "source_log": source_log_path,
                }
            )

        print(
            json.dumps(
                {
                    "mode": "batch-urls",
                    "url_list_file": str(Path(url_list_file).resolve()),
                    "count": len(batch_results),
                    "runs": batch_results,
                },
                indent=2,
            )
        )
        return 0

    if not job_name:
        raise ValueError("Provide job_name for single-run builds")

    default_output_root = Path.cwd() / "output" / job_name
    output_root = Path(output_dir or str(default_output_root))
    output_root.mkdir(parents=True, exist_ok=True)

    if recompile_existing:
        recompile_result = recompile_existing_output(output_root)
        compile_payload = recompile_result.get("compile", {})
        print(
            json.dumps(
                {
                    "job_name": job_name,
                    "output_dir": str(output_root),
                    "summary": recompile_result.get("summary", ""),
                    "pdf": compile_payload.get("pdf_path", ""),
                    "page_count": compile_payload.get("page_count"),
                    "mode": "recompile",
                },
                indent=2,
            )
        )
        return 0

    if not file_path and not job_url:
        raise ValueError("Provide either -f/--file or -u/--url")

    result = _run_single_tailor(job_name, file_path, job_url, output_root, model_name)
    print(
        json.dumps(result, indent=2)
    )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if getattr(args, "clean", False):
            result = clean_workspace_artifacts()
            print(
                json.dumps(
                    {
                        "mode": "clean",
                        "output_dir": result["output_dir"],
                        "log_dir": result["log_dir"],
                    },
                    indent=2,
                )
            )
            return 0

        if not getattr(args, "command", None):
            raise ValueError("Provide a command")

        if args.command == "build":
            return run(
                args.job_name,
                args.file_path,
                args.job_url,
                args.output_dir,
                args.model_name,
                False,
                False,
                False,
                None,
                args.url_list_file,
            )

        if args.command == "build-base":
            return run(None, None, None, args.output_dir, None, build_basic=True)

        if args.command == "rebuild":
            if args.all:
                result = rebuild_all_job_packets(args.output_dir, args.model_name)
            else:
                if not args.job_packet_file:
                    raise ValueError("Provide a job_packet.json path or use --all")
                result = rebuild_from_job_packet(args.job_packet_file, args.job_name, args.output_dir, args.model_name)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "advice":
            return run(
                None,
                None,
                None,
                args.output_dir,
                args.model_name,
                False,
                False,
                True,
                args.job_packet_files,
                None,
            )

        raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:  # pragma: no cover - CLI error surface
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    main()

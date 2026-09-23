from __future__ import annotations

import json
import os
import re
import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from src.application.parse_job import calculate_hybrid_compatibility_score, parse_job

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.application.advise import generate_job_hunt_recommendations
from src.application.tailor_resume import build_tailored_payload, recompile_existing_output
from src.infrastructure.environment import load_dotenv


class StatusSpinner:
    """Single-line terminal progress indicator that keeps stdout clean for JSON output."""

    def __init__(self, message: str) -> None:
        self.message = message
        self._is_tty = sys.stderr.isatty()

    def start(self) -> None:
        if not self._is_tty:
            return
        sys.stderr.write(f"{self.message}...\n")
        sys.stderr.flush()

    def stop(self, final_msg: str = "") -> None:
        return None

    def __enter__(self) -> StatusSpinner:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type:
            self.stop(f"Failed: {self.message}")
        else:
            self.stop(f"{self.message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tailor-resume")
    parser.add_argument("--clean", action="store_true", help="Remove generated output and log contents")
    commands = parser.add_subparsers(dest="command")
    parse = commands.add_parser("parse")
    parse.add_argument("-f", "--file", dest="file_path")
    parse.add_argument("-u", "--url", dest="job_url")
    parse.add_argument("-l", "--url-list-file", dest="url_list_file")
    parse.add_argument("-o", "--output", dest="output_dir")
    parse.add_argument("--model", dest="model_name")
    parse.add_argument("-t", "--tailor", action="store_true", help="Tailor the resume after parsing the job packet")
    tailor = commands.add_parser("tailor")
    tailor.add_argument("job_folder", help="Folder containing job_packet.json and raw_listing_text.txt")
    tailor.add_argument("-o", "--output", dest="output_dir")
    tailor.add_argument("--model", dest="model_name")
    advice = commands.add_parser("advice")
    advice.add_argument("-o", "--output", dest="output_dir")
    advice.add_argument("--model", dest="model_name")
    advice.add_argument("--job-packets", dest="job_packet_files", nargs="*")
    return parser


ROLE_DEFAULT_MODELS: dict[str, str] = {
    "PARSER": "openai/gpt-4o-mini",
    "TAILOR": "anthropic/claude-3.7-sonnet",
    "ADVISOR": "openai/gpt-4.1-mini",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_RESUME_DIR = REPO_ROOT / "resume"


def _require_resume_source(modules_only: bool = False) -> Path:
    modules_dir = REPO_RESUME_DIR / "modules"
    if not (REPO_RESUME_DIR / "resume.tex").exists() or not modules_dir.is_dir():
        raise FileNotFoundError(
            f"Base resume source not found at {REPO_RESUME_DIR}. "
            "Copy resume.example/ to resume/ and fill in your details before building."
        )
    if not modules_only and not (REPO_RESUME_DIR / "letter.tex").exists():
        raise FileNotFoundError(
            f"Base letter source not found at {REPO_RESUME_DIR / 'letter.tex'}. "
            "Copy resume.example/ to resume/ and fill in your details before building."
        )
    return REPO_RESUME_DIR


def load_listing_from_file(file_path: Optional[str]) -> str:
    if not file_path:
        return ""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {file_path}")
    return path.read_text(encoding="utf-8")


def extract_leading_metadata(text: str) -> tuple[dict[str, str], str]:
    """Parse leading `key: value` lines (e.g. source_url) preceding the job listing body."""
    metadata: dict[str, str] = {}
    consumed = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            if metadata:
                consumed += len(line)
            break
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", stripped)
        if not match:
            break
        metadata[match.group(1).lower()] = match.group(2).strip()
        consumed += len(line)
    return metadata, text[consumed:]


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


def _resolve_model_for_role(role: str, cli_override: Optional[str]) -> Optional[str]:
    if cli_override:
        return cli_override

    load_dotenv(REPO_ROOT / ".env")
    role_key = f"OPENROUTER_MODEL_{role.upper()}"
    return os.getenv(role_key) or os.getenv("OPENROUTER_MODEL") or ROLE_DEFAULT_MODELS.get(role.upper())


def append_source_log(
    job_name: str,
    file_path: Optional[str],
    job_url: Optional[str],
    compatibility_score: int,
    model_name: Optional[str] = None,
    validation_errors: Optional[list[str]] = None,
) -> str:
    log_dir = Path.cwd() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / ("failed_history.jsonl" if validation_errors else "success_history.jsonl")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_name": job_name,
        "url": job_url or "",
        "file": str(Path(file_path).resolve()) if file_path else "",
        "compatibility_score": compatibility_score,
        "model_name": model_name or "",
    }
    if validation_errors:
        entry["validation_errors"] = validation_errors
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return str(log_path)


def _validation_errors(job_packet: dict[str, Any]) -> list[str]:
    metadata = job_packet.get("metadata") if isinstance(job_packet, dict) else None
    errors = metadata.get("validation_errors") if isinstance(metadata, dict) else None
    return [str(error) for error in errors] if isinstance(errors, list) else []


def _record_failed_packet(
    job_packet: dict[str, Any],
    job_name: str,
    file_path: Optional[str],
    job_url: Optional[str],
    output_base: Path,
    model_name: Optional[str],
) -> dict[str, Any]:
    errors = _validation_errors(job_packet)
    failed_root = output_base / "failed"
    failed_root.mkdir(parents=True, exist_ok=True)
    failed_packet_root = failed_root / job_name
    failed_packet_root.mkdir(parents=True, exist_ok=True)
    failed_packet_path = failed_packet_root / "job_packet.json"
    failed_packet_path.write_text(json.dumps(job_packet, indent=2), encoding="utf-8")

    source = job_url or (str(Path(file_path).resolve()) if file_path else "")
    failed_list_path = failed_root / "failed.txt"
    if source:
        existing = failed_list_path.read_text(encoding="utf-8").splitlines() if failed_list_path.exists() else []
        if source not in existing:
            with failed_list_path.open("a", encoding="utf-8") as handle:
                handle.write(source + "\n")

    failed_log_path = append_source_log(job_name, file_path, job_url, 0, model_name=model_name, validation_errors=errors)

    return {
        "mode": "failed",
        "job_name": job_name,
        "url": job_url or "",
        "job_packet": str(failed_packet_path),
        "failed_list": str(failed_list_path),
        "validation_errors": errors,
        "failed_log": failed_log_path,
    }


def _write_job_artifacts(
    output_root: Path,
    job_packet: dict[str, Any],
    tailored_payload: dict[str, Any],
    raw_listing_text: str = "",
) -> dict[str, Path]:
    job_root = output_root / "job"
    job_root.mkdir(parents=True, exist_ok=True)

    packet_paths = _write_packet_artifacts(output_root, job_packet, raw_listing_text=raw_listing_text)
    summary_path = job_root / "tailored_resume.json"
    summary_path.write_text(json.dumps(tailored_payload, indent=2), encoding="utf-8")
    return {
        **packet_paths,
        "summary": summary_path,
    }


def _write_packet_artifacts(
    output_root: Path,
    job_packet: dict[str, Any],
    raw_listing_text: str = "",
) -> dict[str, Path]:
    job_root = output_root / "job"
    job_root.mkdir(parents=True, exist_ok=True)

    metadata = job_packet.get("metadata") if isinstance(job_packet.get("metadata"), dict) else {}
    raw_text = raw_listing_text or str(metadata.get("raw_listing_text") or "")
    raw_listing_path = job_root / "raw_listing_text.txt"
    raw_listing_path.write_text(raw_text, encoding="utf-8")

    packet_path = job_root / "job_packet.json"
    packet_path.write_text(json.dumps(job_packet, indent=2), encoding="utf-8")

    return {
        "raw_listing": raw_listing_path,
        "job_packet": packet_path,
    }


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
    file_path: Optional[str],
    job_url: Optional[str],
    output_dir: Optional[str],
    model_name: Optional[str],
) -> dict[str, Any]:
    resolved_tailor_model = _resolve_model_for_role("TAILOR", model_name)

    source_label = job_url or file_path or "source"
    with StatusSpinner(f"Parsing job listing from {source_label}"):
        raw_listing_text = load_listing_from_file(file_path)
        metadata, listing_text = extract_leading_metadata(raw_listing_text)
        effective_job_url = job_url or metadata.get("source_url")
        job_packet = parse_job(job_url=effective_job_url, listing_text=listing_text)

    job_name = _auto_job_name(job_packet, effective_job_url or file_path or "", set())
    output_base = Path(output_dir).parent if output_dir else (Path.cwd() / "output")
    if _validation_errors(job_packet):
        return _record_failed_packet(
            job_packet,
            job_name,
            file_path,
            effective_job_url,
            output_base,
            resolved_tailor_model,
        )

    output_root = Path(output_dir) if output_dir else (output_base / job_name)
    output_root.mkdir(parents=True, exist_ok=True)
    _require_resume_source()

    compatibility_score = job_packet.get("compatibility_score", 0)
    success_log_path = append_source_log(job_name, file_path, effective_job_url, compatibility_score, model_name=resolved_tailor_model)

    with StatusSpinner(f"Tailoring resume modules and compiling PDF for {job_name}"):
        payload = build_tailored_payload(job_packet, job_name=job_name, output_dir=str(output_root), model_name=resolved_tailor_model)
    payload["compatibility_score"] = compatibility_score
    artifact_paths = _write_job_artifacts(output_root, job_packet, payload, raw_listing_text=listing_text)
    packet_path = artifact_paths["job_packet"]
    summary_path = artifact_paths["summary"]

    return {
        "job_name": job_name,
        "output_dir": str(output_root),
        "job_packet": str(packet_path),
        "summary": str(summary_path),
        "pdf": payload.get("compile", {}).get("pdf_path", ""),
        "cv_pdf": payload.get("compile", {}).get("cv_pdf_path", ""),
        "compatibility_score": compatibility_score,
        "success_log": success_log_path,
    }


def _run_single_parse(
    file_path: Optional[str],
    job_url: Optional[str],
    output_dir: Optional[str],
) -> dict[str, Any]:
    source_label = job_url or file_path or "source"
    with StatusSpinner(f"Parsing job listing from {source_label}"):
        raw_listing_text = load_listing_from_file(file_path)
        metadata, listing_text = extract_leading_metadata(raw_listing_text)
        effective_job_url = job_url or metadata.get("source_url")
        job_packet = parse_job(job_url=effective_job_url, listing_text=listing_text)

    job_name = _auto_job_name(job_packet, effective_job_url or file_path or "", set())
    output_base = Path(output_dir).parent if output_dir else (Path.cwd() / "output")
    if _validation_errors(job_packet):
        return _record_failed_packet(job_packet, job_name, file_path, effective_job_url, output_base, None)

    output_root = Path(output_dir) if output_dir else (output_base / job_name)
    output_root.mkdir(parents=True, exist_ok=True)
    compatibility_score = job_packet.get("compatibility_score", 0)
    success_log_path = append_source_log(job_name, file_path, effective_job_url, compatibility_score)
    artifact_paths = _write_packet_artifacts(output_root, job_packet, raw_listing_text=listing_text)

    return {
        "mode": "parse",
        "job_name": job_name,
        "output_dir": str(output_root),
        "job_packet": str(artifact_paths["job_packet"]),
        "raw_listing": str(artifact_paths["raw_listing"]),
        "compatibility_score": compatibility_score,
        "success_log": success_log_path,
    }


def _tailor_job_packet(
    job_packet_file: str,
    output_dir: Optional[str],
    model_name: Optional[str],
    raw_listing_text: str = "",
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

    if packet_path.name == "job_packet.json" and packet_path.parent.name == "job":
        inferred_name = packet_path.parent.parent.name
    else:
        inferred_name = packet_path.parent.name if packet_path.name == "job_packet.json" else packet_path.stem
    effective_name = _slugify(inferred_name)
    output_root = Path(output_dir) if output_dir else (Path.cwd() / "output" / effective_name)

    if not _validation_errors(packet_payload):
        _require_resume_source()

    resolved_tailor_model = _resolve_model_for_role("TAILOR", model_name)
    resolved_parser_model = _resolve_model_for_role("PARSER", model_name)

    if _validation_errors(packet_payload):
        failure = _record_failed_packet(
            packet_payload,
            effective_name,
            str(packet_path.resolve()),
            str((packet_payload.get("metadata") or {}).get("source_url") or ""),
            output_root.parent,
            resolved_tailor_model,
        )
        failure["job_packet_file"] = str(packet_path.resolve())
        return failure

    output_root.mkdir(parents=True, exist_ok=True)

    compatibility_score = calculate_hybrid_compatibility_score(
        packet_payload.get("job", {}),
        model_name=resolved_parser_model,
    )
    packet_payload["compatibility_score"] = compatibility_score
    success_log_path = append_source_log(
        effective_name,
        str(packet_path.resolve()),
        str((packet_payload.get("metadata") or {}).get("source_url") or ""),
        compatibility_score,
        model_name=resolved_tailor_model,
    )

    artifact_job_root = output_root / "job"
    artifact_job_root.mkdir(parents=True, exist_ok=True)
    output_packet_path = artifact_job_root / "job_packet.json"
    serialized_packet = json.dumps(packet_payload, indent=2)
    output_packet_path.write_text(serialized_packet, encoding="utf-8")

    with StatusSpinner(f"Tailoring resume modules and compiling PDF for {effective_name}"):
        payload = build_tailored_payload(packet_payload, job_name=effective_name, output_dir=str(output_root), model_name=resolved_tailor_model)
    payload["compatibility_score"] = compatibility_score
    artifact_paths = _write_job_artifacts(output_root, packet_payload, payload, raw_listing_text=raw_listing_text)
    summary_path = artifact_paths["summary"]

    return {
        "mode": "tailor",
        "job_name": effective_name,
        "job_packet_file": str(packet_path.resolve()),
        "output_dir": str(output_root),
        "job_packet": str(output_packet_path),
        "summary": str(summary_path),
        "pdf": payload.get("compile", {}).get("pdf_path", ""),
        "cv_pdf": payload.get("compile", {}).get("cv_pdf_path", ""),
        "compatibility_score": compatibility_score,
        "success_log": success_log_path,
        "model_name": resolved_tailor_model or "",
        "source_url": str((packet_payload.get("metadata") or {}).get("source_url") or ""),
    }


def tailor_from_job_folder(
    job_folder: str,
    output_dir: Optional[str],
    model_name: Optional[str],
) -> dict[str, Any]:
    input_dir = Path(job_folder)
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"Tailor input is not a directory: {input_dir}")

    packet_path = input_dir / "job_packet.json"
    raw_path = input_dir / "raw_listing_text.txt"
    if not packet_path.is_file():
        raise FileNotFoundError(f"Job packet file not found: {packet_path}")
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw listing file not found: {raw_path}")

    result = _tailor_job_packet(
        str(packet_path),
        output_dir or str(input_dir.parent),
        model_name,
        raw_listing_text=raw_path.read_text(encoding="utf-8"),
    )
    result["job_folder"] = str(input_dir.resolve())
    result["raw_listing"] = str(raw_path.resolve())
    return result


def run(
    file_path: Optional[str],
    job_url: Optional[str],
    output_dir: Optional[str],
    model_name: Optional[str],
    recompile_existing: bool = False,
    job_hunt_advice: bool = False,
    job_packet_files: list[str] | None = None,
    url_list_file: str | None = None,
    tailor: bool = False,
) -> int:
    if job_hunt_advice:
        advisor_model = _resolve_model_for_role("ADVISOR", model_name)
        advice_output_root = Path(output_dir) if output_dir else Path.cwd() / "output"
        with StatusSpinner("Generating job hunt recommendations"):
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

    if url_list_file:
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
        for index, url in enumerate(job_urls, 1):
            with StatusSpinner(f"[{index}/{len(job_urls)}] Processing {url}"):
                job_packet = parse_job(job_url=url)
                auto_name = _auto_job_name(job_packet, url, used_names)
                if _validation_errors(job_packet):
                    batch_results.append(
                        _record_failed_packet(
                            job_packet,
                            auto_name,
                            None,
                            url,
                            output_base,
                            resolved_tailor_model,
                        )
                    )
                    continue

                if not tailor:
                    output_root = output_base / auto_name
                    output_root.mkdir(parents=True, exist_ok=True)
                    compatibility_score = job_packet.get("compatibility_score", 0)
                    success_log_path = append_source_log(auto_name, None, url, compatibility_score)
                    artifact_paths = _write_packet_artifacts(output_root, job_packet)
                    batch_results.append(
                        {
                            "mode": "parse",
                            "job_name": auto_name,
                            "url": url,
                            "output_dir": str(output_root),
                            "job_packet": str(artifact_paths["job_packet"]),
                            "raw_listing": str(artifact_paths["raw_listing"]),
                            "compatibility_score": compatibility_score,
                            "success_log": success_log_path,
                        }
                    )
                    continue

                _require_resume_source()

                output_root = output_base / auto_name
                output_root.mkdir(parents=True, exist_ok=True)

                compatibility_score = job_packet.get("compatibility_score", 0)
                success_log_path = append_source_log(auto_name, None, url, compatibility_score, model_name=resolved_tailor_model)
                payload = build_tailored_payload(job_packet, job_name=auto_name, output_dir=str(output_root), model_name=resolved_tailor_model)
                payload["compatibility_score"] = compatibility_score
                artifact_paths = _write_job_artifacts(output_root, job_packet, payload)
                packet_path = artifact_paths["job_packet"]
                summary_path = artifact_paths["summary"]

                batch_results.append(
                    {
                        "job_name": auto_name,
                        "url": url,
                        "output_dir": str(output_root),
                        "job_packet": str(packet_path),
                        "summary": str(summary_path),
                        "pdf": payload.get("compile", {}).get("pdf_path", ""),
                        "cv_pdf": payload.get("compile", {}).get("cv_pdf_path", ""),
                        "compatibility_score": compatibility_score,
                        "success_log": success_log_path,
                    }
                )

        failed_count = sum(1 for entry in batch_results if entry.get("mode") == "failed")
        print(
            json.dumps(
                {
                    "mode": "batch-urls",
                    "url_list_file": str(Path(url_list_file).resolve()),
                    "count": len(batch_results),
                    "failed_count": failed_count,
                    "runs": batch_results,
                },
                indent=2,
            )
        )
        return 0

    if recompile_existing:
        if not output_dir:
            raise ValueError("Provide -o/--output for recompile runs")
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        with StatusSpinner(f"Recompiling existing LaTeX output for {output_root.name}"):
            recompile_result = recompile_existing_output(output_root)
        compile_payload = recompile_result.get("compile", {})
        print(
            json.dumps(
                {
                    "job_name": output_root.name,
                    "output_dir": str(output_root),
                    "summary": recompile_result.get("summary", ""),
                    "pdf": compile_payload.get("pdf_path", ""),
                    "cv_pdf": compile_payload.get("cv_pdf_path", ""),
                    "page_count": compile_payload.get("page_count"),
                    "mode": "recompile",
                },
                indent=2,
            )
        )
        return 0

    if not file_path and not job_url:
        raise ValueError("Provide either -f/--file or -u/--url")

    result = (
        _run_single_tailor(file_path, job_url, output_dir, model_name)
        if tailor
        else _run_single_parse(file_path, job_url, output_dir)
    )
    print(
        json.dumps(result, indent=2)
    )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if getattr(args, "clean", False):
            with StatusSpinner("Cleaning workspace output and logs"):
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

        if args.command == "parse":
            return run(
                args.file_path,
                args.job_url,
                args.output_dir,
                args.model_name,
                url_list_file=args.url_list_file,
                tailor=args.tailor,
            )

        if args.command == "tailor":
            result = tailor_from_job_folder(
                args.job_folder,
                args.output_dir,
                args.model_name,
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "advice":
            return run(
                None,
                None,
                args.output_dir,
                args.model_name,
                job_hunt_advice=True,
                job_packet_files=args.job_packet_files,
            )

        raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:  # pragma: no cover - CLI error surface
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    main()

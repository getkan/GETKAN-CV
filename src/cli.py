from __future__ import annotations

import json
import os
import re
import argparse
import itertools
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from src.application.parse_job import calculate_hybrid_compatibility_score, parse_job

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.application.advise import generate_job_hunt_recommendations
from src.application.tailor_resume import build_tailored_payload, recompile_existing_output, render_env_placeholders
from src.infrastructure.environment import load_dotenv


class StatusSpinner:
    """Terminal progress indicator writing to stderr to keep stdout clean for JSON output."""

    def __init__(self, message: str) -> None:
        self.message = message
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_tty = sys.stderr.isatty()

    def start(self) -> None:
        if not self._is_tty:
            return
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        chars = itertools.cycle(["-", "\\", "|", "/"])
        while self._running:
            char = next(chars)
            sys.stderr.write(f"\r{char} {self.message}...")
            sys.stderr.flush()
            time.sleep(0.1)

    def stop(self, final_msg: str = "") -> None:
        if self._running:
            self._running = False
            if self._thread:
                self._thread.join()
        if self._is_tty:
            sys.stderr.write("\r\033[K")
            if final_msg:
                sys.stderr.write(f"[✓] {final_msg}\n")
            sys.stderr.flush()

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
    build = commands.add_parser("build")
    build.add_argument("-f", "--file", dest="file_path")
    build.add_argument("-u", "--url", dest="job_url")
    build.add_argument("-l", "--url-list-file", dest="url_list_file")
    build.add_argument("-o", "--output", dest="output_dir")
    build.add_argument("--model", dest="model_name")
    build_base = commands.add_parser("build-base")
    build_base.add_argument("-o", "--output", dest="output_dir")
    rebuild = commands.add_parser("rebuild")
    rebuild.add_argument("job_packet_file", nargs="?")
    rebuild.add_argument("--all", action="store_true")
    rebuild.add_argument("-f", "--force", action="store_true")
    rebuild.add_argument("-o", "--output", dest="output_dir")
    rebuild.add_argument("--model", dest="model_name")
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


def _resolve_model_for_role(role: str, cli_override: Optional[str]) -> Optional[str]:
    if cli_override:
        return cli_override

    load_dotenv(Path.cwd() / ".env")
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
        "failed_list": str(failed_list_path),
        "validation_errors": errors,
        "failed_log": failed_log_path,
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
        listing_text = load_listing_from_file(file_path)
        job_packet = parse_job(job_url=job_url, listing_text=listing_text)

    job_name = _auto_job_name(job_packet, job_url or file_path or "", set())
    output_base = Path(output_dir).parent if output_dir else (Path.cwd() / "output")
    if _validation_errors(job_packet):
        return _record_failed_packet(
            job_packet,
            job_name,
            file_path,
            job_url,
            output_base,
            resolved_tailor_model,
        )

    output_root = Path(output_dir) if output_dir else (output_base / job_name)
    output_root.mkdir(parents=True, exist_ok=True)

    compatibility_score = job_packet.get("compatibility_score", 0)
    success_log_path = append_source_log(job_name, file_path, job_url, compatibility_score, model_name=resolved_tailor_model)

    packet_path = output_root / "job_packet.json"
    packet_path.write_text(json.dumps(job_packet, indent=2), encoding="utf-8")

    with StatusSpinner(f"Tailoring resume modules and compiling PDF for {job_name}"):
        payload = build_tailored_payload(job_packet, job_name=job_name, output_dir=str(output_root), model_name=resolved_tailor_model)
    payload["compatibility_score"] = compatibility_score

    summary_path = output_root / "tailored_resume.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "job_name": job_name,
        "output_dir": str(output_root),
        "job_packet": str(packet_path),
        "summary": str(summary_path),
        "pdf": payload.get("compile", {}).get("pdf_path", ""),
        "compatibility_score": compatibility_score,
        "success_log": success_log_path,
    }


def build_basic_resume(output_dir: Optional[str]) -> dict[str, str]:
    with StatusSpinner("Building base resume and compiling PDF"):
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
                tail = (result.stdout or "")[-1200:] or (result.stderr or "")[-1200:]
                raise RuntimeError(
                    f"Basic resume compile failed on pass {pass_index + 1} "
                    f"(exit={result.returncode}):\n{tail}"
                )

        compiled_pdf = resume_output_root / "resume.pdf"
        pdf_path = destination / "resume.pdf"
        if compiled_pdf.exists():
            shutil.copy2(compiled_pdf, pdf_path)
        return {
            "output_dir": str(destination),
            "pdf": str(pdf_path if pdf_path.exists() else ""),
            "compile_log": "\n".join(logs),
        }


def _refresh_packet_from_source(packet_payload: dict[str, Any], job_packet_file: str) -> dict[str, Any]:
    metadata = packet_payload.get("metadata") if isinstance(packet_payload.get("metadata"), dict) else {}
    source_url = str(metadata.get("source_url") or "").strip()
    if not source_url:
        raise ValueError(f"Job packet has no metadata.source_url to rebuild from: {job_packet_file}")

    return parse_job(job_url=source_url)


def rebuild_from_job_packet(
    job_packet_file: str,
    output_dir: Optional[str],
    model_name: Optional[str],
    force: bool = False,
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

    source_url: Optional[str] = None
    if force:
        metadata = packet_payload.get("metadata") if isinstance(packet_payload.get("metadata"), dict) else {}
        source_url = str(metadata.get("source_url") or "").strip() or None
        packet_payload = _refresh_packet_from_source(packet_payload, job_packet_file)

    inferred_name = packet_path.parent.name if packet_path.name == "job_packet.json" else packet_path.stem
    effective_name = _slugify(inferred_name)
    output_root = Path(output_dir) if output_dir else (Path.cwd() / "output" / effective_name)

    resolved_tailor_model = _resolve_model_for_role("TAILOR", model_name)
    resolved_parser_model = _resolve_model_for_role("PARSER", model_name)

    if _validation_errors(packet_payload):
        failure = _record_failed_packet(
            packet_payload,
            effective_name,
            None if force else str(packet_path.resolve()),
            source_url,
            output_root.parent,
            resolved_tailor_model,
        )
        failure["job_packet_file"] = str(packet_path.resolve())
        failure["forced"] = bool(force)
        # The previously generated output is regenerable, so drop it rather than leave stale artifacts.
        if output_root.exists():
            shutil.rmtree(output_root)
        return failure

    output_root.mkdir(parents=True, exist_ok=True)

    if force:
        compatibility_score = packet_payload.get("compatibility_score", 0)
    else:
        compatibility_score = calculate_hybrid_compatibility_score(
            packet_payload.get("job", {}),
            model_name=resolved_parser_model,
        )
    packet_payload["compatibility_score"] = compatibility_score
    success_log_path = append_source_log(
        effective_name,
        None if force else str(packet_path.resolve()),
        source_url,
        compatibility_score,
        model_name=resolved_tailor_model,
    )

    output_packet_path = output_root / "job_packet.json"
    serialized_packet = json.dumps(packet_payload, indent=2)
    output_packet_path.write_text(serialized_packet, encoding="utf-8")
    if force and output_packet_path.resolve() != packet_path.resolve():
        packet_path.write_text(serialized_packet, encoding="utf-8")

    with StatusSpinner(f"Tailoring resume modules and compiling PDF for {effective_name}"):
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
        "success_log": success_log_path,
        "model_name": resolved_tailor_model or "",
        "forced": bool(force),
        "source_url": source_url or "",
    }


def rebuild_all_job_packets(output_dir: Optional[str] = None, model_name: Optional[str] = None, force: bool = False) -> dict[str, Any]:
    output_root = Path(output_dir) if output_dir else (Path.cwd() / "output")
    packet_files = sorted(p for p in output_root.rglob("job_packet.json") if "failed" not in p.relative_to(output_root).parts)
    if not packet_files:
        raise FileNotFoundError(f"No job_packet.json files found under: {output_root}")

    rebuilds: list[dict[str, Any]] = []
    for packet_path in packet_files:
        packet_output_dir = packet_path.parent
        rebuilds.append(
            rebuild_from_job_packet(
                str(packet_path),
                str(packet_output_dir),
                model_name,
                force,
            )
        )

    return {
        "mode": "rebuild-all",
        "output_dir": str(output_root),
        "packet_count": len(rebuilds),
        "failed_count": sum(1 for entry in rebuilds if entry.get("mode") == "failed"),
        "rebuilds": rebuilds,
    }


def run(
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

                output_root = output_base / auto_name
                output_root.mkdir(parents=True, exist_ok=True)

                compatibility_score = job_packet.get("compatibility_score", 0)
                success_log_path = append_source_log(auto_name, None, url, compatibility_score, model_name=resolved_tailor_model)
                packet_path = output_root / "job_packet.json"
                packet_path.write_text(json.dumps(job_packet, indent=2), encoding="utf-8")
                payload = build_tailored_payload(job_packet, job_name=auto_name, output_dir=str(output_root), model_name=resolved_tailor_model)
                payload["compatibility_score"] = compatibility_score
                summary_path = output_root / "tailored_resume.json"
                summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

                batch_results.append(
                    {
                        "job_name": auto_name,
                        "url": url,
                        "output_dir": str(output_root),
                        "job_packet": str(packet_path),
                        "summary": str(summary_path),
                        "pdf": payload.get("compile", {}).get("pdf_path", ""),
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
                    "page_count": compile_payload.get("page_count"),
                    "mode": "recompile",
                },
                indent=2,
            )
        )
        return 0

    if not file_path and not job_url:
        raise ValueError("Provide either -f/--file or -u/--url")

    result = _run_single_tailor(file_path, job_url, output_dir, model_name)
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

        if args.command == "build":
            return run(
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
            return run(None, None, args.output_dir, None, build_basic=True)

        if args.command == "rebuild":
            if args.all:
                result = rebuild_all_job_packets(args.output_dir, args.model_name, args.force)
            else:
                if not args.job_packet_file:
                    raise ValueError("Provide a job_packet.json path or use --all")
                result = rebuild_from_job_packet(args.job_packet_file, args.output_dir, args.model_name, args.force)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "advice":
            return run(
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

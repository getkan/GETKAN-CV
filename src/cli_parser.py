from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tailor-resume")
    parser.add_argument("--clean", action="store_true", help="Remove generated output and log contents")
    subparsers = parser.add_subparsers(dest="command")

    # Build tailored resume output from a URL, local listing file, or URL list file
    build = subparsers.add_parser(
        "build",
        help="Build tailored resume output from a URL, local listing file, or URL list file",
    )
    build.add_argument("job_name", nargs="?", help="Short name for a single tailored resume run")
    build.add_argument("-f", "--file", dest="file_path", help="Path to a listing file for a single run")
    build.add_argument("-u", "--url", dest="job_url", help="Job listing URL for a single run")
    build.add_argument(
        "-l",
        "--url-list-file",
        dest="url_list_file",
        help="Path to a text file containing job URLs (one per line) for batch processing",
    )
    build.add_argument("-o", "--output", dest="output_dir", help="Output directory for generated artifacts")
    build.add_argument("--model", dest="model_name", help="Optional OpenRouter model override")

    # Build base resume output without tailoring
    build_base = subparsers.add_parser(
        "build-base",
        help="Compile the base resume without tailoring",
    )
    build_base.add_argument("-o", "--output", dest="output_dir", help="Output directory for generated artifacts")

    # Rebuild tailored resume output from an existing job_packet.json
    rebuild = subparsers.add_parser(
        "rebuild",
        help="Rebuild tailored output from an existing job_packet.json",
    )
    rebuild.add_argument("job_packet_file", nargs="?", help="Path to a job_packet.json file")
    rebuild.add_argument("--job-name", dest="job_name", help="Optional explicit job name for output naming")
    rebuild.add_argument("--all", action="store_true", help="Rebuild all job_packet.json files found under the output directory")
    rebuild.add_argument("-o", "--output", dest="output_dir", help="Output directory for generated artifacts")
    rebuild.add_argument("--model", dest="model_name", help="Optional OpenRouter model override")

    # Generate job hunt recommendations from saved job_packet.json files
    advice = subparsers.add_parser(
        "advice",
        help="Generate job hunt recommendations from saved job_packet.json files",
    )
    advice.add_argument("-o", "--output", dest="output_dir", help="Output root to scan/write recommendations")
    advice.add_argument("--model", dest="model_name", help="Optional OpenRouter model override")
    advice.add_argument(
        "--job-packets",
        dest="job_packet_files",
        nargs="*",
        help="Optional explicit job_packet.json file paths (falls back to scanning output/**/job_packet.json)",
    )
    return parser
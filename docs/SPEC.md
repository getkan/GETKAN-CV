# Project specification

## Problem

Manually rewriting a resume for every job listing is slow and error prone, and
hand edits tend to drift away from the facts in the source resume. GETKAN-CV
turns a job listing into a normalized job packet and produces a tailored,
one-page LaTeX resume that only reuses facts already present in the base
resume.

## Users

A single owner-operator applying to software roles, working from a Linux shell
with `xelatex` installed and an OpenRouter API key available. The user owns the
base resume in `resume/` and reviews generated output before sending it.

## Required behavior

- `build` accepts a job URL (`-u`), a local listing file (`-f`), or a URL list
  file (`-l`) and writes tailored artifacts per job.
- Job names are never supplied by the user. They are derived from the parsed
  company and title, fall back to the source URL or file, are slugified, and
  are de-duplicated with a numeric suffix within a batch run.
- `rebuild` takes its job name from the packet's containing folder.
- `build-base` compiles the untailored base resume.
- `rebuild` regenerates tailored output from an existing `job_packet.json`,
  either for one packet or for every packet under the output tree (`--all`).
- `rebuild -f/--force` re-fetches and re-parses the listing from the packet's
  `metadata.source_url` and replaces the packet contents.
- `advice` aggregates saved job packets into job hunt recommendations.
- `--clean` clears generated `output/` and `log/` contents.
- Missing input (no URL, no file, absent packet, packet without
  `metadata.source_url`) fails with a message on stderr and a non-zero exit
  code.
- Every successful run appends an entry to `log/success_history.jsonl` and
  prints a JSON result summary on stdout.
- A parse that produces `metadata.validation_errors` is a failure: no tailored
  output is created, the packet is written to
  `output/failed/<job_name>/job_packet.json`, the source is appended to
  `output/failed/failed.txt`, and the run is logged only to
  `log/failed_history.jsonl`.
- `rebuild --all` and `advice` ignore packets under `output/failed/`.

## User experience

The only interface is the `./tailor-resume` CLI. Primary workflow: build from a
URL, inspect the generated modules and packet under the auto-named output
folder, optionally edit them, then `rebuild` (or `rebuild -f` to discard packet
edits and re-parse the listing). Prompts and tailoring controls are
user-editable JSON files under `src/*/`.

## Architecture and data flow

- `src/cli.py` defines the argument surface and dispatches commands.
- `src/main.py` is the entrypoint; orchestrates each command and resolves models per role.
- **Parsing phase** (`src/application/parse_job.py`):
  - Fetches or loads the listing from a URL or file.
  - Extracts facts: title, company, location, must-haves, nice-to-haves, responsibilities.
  - Normalizes and validates the packet; records `metadata.validation_errors` on failure.
  - Computes a compatibility score (1–10) by comparing job requirements against resume content.
  - Writes the normalized packet to `job_packet.json`.
- **Tailoring phase** (`src/application/tailor_resume.py` + `src/application/deterministic_tailor.py`):
  - Loads the job packet and applies one-page layout profiles progressively.
  - For each profile, `deterministic_tailor.py` rewrites `summary`, `experience`, `personalprojects`, and `aboutme` modules using deterministic rules (no LLM).
  - Writes tailored modules to `output/<job_name>/resume/modules/`.
  - Compiles with `xelatex` to PDF.
  - If page count ≤ 1, selects that profile and stops; otherwise uses the least constrained profile.
- **Advice phase** (`src/application/advise.py`):
  - Reads saved job packets and aggregates job hunt recommendations.
  - Compares market demand across packets against the base resume and skills catalog.
- **Supporting layers**:
  - `src/domain/` defines contracts: `job_packet.py` (job metadata), `resume_profile.py` (layout constraints).
  - `src/infrastructure/` provides adapters: `openrouter.py` (model API), `latex.py` (XeLaTeX integration), `artifacts.py` (I/O), `prompt_config.py` (prompt management).
- **State management**: File-based; `output/<job_name>/job_packet.json`, `tailored_resume.json`, compiled PDF, failed packets under `output/failed/`, and logs in `log/success_history.jsonl` + `log/failed_history.jsonl`.
- **External services**: OpenRouter for LLM calls, HTTP fetch for listing URLs.


## Security and privacy

- `OPENROUTER_API_KEY` is read from the environment or a local `.env` and must
  never be written to `output/` or `log/`.
- Personal identity fields (`RESUME_ADDRESS`, `RESUME_MOBILE`, `RESUME_EMAIL`)
  are injected at render time from environment variables, not committed in the
  base resume.
- Listing URLs are user-supplied and fetched as untrusted content; extracted
  text is only used as model input and packet data, never executed.

## Performance and compatibility

- Python 3.10+ on Linux, `xelatex` on `PATH`, optional `pdfinfo` for page
  counts.
- Tailored output should fit one page; progressive compactness profiles are
  applied until it does.

## Non-goals

- No web UI, service, or hosted deployment.
- No invention of experience, skills, or claims absent from the base resume.
- No automated job application submission.

## Acceptance criteria

- Each CLI command produces its documented artifacts and exits `0`, or fails
  with a clear stderr message and exit `1`.
- Tailored modules contain only facts derivable from `resume/modules/*`.
- `python -m unittest tests.test_parse_job tests.test_tailor_resume tests.test_advise tests.test_prompt_config`
  passes.
- Manual check: generated PDF opens, is one page, and reads correctly.

## Unresolved questions

- None currently tracked.

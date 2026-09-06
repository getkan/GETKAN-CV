# GETKAN-CV

GETKAN-CV is a Python + LaTeX resume and CV-letter tailoring tool.

It takes job input (URL, file, or URL list), extracts structured job requirements, tailors resume modules and a short employer-facing CV letter with truth-preserving edits, and compiles PDF outputs using `xelatex`. For tailored builds, the tool applies progressive one-page layout profiles to fit resume content onto a single page when possible.

## What This Project Does

- Parses a job listing into a normalized job packet.
- Tailors selected resume modules (`summary.tex`, `experience.tex`, `personalprojects.tex`, `aboutme.tex`).
- Tailors `cv.tex` as a short letter of introduction for the target employer and role.
- Uses OpenRouter to generate the tailored module content. `OPENROUTER_API_KEY` is required for tailoring; missing credentials, request failures, or invalid model output stop the run without generating a fallback resume.
- Writes generated artifacts to a dedicated output folder.
- Compiles LaTeX PDFs using `xelatex`.
- Supports rebuilding tailored outputs directly from a manually edited `job_packet.json`, or forcing a fresh parse from the packet's source URL.
- Emits one plain stderr progress line per long-running action while keeping stdout reserved for JSON results.

## Project Structure

### `src/`

#### `src/cli.py` & `src/main.py`

- Main entrypoint and command dispatch.
- Resolves models per role from environment or CLI.
- Manages workflow orchestration across all commands.

#### `src/application/`

**Core business logic and workflows**

- `parse_job.py`: Fetches, extracts, normalizes, validates, and scores job sources from URLs or files.
- `tailor_resume.py`: Core tailoring policy, module rewriting, artifact generation, and LaTeX compilation.
- `advise.py`: Job hunt recommendation generation across saved job packets.
- `deterministic_tailor.py`: Deterministic resume module rewriting engine.

#### `src/domain/`

**Typed contracts and data structures**

- `job_packet.py`: Normalized job metadata, requirements, and metadata.
- `resume_profile.py`: One-page layout profile contract (sentence/item limits, word limits).

#### `src/infrastructure/`

**External integrations and utilities**

- `openrouter.py`: OpenRouter JSON-schema transport and request/response handling.
- `latex.py`: XeLaTeX rendering, PDF page counting, and log inspection.
- `artifacts.py`: JSON serialization and file I/O helpers.
- `prompt_config.py`: Named prompt-configuration loader with safe defaults.
- `prompts.json`: Editable prompt groups for parsing, tailoring, and advice generation.


### `resume/`

- `resume/modules/skills.json`: Editable technical skills catalog used by tailoring allowlist prioritization.
- `resume/`: Source resume and base modules.

Skills categories in `resume/modules/skills.json` also influence bullet prioritization strength during tailoring (for example testing-focused roles prioritize testing-heavy bullets).

### `output/`

- `output/`: Generated job-specific artifacts.

### Repository root

- `tailor-resume`: Executable wrapper script.

## LaTeX File Structure

The resume is assembled from a root TeX file plus section modules.

```text
getkan-cv.cls
resume/
  fonts/
  resume.tex
  cv.tex
  modules/
    summary.tex
    experience.tex
    personalprojects.tex
    aboutme.tex
```

### Root and Class Files

- `getkan-cv.cls`
  - Custom document class for layout, typography, spacing, and CV macros (`\cvsection`, `\cventry`, `\cvitems`, etc.).
- `resume/resume.tex`
  - Main resume entrypoint.
  - Sets page geometry, color theme, fonts, and header/footer identity fields.
  - Imports active content modules using `\input{modules/...}`.
- `resume/cv.tex`
  - Main CV-letter entrypoint.
  - Uses the same class, font, header, footer, and cover-letter macros as the resume styling.
  - Provides the base short letter that tailored runs customize for the target employer.
- `resume/fonts/`
  - Local font files consumed by `\fontdir[fonts/]` in `resume/resume.tex`.
  - Provides Roboto variants and FontAwesome used by the custom class.

### Section Module Files (`resume/modules/*.tex`)

- `resume/modules/summary.tex`
  - Summary section (`\cvsection{Summary}`) with a single paragraph describing your profile.
- `resume/modules/experience.tex`
  - Work Experience section with role blocks and bullet groups.
  - Uses `\cventry`, `\cvitems`, and `\cvsubitems` for job history and achievements.
- `resume/modules/personalprojects.tex`
  - Personal Projects section.
  - Includes optional intro text and project bullets used by tailoring/project-priority logic.
- `resume/modules/aboutme.tex`
  - About Me section.
  - Mixes education anchor content plus personal interest/context bullets.

### Generated TeX (Per Tailoring Run)

For each tailored run, TeX files are copied/generated into:

- `output/<job_name>/resume/resume.tex`
  - Compilable run-specific root file.
- `output/<job_name>/resume/cv.tex`
  - Compilable run-specific CV letter file.
- `output/<job_name>/resume/modules/*.tex`
  - Tailored versions of section modules used for that job target.
- `output/<job_name>/<job_name>.pdf`
  - Published final resume PDF at the output root.
- `output/<job_name>/<job_name>-cv.pdf`
  - Published final CV-letter PDF at the output root.

## Requirements

### System

- Python 3.10+ (recommended)
- `xelatex` (XeTeX distribution) — required for PDF compilation
- `latexmk` — required for terminal and VS Code builds
- Optional but recommended: `pdfinfo` (for page count metadata)

Install the full LaTeX toolchain with the platform scripts:

```bash
# Linux and macOS
./scripts/install-latex.sh
```

```powershell
# Windows (elevated PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\install-latex.ps1
```

See [docs/LATEX_SETUP.md](docs/LATEX_SETUP.md) for the full dependency list,
manual per-distribution commands, verification steps, and troubleshooting.

### API & Environment

- OpenRouter API key for model-assisted parsing and tailoring:
  - `OPENROUTER_API_KEY` (required)
  - Optional global fallback: `OPENROUTER_MODEL`
  - Optional parser model override: `OPENROUTER_MODEL_PARSER`
  - Optional tailor model override: `OPENROUTER_MODEL_TAILOR`
  - Optional advisor model override: `OPENROUTER_MODEL_ADVISOR`

Install Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Minimal Python packages used:

- `requests`

## Environment Setup

Create a `.env` file in the repository root (optional if env vars are already exported):

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_MODEL_PARSER=openai/gpt-4o-mini
OPENROUTER_MODEL_TAILOR=anthropic/claude-3.7-sonnet
OPENROUTER_MODEL_ADVISOR=openai/gpt-4.1-mini
```

Model resolution order is:

- Parser: `OPENROUTER_MODEL_PARSER` -> `OPENROUTER_MODEL` -> built-in default
- Tailor: `--model` CLI override -> `OPENROUTER_MODEL_TAILOR` -> `OPENROUTER_MODEL` -> `anthropic/claude-3.7-sonnet`
- Advisor: `--model` CLI override -> `OPENROUTER_MODEL_ADVISOR` -> `OPENROUTER_MODEL` -> `openai/gpt-4.1-mini`

Parser, tailoring, and advisor prompts live in `src/infrastructure/prompts.json` under the `parser`, `tailor`, and `advisor` keys.
Common keys:

- `summary_section_prompt`
- `experience_section_prompt`
- `personalprojects_section_prompt`
- `aboutme_section_prompt`
- `aboutme_required_items` (delimiter: `||`)

To customize personal project order, include it directly inside `personalprojects_section_prompt`:

`Priority order: getkan-cv||linux enthusiast||mystic type-writer||notesboard plus plus`

## Command Reference

### 1) Build tailored resume outputs

Use `build` for single URL, single file, or URL-list batch workflows. Job names are always derived automatically from the parsed company and title.

Build from URL:

```bash
./tailor-resume build -u <job_url>
```

Example:

```bash
./tailor-resume build -u "https://www.github.careers/careers-home/jobs/5682?lang=en-us"
```

Build from local listing file:

```bash
./tailor-resume build -f <path_to_listing_text_or_html>
```

Batch build from URL list file:

```bash
./tailor-resume build -l <path_to_url_list_file>
```

Optional custom output root for batch runs:

```bash
./tailor-resume build -l <path_to_url_list_file> -o <output_dir>
```

Set custom output directory for a single run:

```bash
./tailor-resume build -u <job_url> -o <output_dir>
```

Override model (optional):

```bash
./tailor-resume build -u <job_url> --model <model_id>
```

If `-o` is omitted for single-run build, default output is:

```text
output/<job_name>
```

The URL list file should contain one URL per line (blank lines and lines starting with `#` are ignored).
Job names are generated from parsed company/title (falling back to the URL), de-duplicated with a numeric suffix, and each run writes to its own output folder.

### 2) Build base resume (no tailoring)

```bash
./tailor-resume build-base
```

Optional custom output directory:

```bash
./tailor-resume build-base -o <output_dir>
```

Default output when `-o` is omitted:

```text
output/general
```

### 3) Rebuild from an existing job_packet.json

Use this when you manually edit a `job_packet.json` and want regenerated tailored modules, CV letter, and PDFs from that packet.

```bash
./tailor-resume rebuild <path_to_job_packet_json>
```

Optional output directory (the job name is taken from the packet's folder name):

```bash
./tailor-resume rebuild <path_to_job_packet_json> -o <output_dir>
```

Optional model override:

```bash
./tailor-resume rebuild <path_to_job_packet_json> --model <model_id>
```

Rebuild all saved packets under the output tree:

```bash
./tailor-resume rebuild --all
```

Optional custom output root for batch rebuild:

```bash
./tailor-resume rebuild --all -o <output_dir>
```

Force a fresh parse from the packet's `metadata.source_url`:

```bash
./tailor-resume rebuild <path_to_job_packet_json> -f
./tailor-resume rebuild --all --force
```

This mode:

- Skips URL/file parsing.
- Rebuilds tailored resume and CV-letter output from the supplied packet.
- Writes/updates `job_packet.json`, `tailored_resume.json`, and compiled PDF outputs in the target folder.
- `--all` scans the output tree for `job_packet.json` files and rebuilds each one.
- `-f/--force` re-fetches and re-parses the listing from `metadata.source_url` and replaces the existing packet contents. It fails when the packet has no `metadata.source_url`.

### 4) Generate job hunt recommendations from saved packets

```bash
./tailor-resume advice
```

Optional custom output root to scan and write recommendations:

```bash
./tailor-resume advice -o <output_dir>
```

Optional explicit packet files (instead of discovery scan):

```bash
./tailor-resume advice --job-packets output/role-a/job_packet.json output/role-b/job_packet.json
```

This mode:

- Scans `output/**/job_packet.json`.
- Or uses explicit files from `--job-packets` when provided.
- Compares market demand from saved packets against your current resume modules and `skills.json`.
- Writes `job_hunt_recommendations.md` with skills and positioning recommendations.
- Includes a **Most Compatible Jobs** section listing the top 5 jobs by compatibility score.
- If no packets are available, it writes general job-hunt recommendations instead of a blank/no-data message.

### 5) Show CLI help

```bash
./tailor-resume -h
```

### 6) Clean generated output and logs

```bash
./tailor-resume --clean
```

This removes the contents of `output/` and `log/` and recreates both directories.

## LaTeX Build Setup

### XeLaTeX Requirement

The custom `getkan-cv.cls` document class uses `fontspec` and `unicode-math`, which require XeTeX or LuaTeX. The build is configured to use `xelatex` via:

1. **Workspace configuration** ([.vscode/settings.json](.vscode/settings.json)):
   - Defines the LaTeX Workshop recipe to use `-xelatex` flag (not `-pdf`).
   - Workspace settings override the VS Code extension's default `pdflatex` recipe.

2. **Local latexmk config** ([resume/.latexmkrc](resume/.latexmkrc)):
   - Sets `$pdf_mode = 5` (XeLaTeX mode) for command-line builds.
   - Ensures consistent behavior across VS Code editor and terminal invocations.

### Build Verification

Test XeLaTeX build from the command line:

```bash
cd resume && latexmk -xelatex -interaction=nonstopmode -file-line-error resume.tex
```

Or from VS Code using the LaTeX Workshop extension (configured to use the xelatex recipe).

## Test Commands

Run the full unit test suite:

```bash
python -m unittest -q tests.test_parse_job tests.test_tailor_resume tests.test_advise tests.test_prompt_config
```

Run a single test file:

```bash
python -m unittest -q tests.test_parse_job
python -m unittest -q tests.test_tailor_resume
python -m unittest -q tests.test_advise
python -m unittest -q tests.test_prompt_config
```

## Generated Output Layout

For a run like `./tailor-resume build -u <job_url>`:

- `output/github-careers/job_packet.json`: Parsed and normalized job data.
- `output/github-careers/tailored_resume.json`: Tailoring payload + compile metadata.
- `output/github-careers/resume/resume.tex`: Compilable resume root.
- `output/github-careers/resume/cv.tex`: Compilable tailored CV letter.
- `output/github-careers/resume/modules/*.tex`: Tailored module files.
- `output/github-careers/github-careers.pdf`: Final resume PDF output.
- `output/github-careers/github-careers-cv.pdf`: Final CV-letter PDF output.
- `log/success_history.jsonl`: Append-only history of successful runs with timestamps.
- `log/failed_history.jsonl`: Append-only history of failed parses with their validation errors.

### Failed Parses

When a parse produces validation errors, no tailored output is generated:

- The job packet is written to `output/failed/<job_name>/job_packet.json` and nothing else.
- The source URL (or file path) is appended to `output/failed/failed.txt`.
- The run is logged to `log/failed_history.jsonl` only, never to `log/success_history.jsonl`.
- The tailor and PDF compile steps are skipped, and the CLI result reports `"mode": "failed"`.
- A `rebuild` of a packet that fails validation removes its regenerable output folder and moves the packet to `output/failed/`.
- `rebuild --all` and `advice` skip everything under `output/failed/`.

For each tailored run, a `compatibility_score` (1-10) is computed and:

- printed in CLI JSON output,
- stored in `job_packet.json`,
- stored in `tailored_resume.json`,
- appended to `log/success_history.jsonl`.

## Typical Workflow

1. Run `build` from URL/file or URL-list.
2. Inspect generated modules in `output/<job_name>/resume/modules`.
3. Optionally edit `job_packet.json` or generated module files.
4. Optionally inspect or edit the generated CV letter at `output/<job_name>/resume/cv.tex`.
5. Run `rebuild` with the packet path to regenerate outputs.
6. Run `rebuild -f` to discard packet edits and re-parse the original listing URL.

For a non-tailored base resume build, use `build-base`.

## Architecture & Data Flow

### Parsing Workflow

1. `src/cli.py` dispatches to `src/application/parse_job.py`.
2. The job source (URL or file) is fetched and normalized.
3. Fact extraction produces structured job metadata: title, company, requirements, responsibilities.
4. Validation checks for required fields; failures are recorded in `metadata.validation_errors`.
5. A compatibility score (1–10) is computed by comparing job requirements against resume content.
6. The normalized packet is written to `job_packet.json`.

### Tailoring Workflow

1. `src/cli.py` loads the job packet and invokes `src/application/tailor_resume.py`.
2. For tailored builds, a list of one-page layout profiles is applied progressively:
   - Profile 1: least constrained (summary_sentences=2, cvsubitems_limit=4, word_limit=28)
   - Profile 2: moderate constraints (summary_sentences=2, cvsubitems_limit=3, word_limit=24)
   - Profile 3: maximum constraints (summary_sentences=1, cvsubitems_limit=2, word_limit=18)
3. For each profile:
  - `src/application/tailor_resume.py` requests tailored resume modules and a tailored `cv.tex` from OpenRouter using JSON schema output.
  - Modules are written to `output/<job_name>/resume/modules/` and the CV letter is written to `output/<job_name>/resume/cv.tex`.
  - XeLaTeX compiles the resume and CV letter to PDFs.
   - Page count is checked; if ≤ 1 page, the profile is selected and tailoring stops.
4. If no profile fits to one page, the least constrained profile is used.
5. Artifacts are written to `output/<job_name>/`; PDFs are published at `output/<job_name>/<job_name>.pdf` and `output/<job_name>/<job_name>-cv.pdf`.

### Notes

- Tailoring is constrained to use existing resume facts only; no new achievements are invented.
- Model-assisted tailoring is constrained by prompts and schema output to reuse existing resume facts only.
- Project selection/prioritization logic for `personalprojects.tex` is independent of job description and governed by a fixed priority list.
- One-page fitting uses progressive compactness profiles to maximize content density while maintaining readability.

# GETKAN-CV

GETKAN-CV is a Python + LaTeX resume tailoring tool.

It takes job input (URL, file, or URL list), extracts structured job requirements, tailors resume modules with truth-preserving edits, and compiles PDF resume outputs that are constrained to one page when possible.

## What This Project Does

- Parses a job listing into a normalized job packet.
- Tailors selected resume modules (`summary.tex`, `experience.tex`, `personalprojects.tex`, `aboutme.tex`).
- Writes generated artifacts to a dedicated output folder.
- Compiles a LaTeX PDF using `xelatex`.
- Supports rebuilding tailored outputs directly from a manually edited `job_packet.json`.

## Project Structure

### `src/`

#### `src/main.py`

- CLI entrypoint and workflow orchestration.

#### `src/parser/`

- `agent.py`: Job extraction, fallback parsing, normalization, validation.
- `prompts.json`: Editable prompt templates for parser behavior.

#### `src/advisor/`

- `agent.py`: Cross-job analysis of saved job packets with resume-based recommendation output.
- `prompts.json`: Editable prompt templates for advisor behavior.
- `sections/`: Section builders for general advice, skills, job titles, resume recommendations, interview prep, ATS gaps, and portfolio suggestions.
- `common.py`: Shared advisor helpers for text normalization and related advisor utilities.

#### `src/tailor/`

- `agent.py`: Module tailoring, one-page fit profiles, artifact writing, compile logic.
- `prompts.json`: Editable prompt templates for tailor behavior.


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
  modules/
    summary.tex
    experience.tex
    personalprojects.tex
    aboutme.tex
    education.tex
```

### Root and Class Files

- `getkan-cv.cls`
  - Custom document class for layout, typography, spacing, and CV macros (`\cvsection`, `\cventry`, `\cvitems`, etc.).
- `resume/resume.tex`
  - Main resume entrypoint.
  - Sets page geometry, color theme, fonts, and header/footer identity fields.
  - Imports active content modules using `\input{modules/...}`.
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
- `resume/modules/education.tex`
  - Standalone Education section content.
  - Currently present as a source module but not imported by default in `resume/resume.tex`.

### Generated TeX (Per Tailoring Run)

For each tailored run, TeX files are copied/generated into:

- `output/<job_name>/resume/resume.tex`
  - Compilable run-specific root file.
- `output/<job_name>/resume/modules/*.tex`
  - Tailored versions of section modules used for that job target.
- `output/<job_name>/<job_name>.pdf`
  - Published final PDF at the output root.

## Requirements

- Python 3.10+ (recommended)
- `xelatex` available on `PATH`
- Optional but recommended: `pdfinfo` (for page count metadata)
- OpenRouter API key for model-assisted parsing:
  - `OPENROUTER_API_KEY`
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
RESUME_ADDRESS=123 Main St, Austin, TX 78701
RESUME_MOBILE=(+1) 555-555-5555
RESUME_EMAIL=your.email@example.com
```

Model resolution order is:

- Parser: `OPENROUTER_MODEL_PARSER` -> `OPENROUTER_MODEL` -> built-in default
- Tailor: `--model` CLI override -> `OPENROUTER_MODEL_TAILOR` -> `OPENROUTER_MODEL` -> `anthropic/claude-3.7-sonnet`
- Advisor: `--model` CLI override -> `OPENROUTER_MODEL_ADVISOR` -> `OPENROUTER_MODEL` -> `openai/gpt-4.1-mini`

Resume template identity placeholders resolve from env vars:

- `RESUME_ADDRESS`
- `RESUME_MOBILE`
- `RESUME_EMAIL`

Section-level tailoring controls live in `src/tailor/prompts.json`.
Advisor section prompts live in `src/advisor/prompts.json`.
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

Use `build` for single URL, single file, or URL-list batch workflows.

Build from URL:

```bash
./tailor-resume build <job_name> -u <job_url>
```

Example:

```bash
./tailor-resume build github-careers -u "https://www.github.careers/careers-home/jobs/5682?lang=en-us"
```

Build from local listing file:

```bash
./tailor-resume build <job_name> -f <path_to_listing_text_or_html>
```

Batch build from URL list file (auto job names):

```bash
./tailor-resume build -l <path_to_url_list_file>
```

Optional custom output root for batch runs:

```bash
./tailor-resume build -l <path_to_url_list_file> -o <output_dir>
```

Set custom output directory for a single run:

```bash
./tailor-resume build <job_name> -u <job_url> -o <output_dir>
```

Override model (optional):

```bash
./tailor-resume build <job_name> -u <job_url> --model <model_id>
```

If `-o` is omitted for single-run build, default output is:

```text
output/<job_name>
```

The URL list file should contain one URL per line (blank lines and lines starting with `#` are ignored).
Batch mode auto-generates unique job names from parsed company/title and writes each run to its own output folder.

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

Use this when you manually edit a `job_packet.json` and want regenerated tailored modules/PDF from that packet.

```bash
./tailor-resume rebuild <path_to_job_packet_json>
```

Optional explicit job name and output directory:

```bash
./tailor-resume rebuild <path_to_job_packet_json> --job-name <job_name> -o <output_dir>
```

Optional model override:

```bash
./tailor-resume rebuild <path_to_job_packet_json> --model <model_id>
```

This mode:

- Skips URL/file parsing.
- Rebuilds tailored output from the supplied packet.
- Writes/updates `job_packet.json`, `tailored_resume.json`, and compiled PDF output in the target folder.

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

## Test Commands

Run the current unit test suite:

```bash
python -m unittest -q tests.test_job_parser_agent
```

## Generated Output Layout

For a run like `./tailor-resume build github-careers ...`:

- `output/github-careers/job_packet.json`: Parsed and normalized job data.
- `output/github-careers/tailored_resume.json`: Tailoring payload + compile metadata.
- `output/github-careers/resume/resume.tex`: Compilable resume root.
- `output/github-careers/resume/modules/*.tex`: Tailored module files.
- `output/github-careers/github-careers.pdf`: Final PDF output.
- `log/source_history.jsonl`: Append-only history of previously used URL/file inputs with timestamps.

For each tailored run, a `compatibility_score` (1-10) is computed and:

- printed in CLI JSON output,
- stored in `tailored_resume.json`,
- appended to `log/source_history.jsonl`.

## Typical Workflow

1. Run `build` from URL/file or URL-list.
2. Inspect generated modules in `output/<job_name>/resume/modules`.
3. Optionally edit `job_packet.json` or generated module files.
4. Run `rebuild` with the packet path to regenerate outputs.

For a non-tailored base resume build, use `build-base`.

## Notes

- Tailoring is constrained to use existing resume facts only.
- Project selection/prioritization logic for personalprojects content is deterministic and independent of job description.
- One-page fitting uses progressive compactness profiles when generating tailored output.

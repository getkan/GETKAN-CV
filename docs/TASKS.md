# Project tasks

## Current phase

No pending tasks. Add a task here when new work is scoped in
[ROADMAP.md](ROADMAP.md).

## Completed

- [x] Parsing foundation (Roadmap Phase 1).
  - Validation: `python -m unittest tests.test_parse_job`.
- [x] Tailoring and PDF compilation (Roadmap Phase 2).
  - Validation: test suite plus manual PDF review.
- [x] Rebuild and advice workflows (Roadmap Phase 3).
  - Validation: test suite, `./tailor-resume rebuild --help`, and a
    `./tailor-resume rebuild --all -f` run.
- [x] Automatic job naming for all commands.
  - Validation: full unittest run and `./tailor-resume build --help` / `./tailor-resume rebuild --help`.
- [x] Failed-parse isolation (Roadmap Phase 4).
  - Validation: `python -m unittest tests.test_parse_job tests.test_tailor_resume tests.test_advise tests.test_prompt_config` (full test suite).
- [x] Refactored codebase structure.
  - Consolidated `src/parser/`, `src/tailor/`, and `src/advisor/` into `src/application/`.
  - Added `src/domain/` for typed contracts.
  - Added `src/infrastructure/` for external integrations (`openrouter.py`, `latex.py`, `artifacts.py`, `prompt_config.py`).
  - Standardized OpenRouter JSON schema calls across application modules to use `src/infrastructure/openrouter.py`.
  - Reorganized `parse_job.py` and `advise.py` into clear logical sections with PEP 8 top-level imports.
  - Rewrote and updated unit test suite (35 passing tests) matching new module structure and deleted legacy test files (`test_parser_agent.py`, `test_tailor_agent.py`, `test_advisor_agent.py`).
- [x] LaTeX build configuration.
  - Added `.vscode/settings.json` for workspace-level XeLaTeX recipe override.
  - Added `resume/.latexmkrc` for command-line consistency.
  - Verified `xelatex` builds work from both editor and terminal.
- [x] One-line progress output for long-running CLI operations.
  - Replaced animated spinner output with one stderr line per action so stdout remains clean JSON.
- [x] Tailored CV letter output.
  - Added `resume/letter.tex` tailoring and published `<job_name>-cv.pdf` outputs alongside resume PDFs.
- [] More dynamic resume modules, allowing for easier addition and removal of sections without modifying core logic.
- [] Extract skills from hardcoded lists into a configurable source (e.g., JSON or database).

## Known issues

- None currently tracked; all known issues have been resolved.

## Notes

- PDF publication is validated by manual inspection; automated page-count assertions are in place for tailored resume output.
- One-page layout fitting uses progressive profile constraints while model-assisted tailoring remains constrained to existing resume facts.


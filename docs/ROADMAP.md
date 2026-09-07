# Project roadmap

All planned phases are delivered. New phases are added only when new work is
scoped.

## Phase 1: Parsing foundation (completed)

### Outcome

A job listing from a URL or local file is parsed into a normalized, validated
`job_packet.json` with a compatibility score.

### Included work

- Listing fetch/load, fact extraction, normalization, and validation in
  `src/application/parse_job.py`.
- Deterministic skill normalization using resume content alignment.
- Role-based model resolution and `.env` loading.

### Dependencies and risks

- Requires `OPENROUTER_API_KEY`; listing sites may block automated fetches.

### Exit criteria

- `./tailor-resume build -u <url>` writes a valid packet.

### Validation

- `python -m unittest tests.test_parse_job`.


## Phase 2: Tailoring and compilation (completed)

### Outcome

Tailored resume modules, a tailored CV letter, and compiled PDFs per job, with progressive one-page layout fitting for the resume.

### Included work

- Module tailoring with deterministic rewriting in `src/application/deterministic_tailor.py`.
- CV-letter tailoring from `resume/letter.tex` using the same LaTeX styling.
- One-page fit profiles and progressive constraint application in `src/application/tailor_resume.py`.
- `build` and batch URL-list builds.
- Artifact layout under `output/<job_name>/`.
- XeLaTeX integration with workspace and local latexmk configuration.

### Dependencies and risks

- Requires `xelatex`; compile failures block PDF output.
- Requires `pdfinfo` for page count detection (falls back gracefully).

### Exit criteria

- Tailored `.tex` modules, tailored `letter.tex`, and published resume/CV PDFs are produced for a build run.

### Validation

- Test suite plus manual review of the generated PDFs.


## Phase 3: Rebuild and advice workflows (completed)

### Outcome

Saved packets can be regenerated or re-parsed, and analyzed across jobs.

### Included work

- `rebuild`, `rebuild --all`, and `rebuild -f/--force` re-parse from
  `metadata.source_url`.
- Automatic job naming for every command; explicit job-name arguments removed.
- `advice` recommendation sections in `src/application/advise.py`.
- `--clean` workspace reset.

### Dependencies and risks

- Forced rebuild depends on the source URL still being reachable; it
  overwrites manual packet edits by design.

### Exit criteria

- `./tailor-resume rebuild --all -f` completes and refreshes each packet.

### Validation

- Test suite, `rebuild --help` surface check, and a real `rebuild --all -f`
  run.

## Phase 4: Failed-parse isolation (completed)

### Outcome

Listings that fail validation never produce tailored output and are tracked
separately.

### Included work

- Failed packets written to `output/failed/<job_name>/job_packet.json` with the
  source recorded in `output/failed/failed.txt`.
- Split history logs: `log/success_history.jsonl` and
  `log/failed_history.jsonl`.
- `rebuild --all` and the advisor skip `output/failed/`.

### Dependencies and risks

- A failed `rebuild` deletes the regenerable output folder for that packet.

### Exit criteria

- A parse with validation errors skips the tailor and writes only the failed
  packet.

### Validation

- `python -m unittest tests.test_tailor_resume` including coverage of failed-parse paths.


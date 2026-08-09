from __future__ import annotations

# Centralized list of resume module filenames used across analysis/build flows.
# Edit this tuple to add/remove modules consumed by helpers that build a resume corpus.
RESUME_MODULE_NAMES: tuple[str, ...] = (
    "summary.tex",
    "experience.tex",
    "personalprojects.tex",
    "aboutme.tex",
)

# Compatibility score range that triggers an LLM adjustment pass.
# Scores outside this range are returned as-is (no API cost).
COMPATIBILITY_BORDERLINE_LOW: int = 3
COMPATIBILITY_BORDERLINE_HIGH: int = 10

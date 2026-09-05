"""Prompt configuration loading with safe defaults."""

from __future__ import annotations

import json
from pathlib import Path


def load_prompt_config(path: Path, defaults: dict[str, str], section: str | None = None) -> dict[str, str]:
    """Load non-empty prompt overrides, preserving defaults for missing values."""
    prompts = dict(defaults)
    if not path.exists():
        return prompts

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return prompts

    if section:
        payload = payload.get(section, {}) if isinstance(payload, dict) else {}

    if not isinstance(payload, dict):
        return prompts

    for key, default_value in defaults.items():
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            prompts[key] = value.strip()
        else:
            prompts[key] = default_value
    return prompts

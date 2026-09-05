"""LaTeX rendering and compilation adapter."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_ENV_TOKEN_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def render_env_placeholders(text: str, repo_root: Path) -> str:
    values = dict(os.environ)
    for env_path in (Path.cwd() / ".env", repo_root / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values.setdefault(key.strip(), value.strip().strip("\"").strip("'"))
    return _ENV_TOKEN_PATTERN.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def page_count(pdf_path: str) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if not pdf_path or not pdfinfo:
        return None
    result = subprocess.run([pdfinfo, pdf_path], capture_output=True, text=True)
    match = re.search(r"(?m)^Pages:\s*(\d+)", result.stdout) if result.returncode == 0 else None
    return int(match.group(1)) if match else None

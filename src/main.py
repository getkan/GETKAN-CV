"""Backward-compatible launcher for the CLI application."""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

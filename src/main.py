"""Backward-compatible launcher for the CLI application."""

from src.cli import *


if __name__ == "__main__":
    raise SystemExit(main())

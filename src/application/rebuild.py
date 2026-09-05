"""Rebuild workflow boundary.

The CLI currently owns command dispatch and delegates packet parsing and tailoring
through the application services. This module reserves the explicit rebuild
workflow boundary for callers that do not use the command line.
"""

from __future__ import annotations

from pathlib import Path


def output_directory_for_packet(packet_path: str | Path, output_root: str | Path) -> Path:
    """Return the generated-output directory corresponding to a job packet."""
    path = Path(packet_path)
    return Path(output_root) / path.parent.name

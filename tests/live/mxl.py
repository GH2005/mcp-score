"""MusicXML snapshot helpers for the live suite.

The parsing/diffing core lives in :mod:`mcp_score.musicxml` (it is also
the production read path); this module re-exports it and adds the
machine-local PNG renderer used for visual spot checks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mcp_score.musicxml import (
    Snapshot,
    diff_snapshots,
    get_measure,
    measure_of_key,
    parse_snapshot,
)

__all__ = [
    "MUSESCORE_EXE",
    "Snapshot",
    "diff_snapshots",
    "get_measure",
    "measure_of_key",
    "parse_snapshot",
    "render_png",
]

MUSESCORE_EXE = Path("C:/Program Files/MuseScore 4/bin/MuseScore4.exe")


def render_png(musicxml_path: Path, out_png: Path, dpi: int = 130) -> list[Path]:
    """Render a MusicXML file to PNG page images via the MuseScore CLI.

    Works while the MuseScore GUI is open. Returns the per-page PNG paths
    (MuseScore appends -1, -2, ... to the requested name).
    """
    subprocess.run(
        [
            str(MUSESCORE_EXE),
            str(musicxml_path),
            "-o",
            str(out_png),
            "-r",
            str(dpi),
            "--force",
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    return sorted(out_png.parent.glob(f"{out_png.stem}-*{out_png.suffix}"))

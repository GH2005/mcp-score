"""exportScore: the ground-truth snapshot command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.live import mxl
from tests.live.conftest import ARTIFACTS_DIR

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge

pytestmark = pytest.mark.anyio


async def test_export_musicxml_writes_parseable_file(
    bridge: MuseScoreBridge,
) -> None:
    path = ARTIFACTS_DIR / "export-basic.musicxml"
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    reply = await bridge.send_command(
        "exportScore", {"path": path.as_posix(), "format": "musicxml"}
    )
    assert reply.get("result", {}).get("written") is True, f"export failed: {reply}"
    assert path.exists() and path.stat().st_size > 0

    snap = mxl.parse_snapshot(path)
    assert snap["measure_count"] >= 1
    assert len(snap["staves"]) >= 1


async def test_export_path_with_spaces(bridge: MuseScoreBridge) -> None:
    target_dir = ARTIFACTS_DIR / "dir with spaces"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "export spaced.musicxml"
    reply = await bridge.send_command(
        "exportScore", {"path": path.as_posix(), "format": "musicxml"}
    )
    assert reply.get("result", {}).get("written") is True, f"export failed: {reply}"
    assert path.exists() and path.stat().st_size > 0


async def test_export_missing_path_returns_error(bridge: MuseScoreBridge) -> None:
    reply = await bridge.send_command("exportScore", {"format": "musicxml"})
    assert "error" in reply
    assert "path" in reply["error"]


async def test_export_mscz_is_rejected(bridge: MuseScoreBridge) -> None:
    reply = await bridge.send_command(
        "exportScore",
        {"path": (ARTIFACTS_DIR / "never.mscz").as_posix(), "format": "mscz"},
    )
    assert "error" in reply
    assert "broken" in reply["error"]


async def test_cli_render_png_while_gui_open(bridge: MuseScoreBridge) -> None:
    """MuseScore's CLI converts a snapshot to PNG even while the GUI runs."""
    source = ARTIFACTS_DIR / "render-source.musicxml"
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    reply = await bridge.send_command(
        "exportScore", {"path": source.as_posix(), "format": "musicxml"}
    )
    assert reply.get("result", {}).get("written") is True

    pages = mxl.render_png(source, ARTIFACTS_DIR / "render-check.png")
    assert pages, "no PNG pages produced"
    assert all(p.stat().st_size > 0 for p in pages)

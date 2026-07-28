"""Order-sensitive baseline probes that must run before any other live test.

File is named test_00_* so pytest collects it first: the no-selection
transpose test is only meaningful before any other test has created a
selection (the plugin has no clear-selection command).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge

pytestmark = pytest.mark.anyio


async def test_ping_returns_pong(bridge: MuseScoreBridge) -> None:
    reply = await bridge.send_command("ping")
    assert reply == {"result": "pong"}


async def test_wire_transpose_is_gone(bridge: MuseScoreBridge) -> None:
    """Transposition moved to the server, which spells it with music21.

    The plugin holds no music theory: it applies pitch + tpc edits via
    setPitches and nothing else.
    """
    reply = await bridge.send_command("transpose", {"semitones": 1})
    assert "error" in reply
    assert "Unknown command" in reply["error"]


async def test_get_score_reports_expected_shape(bridge: MuseScoreBridge) -> None:
    reply = await bridge.get_score()
    result = reply["result"]
    assert set(result) >= {
        "title",
        "partCount",
        "parts",
        "measureCount",
        "keySignature",
        "timeSignature",
    }
    assert result["partCount"] == len(result["parts"])
    assert result["measureCount"] >= 1
    for part in result["parts"]:
        assert "name" in part


def _plugin_version_on_disk() -> str:
    """The version declared by the QML source in this working tree."""
    qml = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "mcp_score"
        / "musescore"
        / "mcp-score-bridge.qml"
    )
    # Explicit encoding: the default is the system codepage, which is GBK
    # on this machine and cannot decode the QML's non-ASCII characters.
    source = qml.read_text(encoding="utf-8")
    match = re.search(r'^\s*version:\s*"([^"]+)"', source, re.MULTILINE)
    assert match, f"no version declared in {qml}"
    return match.group(1)


async def test_get_score_reports_plugin_version(
    bridge: MuseScoreBridge,
) -> None:
    """Stale-plugin detection: the RUNNING plugin must be the one on disk.

    Compared against the QML source rather than a literal. A hardcoded
    version turns every plugin bump into a spurious failure, which trains
    everyone to ignore the one check that catches a MuseScore still
    running yesterday's plugin -- the failure mode that silently
    invalidates every other result in this suite.
    """
    expected = _plugin_version_on_disk()
    reply = await bridge.get_score()
    running = reply["result"].get("pluginVersion")

    assert running == expected, (
        f"MuseScore is running plugin {running} but the working tree has "
        f"{expected}. Restart MuseScore and relaunch the "
        f"mcp-score-bridge dock, or every result in this suite is stale."
    )


async def test_get_score_parts_include_staff_ranges(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.get_score()
    for part in reply["result"]["parts"]:
        assert set(part) >= {"name", "startStaff", "endStaff"}

"""Order-sensitive baseline probes that must run before any other live test.

File is named test_00_* so pytest collects it first: the no-selection
transpose test is only meaningful before any other test has created a
selection (the plugin has no clear-selection command).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge

pytestmark = pytest.mark.anyio


async def test_ping_returns_pong(bridge: MuseScoreBridge) -> None:
    reply = await bridge.send_command("ping")
    assert reply == {"result": "pong"}


async def test_transpose_without_selection_returns_error(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.send_command("transpose", {"semitones": 1})
    assert "error" in reply
    assert "No active selection" in reply["error"]


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


async def test_get_score_reports_plugin_version(
    bridge: MuseScoreBridge,
) -> None:
    """Stale-plugin detection: getScore must carry the plugin version."""
    reply = await bridge.get_score()
    assert reply["result"].get("pluginVersion") == "0.2.0"


@pytest.mark.xfail(
    reason="Part.startStaff/endStaff are undefined in MuseScore 4.7.4's "
    "plugin API (MuseScore 3 properties); JSON.stringify drops them, so "
    "getScore parts carry only 'name'. Probing startTrack/endTrack as a "
    "replacement (apiProbe).",
    strict=True,
)
async def test_get_score_parts_include_staff_ranges(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.get_score()
    for part in reply["result"]["parts"]:
        assert set(part) >= {"name", "startStaff", "endStaff"}

"""Read and navigation wire commands verified against exported ground truth."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio


async def test_get_score_matches_export(
    bridge: MuseScoreBridge, snapshot: SnapshotFn
) -> None:
    reply = await bridge.get_score()
    result = reply["result"]
    snap = await snapshot("getscore")
    assert result["measureCount"] == snap["measure_count"]
    first_measure = mxl.get_measure(snap, 0, 1)
    assert first_measure is not None
    if "key" in first_measure:
        assert result["keySignature"] == first_measure["key"][0]
    if "time" in first_measure and result["timeSignature"] is not None:
        numerator = result["timeSignature"]["numerator"]
        denominator = result["timeSignature"]["denominator"]
        assert f"{numerator}/{denominator}" == first_measure["time"][0]


async def test_go_to_measure_valid_and_bounds(bridge: MuseScoreBridge) -> None:
    reply = await bridge.go_to_measure(2)
    assert reply["result"]["measure"] == 2

    reply = await bridge.go_to_measure(0)
    assert "error" in reply
    assert "out of range" in reply["error"]

    info = await bridge.get_score()
    beyond = int(info["result"]["measureCount"]) + 1
    reply = await bridge.go_to_measure(beyond)
    assert "error" in reply
    assert "out of range" in reply["error"]


async def test_go_to_staff_valid_and_bounds(bridge: MuseScoreBridge) -> None:
    reply = await bridge.go_to_staff(0)
    assert reply["result"]["staff"] == 0
    reply = await bridge.go_to_staff(1)
    assert reply["result"]["staff"] == 1

    reply = await bridge.go_to_staff(99)
    assert "error" in reply
    assert "out of range" in reply["error"]

    await bridge.go_to_staff(0)


async def test_get_cursor_info_reports_element_at_measure(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    await bridge.go_to_staff(0)
    await bridge.go_to_measure(start)
    reply = await bridge.add_note(60, {"numerator": 1, "denominator": 4})
    assert "result" in reply, f"addNote failed: {reply}"

    await bridge.go_to_measure(start)
    info = await bridge.get_cursor_info()
    result = info["result"]
    assert result["measure"] == start
    assert result["staff"] == 0
    element = result["element"]
    assert element is not None, "cursor element missing at a measure with a note"
    assert [n["pitch"] for n in element.get("notes", [])] == [60]


@pytest.mark.xfail(
    reason="cursor.timeSignature is undefined in MuseScore 4.7.4, so the "
    "plugin's beat computation is skipped and beat is always null. "
    "Plugin fix planned (PR5).",
    strict=True,
)
async def test_get_cursor_info_computes_beat(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    await bridge.go_to_staff(0)
    await bridge.go_to_measure(start)
    info = await bridge.get_cursor_info()
    assert info["result"]["beat"] == 1


@pytest.mark.xfail(
    reason="note.noteName is undefined in MuseScore 4.7.4, so element note "
    "names are always null in getCursorInfo replies. Plugin fix planned "
    "(PR5, derive the name from pitch/tpc instead).",
    strict=True,
)
async def test_get_cursor_info_reports_note_names(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    await bridge.go_to_staff(0)
    await bridge.go_to_measure(start)
    reply = await bridge.add_note(60, {"numerator": 1, "denominator": 4})
    assert "result" in reply, f"addNote failed: {reply}"

    await bridge.go_to_measure(start)
    info = await bridge.get_cursor_info()
    element = info["result"]["element"]
    assert element is not None
    assert [n["name"] for n in element.get("notes", [])] == ["C4"]

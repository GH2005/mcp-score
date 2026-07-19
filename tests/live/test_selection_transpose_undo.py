"""Selection, transposition, and undo semantics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}

XFAIL_TRANSPOSE = pytest.mark.xfail(
    reason="curScore.transpose() does not exist in MuseScore 4.7.4 -- the "
    "plugin gets \"Property 'transpose' of object Score is not a "
    'function", so every transposition path is broken. Reimplementation '
    "planned (PR5).",
    strict=True,
)

XFAIL_UNDO = pytest.mark.xfail(
    reason="cmd('undo') is a silent no-op from the dock-plugin context in "
    "MuseScore 4.7.4: the plugin reports ok but the edit stays in the "
    "score. Fix planned (PR5).",
    strict=True,
)


async def _at(bridge: MuseScoreBridge, measure: int, staff: int = 0) -> None:
    assert "result" in await bridge.go_to_staff(staff)
    assert "result" in await bridge.go_to_measure(measure)


@XFAIL_TRANSPOSE
async def test_select_current_measure_then_transpose(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    before = await snapshot("selcur-before")

    await _at(bridge, start)
    reply = await bridge.send_command("selectCurrentMeasure")
    assert "result" in reply, f"selectCurrentMeasure failed: {reply}"
    reply = await bridge.send_command("transpose", {"semitones": 1})
    assert reply.get("result", {}).get("semitones") == 1

    after = await snapshot("selcur-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    notes = [
        e for e in changes[f"s0m{start}"]["after"]["events"] if e["kind"] != "rest"
    ]
    assert [e["midi"] for e in notes] == [[61]]
    assert notes[0]["names"] == ["C#4"], "expected sharp spelling for +1 from C"


@XFAIL_TRANSPOSE
async def test_select_custom_range_then_transpose_confined(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, end = await scratch(3)  # third measure stays untouched as a control
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    await _at(bridge, start + 1)
    assert "result" in await bridge.add_note(62, QUARTER)
    await _at(bridge, end)
    assert "result" in await bridge.add_note(64, QUARTER)
    before = await snapshot("selrange-before")

    reply = await bridge.send_command(
        "selectCustomRange",
        {
            "startMeasure": start,
            "endMeasure": start + 1,
            "startStaff": 0,
            "endStaff": 0,
        },
    )
    assert "result" in reply, f"selectCustomRange failed: {reply}"
    reply = await bridge.send_command("transpose", {"semitones": 2})
    assert "result" in reply, f"transpose failed: {reply}"

    after = await snapshot("selrange-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}", f"s0m{start + 1}"}, (
        f"transpose leaked outside the selected range: {set(changes)}"
    )
    for measure, expected_midi in ((start, 62), (start + 1, 64)):
        notes = [
            e
            for e in changes[f"s0m{measure}"]["after"]["events"]
            if e["kind"] != "rest"
        ]
        assert [e["midi"] for e in notes] == [[expected_midi]]


async def test_select_custom_range_invalid_ranges_return_errors(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.send_command(
        "selectCustomRange",
        {"startMeasure": 5, "endMeasure": 2, "startStaff": 0, "endStaff": 0},
    )
    assert "error" in reply
    assert "Invalid measure range" in reply["error"]

    reply = await bridge.send_command(
        "selectCustomRange",
        {"startMeasure": 1, "endMeasure": 2, "startStaff": 0, "endStaff": 99},
    )
    assert "error" in reply
    assert "Invalid staff range" in reply["error"]

    reply = await bridge.send_command("selectCustomRange", {"startMeasure": 1})
    assert "error" in reply
    assert "Missing required parameters" in reply["error"]


@XFAIL_TRANSPOSE
async def test_transpose_octave_up(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    before = await snapshot("octave-before")

    await _at(bridge, start)
    assert "result" in await bridge.send_command("selectCurrentMeasure")
    reply = await bridge.send_command("transpose", {"semitones": 13})
    assert "result" in reply, f"transpose failed: {reply}"

    after = await snapshot("octave-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}
    notes = [
        e for e in changes[f"s0m{start}"]["after"]["events"] if e["kind"] != "rest"
    ]
    assert [e["midi"] for e in notes] == [[73]], "expected C4 + 13 semitones = C#5"


@XFAIL_UNDO
async def test_undo_reverts_simple_add_note(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("undo-simple-before")

    assert "result" in await bridge.add_note(60, QUARTER)
    reply = await bridge.undo()
    assert reply == {"result": "ok"}

    after = await snapshot("undo-simple-after")
    changes = mxl.diff_snapshots(before, after)
    assert changes == {}, (
        f"undo did not restore the score; residual delta: {set(changes)}"
    )


@XFAIL_UNDO
async def test_undo_reverts_last_edit_despite_intervening_selection(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """The killer test: a selection between the edit and the undo must not
    swallow the undo (selections are not edits)."""
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("undo-sel-before")

    assert "result" in await bridge.add_note(60, QUARTER)
    reply = await bridge.send_command(
        "selectCustomRange",
        {
            "startMeasure": start,
            "endMeasure": start,
            "startStaff": 0,
            "endStaff": 0,
        },
    )
    assert "result" in reply
    reply = await bridge.undo()
    assert reply == {"result": "ok"}

    after = await snapshot("undo-sel-after")
    changes = mxl.diff_snapshots(before, after)
    assert changes == {}, (
        "undo after a selection did not remove the note -- the selection "
        f"polluted the undo stack; residual delta: {set(changes)}"
    )

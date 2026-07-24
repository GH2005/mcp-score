"""Selection, transposition, and undo semantics."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mcp_score.tools.manipulation import transpose_passage
from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}

XFAIL_UNDO = pytest.mark.xfail(
    reason="cmd('undo') is a silent no-op from the dock-plugin context in "
    "MuseScore 4.7.4: the plugin reports ok but the edit stays in the "
    "score. Fix planned (PR5).",
    strict=True,
)


async def _at(bridge: MuseScoreBridge, measure: int, staff: int = 0) -> None:
    assert "result" in await bridge.go_to_staff(staff)
    assert "result" in await bridge.go_to_measure(measure)


async def test_transpose_range_single_measure(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    before = await snapshot("selcur-before")

    reply = json.loads(await transpose_passage(start, start, 0, 1))
    assert reply.get("success") is True, f"transpose_passage: {reply}"
    assert reply["notes_transposed"] >= 1

    after = await snapshot("selcur-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    notes = [
        e for e in changes[f"s0m{start}"]["after"]["events"] if e["kind"] != "rest"
    ]
    assert [e["midi"] for e in notes] == [[61]]
    assert notes[0]["names"] == ["C#4"], "expected sharp spelling for +1 from C"


async def test_transpose_range_confined_to_range(
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

    reply = json.loads(await transpose_passage(start, start + 1, 0, 2))
    assert reply.get("success") is True, f"transpose_passage failed: {reply}"

    after = await snapshot("selrange-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}", f"s0m{start + 1}"}, (
        f"transpose leaked outside the requested range: {set(changes)}"
    )
    for measure, expected_midi in ((start, 62), (start + 1, 64)):
        notes = [
            e
            for e in changes[f"s0m{measure}"]["after"]["events"]
            if e["kind"] != "rest"
        ]
        assert [e["midi"] for e in notes] == [[expected_midi]]


async def test_transpose_into_a_flat_key_spells_flats(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """The point of routing transposition through music21.

    A fixed per-semitone table sharpens everything; music21 picks the
    spelling that suits the interval. G + 3 semitones is B-flat, not
    A-sharp.
    """
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(67, QUARTER)  # G4
    before = await snapshot("flatkey-before")

    reply = json.loads(await transpose_passage(start, start, 0, 3))
    assert reply.get("success") is True, f"transpose_passage failed: {reply}"

    after = await snapshot("flatkey-after")
    changes = mxl.diff_snapshots(before, after)
    notes = [
        e for e in changes[f"s0m{start}"]["after"]["events"] if e["kind"] != "rest"
    ]
    assert [e["midi"] for e in notes] == [[70]]
    assert notes[0]["names"] == ["B-4"], "expected B-flat, not A-sharp"


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


async def test_transpose_octave_up(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    before = await snapshot("octave-before")

    reply = json.loads(await transpose_passage(start, start, 0, 13))
    assert reply.get("success") is True, f"transpose_passage failed: {reply}"

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

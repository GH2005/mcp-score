"""processSequence: atomic batch execution with rollback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}
HALF = {"numerator": 1, "denominator": 2}


def _add_note_step(pitch: int, duration: dict[str, int]) -> dict[str, Any]:
    return {"action": "addNote", "params": {"pitch": pitch, "duration": duration}}


async def test_sequence_writes_contiguous_notes_across_measures(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    first, second = await scratch(2)
    before = await snapshot("seq-before")

    reply = await bridge.process_sequence(
        [
            {"action": "goToStaff", "params": {"staff": 0}},
            {"action": "goToMeasure", "params": {"measure": first}},
            _add_note_step(60, QUARTER),
            _add_note_step(62, QUARTER),
            {"action": "goToMeasure", "params": {"measure": second}},
            _add_note_step(64, HALF),
            _add_note_step(65, HALF),
        ]
    )
    result = reply.get("result")
    assert result is not None, f"processSequence failed: {reply}"
    assert result["count"] == 7

    after = await snapshot("seq-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{first}", f"s0m{second}"}, (
        f"unexpected delta: {set(changes)}"
    )

    first_notes = [
        e for e in changes[f"s0m{first}"]["after"]["events"] if e["kind"] != "rest"
    ]
    assert [(e["offset"], e["midi"]) for e in first_notes] == [
        (0.0, [60]),
        (1.0, [62]),
    ], f"measure {first}: {first_notes}"

    second_notes = [
        e for e in changes[f"s0m{second}"]["after"]["events"] if e["kind"] != "rest"
    ]
    assert [(e["offset"], e["midi"]) for e in second_notes] == [
        (0.0, [64]),
        (2.0, [65]),
    ], f"measure {second}: {second_notes}"


@pytest.mark.xfail(
    reason="processSequence rollback relies on cmd('undo'), which is a silent "
    "no-op from the dock-plugin context in MuseScore 4.7.4 -- a failed "
    "sequence leaves its earlier steps applied to the score. Fix planned "
    "(PR5).",
    strict=True,
)
async def test_sequence_rollback_leaves_no_trace(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    before = await snapshot("seqroll-before")

    reply = await bridge.process_sequence(
        [
            {"action": "goToStaff", "params": {"staff": 0}},
            {"action": "goToMeasure", "params": {"measure": start}},
            _add_note_step(60, QUARTER),
            {"action": "goToMeasure", "params": {"measure": 999999}},
        ]
    )
    assert "error" in reply, f"expected failure, got: {reply}"
    assert reply["failedIndex"] == 3
    assert reply["failedAction"] == "goToMeasure"

    after = await snapshot("seqroll-after")
    changes = mxl.diff_snapshots(before, after)
    assert changes == {}, f"rollback left residue in the score: {set(changes)}"


async def test_sequence_empty_returns_empty_result(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.process_sequence([])
    assert reply == {"result": {"results": [], "count": 0}}


async def test_sequence_missing_action_field_fails_cleanly(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    before = await snapshot("seqbad-before")

    reply = await bridge.process_sequence(
        [
            {"action": "goToMeasure", "params": {"measure": start}},
            {"params": {"pitch": 60}},
        ]
    )
    assert "error" in reply
    assert reply["failedIndex"] == 1

    after = await snapshot("seqbad-after")
    assert mxl.diff_snapshots(before, after) == {}

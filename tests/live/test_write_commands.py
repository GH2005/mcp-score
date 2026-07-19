"""Mutating wire commands verified by delta-scoped MusicXML diffs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}


def _barline_values(measure_dict: dict[str, Any] | None) -> set[str]:
    if measure_dict is None:
        return set()
    values = {measure_dict.get("barline"), measure_dict.get("barline_left")}
    return {v for v in values if v is not None}


async def _at(bridge: MuseScoreBridge, measure: int, staff: int = 0) -> None:
    reply = await bridge.go_to_staff(staff)
    assert "result" in reply, f"goToStaff failed: {reply}"
    reply = await bridge.go_to_measure(measure)
    assert "result" in reply, f"goToMeasure failed: {reply}"


async def test_add_note_writes_single_note(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("addnote-before")

    reply = await bridge.add_note(60, QUARTER)
    assert reply.get("result", {}).get("pitch") == 60

    after = await snapshot("addnote-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    events = changes[f"s0m{start}"]["after"]["events"]
    first = events[0]
    assert first["kind"] == "note"
    assert first["midi"] == [60]
    assert first["offset"] == 0.0
    assert first["ql"] == 1.0


async def test_add_note_consecutive_notes_accumulate(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """Two addNote commands in one measure must produce two notes in order."""
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("addnote2-before")

    assert "result" in await bridge.add_note(60, QUARTER)
    assert "result" in await bridge.add_note(64, QUARTER)

    after = await snapshot("addnote2-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}
    events = changes[f"s0m{start}"]["after"]["events"]
    notes = [e for e in events if e["kind"] != "rest"]
    assert [(e["offset"], e["midi"]) for e in notes] == [
        (0.0, [60]),
        (1.0, [64]),
    ], f"expected C4 then E4 as separate beats, got: {notes}"


async def test_add_note_invalid_pitch_returns_error(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    reply = await bridge.add_note(200, QUARTER)
    assert "error" in reply
    assert "0-127" in reply["error"]


async def test_add_rehearsal_mark(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("rehearsal-before")

    reply = await bridge.add_rehearsal_mark("LIVE-T1")
    assert reply.get("result", {}).get("text") == "LIVE-T1"

    after = await snapshot("rehearsal-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}
    assert changes[f"s0m{start}"]["after"].get("rehearsal") == ["LIVE-T1"]


@pytest.mark.skip(
    reason="setBarline crashes MuseScore Studio 4.7.4 (verified: process "
    "death). The plugin now refuses it without __experimental=true; this "
    "mutation test stays skipped until a safe implementation exists."
)
@pytest.mark.parametrize(
    ("wire_type", "expected"),
    [
        ("double", "double"),
        ("final", "final"),
        ("dashed", "dashed"),
        ("startRepeat", "repeat-start"),
        ("endRepeat", "repeat-end"),
    ],
)
async def test_set_barline(
    bridge: MuseScoreBridge,
    scratch: ScratchFn,
    snapshot: SnapshotFn,
    wire_type: str,
    expected: str,
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot(f"barline-{wire_type}-before")

    reply = await bridge.set_barline(wire_type)
    assert reply.get("result", {}).get("type") == wire_type

    after = await snapshot(f"barline-{wire_type}-after")
    changes = mxl.diff_snapshots(before, after)
    allowed = {f"s0m{start}", f"s1m{start}"}
    assert set(changes) <= allowed and changes, f"unexpected delta: {set(changes)}"
    assert expected in _barline_values(changes[f"s0m{start}"]["after"]), (
        f"barline {expected!r} not found in measure {start}: "
        f"{changes[f's0m{start}']['after']}"
    )


async def test_set_barline_without_experimental_flag_is_refused(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    """The crasher commands must refuse to run unless explicitly forced."""
    start, _ = await scratch(1)
    await _at(bridge, start)
    reply = await bridge.set_barline("double")
    assert "error" in reply
    assert "crashes MuseScore" in reply["error"]

    reply = await bridge.add_chord_symbol("Cmaj7")
    assert "error" in reply
    assert "crashes" in reply["error"]

    reply = await bridge.add_dynamic("mf")
    assert "error" in reply
    assert "crashes" in reply["error"]


async def test_set_barline_unknown_type_returns_error(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    reply = await bridge.set_barline("bogus")
    assert "error" in reply
    assert "Unknown barline type" in reply["error"]
    assert "double" in reply["error"]  # error lists the valid types


@pytest.mark.xfail(
    reason="setKeySignature writes the wrong key in MuseScore 4.7.4: "
    "requesting fifths=2 produced fifths=-8 in the exported score (the "
    "KEYSIG element's key property maps differently in MS4). Fix "
    "planned (PR5).",
    strict=True,
)
async def test_set_key_signature(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("keysig-before")

    reply = await bridge.set_key_signature(2)
    assert reply.get("result", {}).get("fifths") == 2

    after = await snapshot("keysig-after")
    changes = mxl.diff_snapshots(before, after)
    # Key signatures apply to every staff; a courtesy signature may also
    # appear at the end of the preceding measure.
    allowed = {
        f"s{staff}m{measure}" for staff in (0, 1) for measure in (start - 1, start)
    }
    assert set(changes) <= allowed and changes, f"unexpected delta: {set(changes)}"
    assert changes[f"s0m{start}"]["after"].get("key") == [2]


async def test_set_key_signature_out_of_range_returns_error(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.set_key_signature(8)
    assert "error" in reply
    assert "between -7 and 7" in reply["error"]


async def test_set_time_signature(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    # Three scratch measures with the signature on the middle one, so
    # courtesy-signature side effects on neighbours stay inside the
    # scratch window even when earlier runs left signatures nearby.
    start, end = await scratch(3)
    target = start + 1
    await _at(bridge, target)
    before = await snapshot("timesig-before")

    reply = await bridge.set_time_signature(3, 4)
    assert reply.get("result", {}).get("numerator") == 3

    after = await snapshot("timesig-after")
    changes = mxl.diff_snapshots(before, after)
    assert changes, "setTimeSignature produced no change"
    for change_key in changes:
        if change_key == "measure_count":
            continue
        assert mxl.measure_of_key(change_key) >= start, (
            f"delta leaked before the scratch range: {set(changes)}"
        )
    assert changes[f"s0m{target}"]["after"].get("time") == ["3/4"]
    events = changes[f"s0m{target}"]["after"]["events"]
    assert sum(e["ql"] for e in events) == pytest.approx(3.0)


@pytest.mark.xfail(
    reason="setTempo produces an empty metronome mark in MuseScore "
    "4.7.4: the exported score has a tempo entry with no number and no "
    "text (TEMPO_TEXT text/tempo properties do not take effect). Fix "
    "planned (PR5).",
    strict=True,
)
async def test_set_tempo(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("tempo-before")

    reply = await bridge.set_tempo(88, "Andante test")
    assert reply.get("result", {}).get("bpm") == 88

    after = await snapshot("tempo-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    marks = changes[f"s0m{start}"]["after"].get("tempo", [])
    assert any(
        mark.get("number") == 88 or mark.get("text") == "Andante test" for mark in marks
    ), f"tempo mark not found: {marks}"


@pytest.mark.skip(
    reason="addChordSymbol crashes MuseScore Studio 4.7.4; the plugin now "
    "refuses it without __experimental=true (gate covered by "
    "test_set_barline_without_experimental_flag_is_refused). Re-enable "
    "once a safe implementation exists."
)
async def test_add_chord_symbol(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("chordsym-before")

    reply = await bridge.add_chord_symbol("Cmaj7")
    assert reply.get("result", {}).get("text") == "Cmaj7"

    after = await snapshot("chordsym-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    figures = changes[f"s0m{start}"]["after"].get("harmony", [])
    assert figures and figures[0].startswith("C"), f"harmony not found: {figures}"


@pytest.mark.skip(
    reason="addDynamic shares the crashing newElement+cursor.add pattern; "
    "the plugin now refuses it without __experimental=true (gate covered "
    "by test_set_barline_without_experimental_flag_is_refused). Re-enable "
    "once a safe implementation exists."
)
async def test_add_dynamic(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    before = await snapshot("dynamic-before")

    await _at(bridge, start)
    reply = await bridge.add_dynamic("mf")
    assert reply.get("result", {}).get("type") == "mf"

    after = await snapshot("dynamic-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    assert changes[f"s0m{start}"]["after"].get("dynamics") == ["mf"]


async def test_append_measures(bridge: MuseScoreBridge, snapshot: SnapshotFn) -> None:
    info = await bridge.get_score()
    count = int(info["result"]["measureCount"])
    await snapshot("append-before")

    reply = await bridge.append_measures(2)
    assert reply.get("result", {}).get("totalMeasures") == count + 2

    after = await snapshot("append-after")
    assert after["measure_count"] == count + 2
    for measure in (count + 1, count + 2):
        for staff in (0, 1):
            measure_dict = mxl.get_measure(after, staff, measure)
            assert measure_dict is not None
            kinds = {e["kind"] for e in measure_dict["events"]}
            assert kinds == {"rest"}, (
                f"new measure {measure} staff {staff} not empty: {kinds}"
            )


async def test_append_measures_invalid_count_returns_error(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.append_measures(0)
    assert "error" in reply
    assert "at least 1" in reply["error"]

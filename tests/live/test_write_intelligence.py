"""Voicing, diatonic motion, transformations, and ornaments, live.

Everything here is verified against exported MusicXML rather than a
command's reply, and scoped to freshly appended scratch measures so a
dirty score can neither fake a pass nor cause a failure.

These are all Python-side features: the plugin is unchanged at 0.3.0 and
every write rides the wire commands that already existed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mcp_score.tools.composition import realize_ornament, voice_progression
from mcp_score.tools.manipulation import (
    add_live_notes,
    transform_passage,
    transpose_passage,
)
from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}
HALF = {"numerator": 1, "denominator": 2}

#: Test motifs are three quarters long so they fill a 3/4 bar exactly and
#: still fit inside a 4/4 one. A run longer than the bar spills into the
#: next measure, which would put the delta outside the scratch range.
MOTIF_BEATS = 3


def _sounding(measure: dict[str, object]) -> list[dict[str, object]]:
    """Notes and chords of a measure, rests dropped."""
    events = measure["events"]
    assert isinstance(events, list)
    return [e for e in events if e["kind"] != "rest"]


def _names(measure: dict[str, object]) -> list[str]:
    """Every sounding note name in a measure, in time order."""
    written: list[str] = []
    for event in _sounding(measure):
        names = event["names"]
        assert isinstance(names, list)
        written.extend(names)
    return written


async def _write(
    start: int, notes: list[dict[str, object]], staff: int = 0, voice: int = 0
) -> None:
    reply = json.loads(await add_live_notes(start, staff, notes, voice))
    assert "error" not in reply, f"add_live_notes failed: {reply}"


# ── Voicing a progression ────────────────────────────────────────────


async def test_voiced_progression_round_trip(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """Voiced chords go in and come back as chords, note for note."""
    planned = json.loads(await voice_progression(["I", "IV", "V7"], "C"))
    assert planned["success"] is True, planned
    assert planned["solution_count"] > 0

    start, _ = await scratch(1)
    before = await snapshot("voicing-before")

    await _write(start, planned["entries"]["chords"])

    after = await snapshot("voicing-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"

    events = _sounding(changes[f"s0m{start}"]["after"])
    assert len(events) == MOTIF_BEATS, "one chord per figure"
    for event, voiced in zip(events, planned["chords"], strict=True):
        assert event["kind"] == "chord"
        assert event["midi"] == sorted(p["midi"] for p in voiced["pitches"])


async def test_voiced_progression_keeps_flat_spellings(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """A progression voiced in E-flat must not come back with sharps."""
    planned = json.loads(await voice_progression(["I", "ii65", "V7"], "E-"))
    assert planned["success"] is True, planned

    start, _ = await scratch(1)
    before = await snapshot("voicing-flat-before")

    await _write(start, planned["entries"]["chords"])

    after = await snapshot("voicing-flat-after")
    changes = mxl.diff_snapshots(before, after)
    written = _names(changes[f"s0m{start}"]["after"])
    assert written, "nothing was written"
    assert not any("#" in name for name in written), written


async def test_grand_staff_split_covers_the_whole_texture(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """upper + bass together hold exactly what chords holds.

    The real handoff puts upper on one staff and bass on the other; on a
    score whose staff count is unknown this uses two voices of staff 0,
    which exercises the same split.
    """
    planned = json.loads(await voice_progression(["I", "V7", "I"], "C"))
    assert planned["success"] is True, planned

    start, _ = await scratch(1)
    before = await snapshot("grandstaff-before")

    await _write(start, planned["entries"]["upper"], voice=0)
    await _write(start, planned["entries"]["bass"], voice=1)

    after = await snapshot("grandstaff-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"

    written = sorted(_names(changes[f"s0m{start}"]["after"]))
    expected = sorted(
        p["name"] for voiced in planned["chords"] for p in voiced["pitches"]
    )
    assert written == expected


# ── Moving music within a key ────────────────────────────────────────


async def test_diatonic_transposition_stays_in_key(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """Up a third in C turns C D E into E F G, not E F# G#."""
    start, _ = await scratch(1)
    await _write(start, [{"name": n, **QUARTER} for n in ("C4", "D4", "E4")])
    before = await snapshot("diatonic-before")

    reply = json.loads(await transpose_passage(start, start, 0, degrees=2, key="C"))
    assert "error" not in reply, f"transpose_passage failed: {reply}"

    after = await snapshot("diatonic-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    assert _names(changes[f"s0m{start}"]["after"]) == ["E4", "F4", "G4"]


async def test_diatonic_transposition_spells_for_a_flat_key(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """In E-flat the answers are B-flat and E-flat, never A-sharp or D-sharp."""
    start, _ = await scratch(1)
    await _write(start, [{"name": n, **QUARTER} for n in ("G4", "C5")])
    before = await snapshot("diatonic-flat-before")

    reply = json.loads(await transpose_passage(start, start, 0, degrees=2, key="E-"))
    assert "error" not in reply, f"transpose_passage failed: {reply}"

    after = await snapshot("diatonic-flat-after")
    changes = mxl.diff_snapshots(before, after)
    assert _names(changes[f"s0m{start}"]["after"])[:2] == ["B-4", "E-5"]


async def test_chromatic_transposition_still_works(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """The semitones path is unchanged by the new degrees path."""
    start, _ = await scratch(1)
    await _write(start, [{"name": n, **QUARTER} for n in ("C4", "E4")])
    before = await snapshot("chromatic-before")

    reply = json.loads(await transpose_passage(start, start, 0, semitones=2))
    assert "error" not in reply, f"transpose_passage failed: {reply}"

    after = await snapshot("chromatic-after")
    changes = mxl.diff_snapshots(before, after)
    assert _names(changes[f"s0m{start}"]["after"])[:2] == ["D4", "F#4"]


async def test_transpose_rejects_both_modes_at_once(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """An ambiguous request must change nothing."""
    start, _ = await scratch(1)
    await _write(start, [{"name": "C4", **QUARTER}])
    before = await snapshot("bothmodes-before")

    reply = json.loads(
        await transpose_passage(start, start, 0, semitones=2, degrees=2, key="C")
    )
    assert "error" in reply

    after = await snapshot("bothmodes-after")
    assert mxl.diff_snapshots(before, after) == {}


# ── Transformations ──────────────────────────────────────────────────


async def test_invert_mirrors_around_the_axis(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _write(start, [{"name": n, **QUARTER} for n in ("C4", "E4", "G4")])
    before = await snapshot("invert-before")

    reply = json.loads(
        await transform_passage("invert", start, start, 0, key="C", axis="G4")
    )
    assert "error" not in reply, f"transform_passage failed: {reply}"

    after = await snapshot("invert-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    assert _names(changes[f"s0m{start}"]["after"]) == ["D5", "B4", "G4"]


async def test_retrograde_reverses_pitch_and_rhythm(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _write(start, [{"name": "C4", **QUARTER}, {"name": "D4", **HALF}])
    before = await snapshot("retrograde-before")

    reply = json.loads(await transform_passage("retrograde", start, start, 0))
    assert "error" not in reply, f"transform_passage failed: {reply}"

    after = await snapshot("retrograde-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"

    events = _sounding(changes[f"s0m{start}"]["after"])
    assert [e["names"] for e in events] == [["D4"], ["C4"]]
    assert [e["ql"] for e in events] == [2.0, 1.0], "the half note must lead now"


async def test_sequence_writes_shifted_copies_after_the_motif(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(3)
    await _write(start, [{"name": n, **QUARTER} for n in ("C4", "E4", "G4")])
    before = await snapshot("sequence-before")

    reply = json.loads(
        await transform_passage(
            "sequence", start, start, 0, key="C", copies=2, degrees=1
        )
    )
    assert "error" not in reply, f"transform_passage failed: {reply}"

    after = await snapshot("sequence-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start + 1}", f"s0m{start + 2}"}, (
        f"the motif itself must be untouched: {set(changes)}"
    )
    assert _names(changes[f"s0m{start + 1}"]["after"]) == ["D4", "F4", "A4"]
    assert _names(changes[f"s0m{start + 2}"]["after"]) == ["E4", "G4", "B4"]


async def test_sequence_beyond_the_score_end_changes_nothing(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await _write(start, [{"name": n, **QUARTER} for n in ("C4", "E4", "G4")])
    before = await snapshot("sequence-refuse-before")

    reply = json.loads(
        await transform_passage(
            "sequence", start, start, 0, key="C", copies=8, degrees=1
        )
    )
    assert "error" in reply
    assert "append_live_measures" in reply["error"]

    after = await snapshot("sequence-refuse-after")
    assert mxl.diff_snapshots(before, after) == {}


# ── Ornaments ────────────────────────────────────────────────────────


async def test_realized_trill_is_written_out(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """A trill on a quarter becomes eight thirty-seconds that fill it."""
    planned = json.loads(await realize_ornament("trill", "C5", "C"))
    assert planned["success"] is True, planned

    start, _ = await scratch(1)
    before = await snapshot("trill-before")

    await _write(start, planned["entries_for_add_live_notes"])

    after = await snapshot("trill-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"

    events = _sounding(changes[f"s0m{start}"]["after"])
    assert [e["names"] for e in events] == [["C5"], ["D5"]] * 4
    assert all(e["ql"] == 0.125 for e in events)
    assert sum(float(e["ql"]) for e in events) == 1.0, "the trill must fill the beat"


async def test_realized_mordent_follows_the_key(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """In E-flat the note below C is B-flat, and that is what lands."""
    planned = json.loads(await realize_ornament("mordent", "C5", "E-"))
    assert planned["success"] is True, planned

    start, _ = await scratch(1)
    before = await snapshot("mordent-before")

    await _write(start, planned["entries_for_add_live_notes"])

    after = await snapshot("mordent-after")
    changes = mxl.diff_snapshots(before, after)
    assert _names(changes[f"s0m{start}"]["after"])[:3] == ["C5", "B-4", "C5"]

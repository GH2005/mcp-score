"""Chords, voices, spelling, and the advisory analysis tools.

These cover the 0.3.0 write vocabulary: what the bridge could not do
before is a chord, a second voice, a rest, or a note whose enharmonic
spelling was chosen deliberately rather than guessed from the key
signature.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mcp_score.tools.analysis import analyze_passage, realize_harmony
from mcp_score.tools.manipulation import add_live_notes
from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}


def _sounding(measure: dict[str, object]) -> list[dict[str, object]]:
    """Notes and chords of a measure, rests dropped."""
    events = measure["events"]
    assert isinstance(events, list)
    return [e for e in events if e["kind"] != "rest"]


# ── Writing chords ───────────────────────────────────────────────────


async def test_add_to_chord_stacks_one_chord(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    before = await snapshot("chord-before")

    reply = json.loads(await add_live_notes(start, 0, [{"chord": ["C4", "E4", "G4"]}]))
    assert "error" not in reply, f"add_live_notes failed: {reply}"

    after = await snapshot("chord-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}"}, f"unexpected delta: {set(changes)}"
    notes = _sounding(changes[f"s0m{start}"]["after"])
    assert len(notes) == 1, "three simultaneous notes must be ONE chord event"
    assert notes[0]["kind"] == "chord"
    assert notes[0]["midi"] == [60, 64, 67]


async def test_chord_keeps_each_tone_spelled(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """An E-flat in the chord must not come back as a D-sharp."""
    start, _ = await scratch(1)
    before = await snapshot("chordspell-before")

    reply = json.loads(await add_live_notes(start, 0, [{"chord": ["C4", "E-4", "G4"]}]))
    assert "error" not in reply, f"add_live_notes failed: {reply}"

    after = await snapshot("chordspell-after")
    changes = mxl.diff_snapshots(before, after)
    notes = _sounding(changes[f"s0m{start}"]["after"])
    assert notes[0]["names"] == ["C4", "E-4", "G4"]


# ── Writing voices ───────────────────────────────────────────────────


async def test_second_voice_is_independent(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """Two voices on one staff -- the core of two-staff piano writing."""
    start, _ = await scratch(1)
    before = await snapshot("voice-before")

    upper = json.loads(await add_live_notes(start, 0, [{"name": "C5"}], voice=0))
    assert "error" not in upper, f"voice 0 write failed: {upper}"
    lower = json.loads(await add_live_notes(start, 0, [{"name": "G3"}], voice=1))
    assert "error" not in lower, f"voice 1 write failed: {lower}"

    after = await snapshot("voice-after")
    changes = mxl.diff_snapshots(before, after)
    notes = _sounding(changes[f"s0m{start}"]["after"])
    voices = {e.get("voice") for e in notes}
    assert len(voices) == 2, f"expected two voices, saw {voices}"
    # Both start at beat 1: they sound together rather than in sequence.
    assert all(e["offset"] == 0.0 for e in notes)
    assert sorted(m for e in notes for m in e["midi"]) == [55, 72]


# ── Spelling ─────────────────────────────────────────────────────────


async def test_named_note_keeps_its_flat_spelling(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    before = await snapshot("spell-before")

    reply = json.loads(await add_live_notes(start, 0, [{"name": "D-4"}]))
    assert "error" not in reply, f"add_live_notes failed: {reply}"

    after = await snapshot("spell-after")
    changes = mxl.diff_snapshots(before, after)
    notes = _sounding(changes[f"s0m{start}"]["after"])
    assert notes[0]["midi"] == [61]
    assert notes[0]["names"] == ["D-4"], "D-flat must not be respelled as C-sharp"


async def test_same_pitch_written_both_ways(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """MIDI 61 written as D-flat and as C-sharp must differ on the page."""
    start, end = await scratch(2)
    before = await snapshot("enharm-before")

    assert "error" not in json.loads(await add_live_notes(start, 0, [{"name": "D-4"}]))
    assert "error" not in json.loads(await add_live_notes(end, 0, [{"name": "C#4"}]))

    after = await snapshot("enharm-after")
    changes = mxl.diff_snapshots(before, after)
    flat = _sounding(changes[f"s0m{start}"]["after"])[0]
    sharp = _sounding(changes[f"s0m{end}"]["after"])[0]
    assert flat["midi"] == sharp["midi"] == [61]
    assert flat["names"] != sharp["names"]


async def test_bare_midi_is_spelled_for_the_given_key(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    before = await snapshot("keyspell-before")

    reply = json.loads(await add_live_notes(start, 0, [{"pitch": 68, "key": "E-"}]))
    assert "error" not in reply, f"add_live_notes failed: {reply}"

    after = await snapshot("keyspell-after")
    changes = mxl.diff_snapshots(before, after)
    notes = _sounding(changes[f"s0m{start}"]["after"])
    assert notes[0]["names"] == ["A-4"], "MIDI 68 in E-flat is A-flat, not G-sharp"


# ── Rests ────────────────────────────────────────────────────────────


async def test_add_rest_writes_a_rest(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    await bridge.go_to_staff(0, voice=0)
    await bridge.go_to_measure(start)
    reply = await bridge.add_rest(QUARTER)
    assert "error" not in reply, f"addRest failed: {reply}"
    assert reply["result"]["rest"] is True

    after = await snapshot("rest-after")
    events = after["staves"]["0"][str(start)]["events"]
    assert any(e["kind"] == "rest" for e in events)


# ── setPitches guards ────────────────────────────────────────────────


async def test_set_pitches_rejects_a_stale_request(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """Verification happens before any write, so nothing half-applies."""
    start, _ = await scratch(1)
    assert "error" not in json.loads(await add_live_notes(start, 0, [{"name": "C4"}]))
    before = await snapshot("stale-before")

    reply = await bridge.set_pitches(
        0, 0, start, start, [{"oldPitch": 99, "newPitch": 60, "newTpc": 14}]
    )
    assert "error" in reply

    after = await snapshot("stale-after")
    assert mxl.diff_snapshots(before, after) == {}, (
        "a rejected edit must change nothing"
    )


async def test_set_pitches_requires_a_spelling(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """MuseScore exports spelling, not MIDI: pitch without tpc corrupts."""
    start, _ = await scratch(1)
    assert "error" not in json.loads(await add_live_notes(start, 0, [{"name": "C4"}]))
    before = await snapshot("notpc-before")

    reply = await bridge.set_pitches(
        0, 0, start, start, [{"oldPitch": 60, "newPitch": 62}]
    )
    assert "error" in reply
    assert "newTpc" in reply["error"]

    after = await snapshot("notpc-after")
    assert mxl.diff_snapshots(before, after) == {}


# ── Advisory analysis ────────────────────────────────────────────────


async def test_realize_harmony_needs_no_score() -> None:
    reply = json.loads(await realize_harmony("V7/V", "E-", 4))
    assert reply["success"] is True
    assert reply["chord_for_add_live_notes"] == ["F4", "A4", "C5", "E-5"]


async def test_realized_chord_can_be_written_straight_back(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    """The round trip that makes the pair useful: figure -> notes -> score."""
    start, _ = await scratch(1)
    realized = json.loads(await realize_harmony("V7", "E-", 3))
    before = await snapshot("realize-before")

    reply = json.loads(
        await add_live_notes(
            start, 0, [{"chord": realized["chord_for_add_live_notes"]}]
        )
    )
    assert "error" not in reply, f"add_live_notes failed: {reply}"

    after = await snapshot("realize-after")
    changes = mxl.diff_snapshots(before, after)
    notes = _sounding(changes[f"s0m{start}"]["after"])
    # B-flat dominant 7 in E-flat: Bb D F Ab.
    assert notes[0]["names"] == ["A-4", "B-3", "D4", "F4"]


async def test_analyze_passage_reads_harmony_back(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    assert "error" not in json.loads(
        await add_live_notes(start, 0, [{"chord": ["B-3", "D4", "F4", "A-4"]}])
    )

    report = json.loads(await analyze_passage(start, start, key="E-"))
    assert report["success"] is True
    assert report["key"]["used_for_harmony"] == "E- major"
    figures = [entry["roman"] for entry in report["harmony"]]
    assert any(f and f.startswith("V") for f in figures), (
        f"expected a dominant reading of Bb7 in E-flat, got {figures}"
    )


async def test_analyze_passage_never_edits(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    assert "error" not in json.loads(await add_live_notes(start, 0, [{"name": "C4"}]))
    before = await snapshot("analyze-before")

    report = json.loads(await analyze_passage(start, start))
    assert report["success"] is True

    after = await snapshot("analyze-after")
    assert mxl.diff_snapshots(before, after) == {}, "analysis must be read-only"


async def test_analyze_passage_reports_parallel_fifths(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    """Reported as an observation -- never blocked, never corrected."""
    start, _ = await scratch(1)
    written = json.loads(
        await add_live_notes(
            start,
            0,
            [{"chord": ["G3", "D4"]}, {"chord": ["A3", "E4"]}],
        )
    )
    assert "error" not in written, f"add_live_notes failed: {written}"

    report = json.loads(await analyze_passage(start, start))
    assert report["success"] is True
    observations = [o["observation"] for o in report["voice_leading"]]
    assert "parallel fifths" in observations, f"saw {observations}"

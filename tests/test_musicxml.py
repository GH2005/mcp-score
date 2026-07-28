"""Tests for the MusicXML snapshot parser.

The snapshot is the project's ground truth: every write is verified
against one rather than against a command's reply. What it records is
therefore what the rest of the server is allowed to reason about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_score.musicxml import parse_snapshot

if TYPE_CHECKING:
    from pathlib import Path


def _write_score(path: Path, tie_the_first_pair: bool) -> None:
    """Write a one-part, one-measure score, optionally with a tie."""
    from music21 import meter, note, stream, tie

    measure = stream.Measure(number=1)
    measure.append(meter.TimeSignature("4/4"))
    first = note.Note("C4", quarterLength=2.0)
    second = note.Note("C4", quarterLength=2.0)
    if tie_the_first_pair:
        first.tie = tie.Tie("start")
        second.tie = tie.Tie("stop")
    measure.append(first)
    measure.append(second)
    part = stream.Part()
    part.append(measure)
    score = stream.Score()
    score.append(part)
    score.write("musicxml", fp=str(path))


class TestTieMarkers:
    """A tied note is only part of a note, and must be visible as such."""

    def test_tied_notes_carry_their_tie_type(self, tmp_path: Path) -> None:
        path = tmp_path / "tied.musicxml"
        _write_score(path, tie_the_first_pair=True)

        snapshot = parse_snapshot(path)

        events = snapshot["staves"]["0"]["1"]["events"]
        assert [event.get("tie") for event in events] == ["start", "stop"]

    def test_untied_notes_carry_no_tie_field(self, tmp_path: Path) -> None:
        path = tmp_path / "untied.musicxml"
        _write_score(path, tie_the_first_pair=False)

        snapshot = parse_snapshot(path)

        events = snapshot["staves"]["0"]["1"]["events"]
        assert all("tie" not in event for event in events)


def _write_score_with_mid_measure_clef(path: Path) -> None:
    """One measure whose second half switches to bass clef.

    This is the shape MuseScore's MIDI import produces when notes stray
    out of a staff's range mid-bar.
    """
    from music21 import clef, meter, note, stream

    measure = stream.Measure(number=1)
    measure.append(meter.TimeSignature("4/4"))
    measure.append(note.Note("C5", quarterLength=2.0))
    measure.insert(2.0, clef.BassClef())
    measure.insert(2.0, note.Note("C3", quarterLength=2.0))
    part = stream.Part()
    part.insert(0, clef.TrebleClef())
    part.append(measure)
    score = stream.Score()
    score.append(part)
    score.write("musicxml", fp=str(path))


class TestClefReporting:
    """Mid-measure clef changes must be visible, and locatable by offset.

    Without the offset there is no way to tell a normal staff-defining
    clef from a mid-measure change, and no way to address the change for
    removal.
    """

    def test_clefs_are_reported_with_offsets(self, tmp_path: Path) -> None:
        path = tmp_path / "midclef.musicxml"
        _write_score_with_mid_measure_clef(path)

        snapshot = parse_snapshot(path)

        clefs = snapshot["staves"]["0"]["1"]["clef"]
        assert [c["offset"] for c in clefs] == [0.0, 2.0]

    def test_mid_measure_clef_is_distinguishable_from_the_staff_clef(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "midclef2.musicxml"
        _write_score_with_mid_measure_clef(path)

        snapshot = parse_snapshot(path)

        clefs = snapshot["staves"]["0"]["1"]["clef"]
        mid = [c for c in clefs if c["offset"] > 0.0]
        assert len(mid) == 1
        assert mid[0]["sign"] == "BassClef"

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

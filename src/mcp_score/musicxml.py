"""MusicXML parsing and diffing -- the ground-truth read path.

MuseScore's plugin cursor API cannot reliably report score contents
(chords, voices, and anything past the first element of a measure are
invisible to it), but MuseScore's own MusicXML exporter is complete.
The accurate way to read the live score is therefore: snapshot it via
the plugin's ``exportScore`` command and parse the MusicXML here.

This module normalizes a MusicXML file into plain, JSON-serializable
dicts (via music21) and can diff two snapshots to verify that an edit
changed exactly what it claimed to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from music21 import (
    bar,
    chord,
    clef,
    converter,
    dynamics,
    expressions,
    harmony,
    key,
    note,
    stream,
    tempo,
)
from music21.meter.base import TimeSignature

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "Snapshot",
    "diff_snapshots",
    "get_measure",
    "measure_of_key",
    "parse_snapshot",
]

Snapshot = dict[str, Any]


def _events(measure: stream.Measure) -> list[dict[str, Any]]:
    """Normalize the notes, chords, and rests of one measure."""
    events: list[dict[str, Any]] = []
    for el in measure.recurse().notesAndRests:
        if isinstance(el, harmony.Harmony):
            continue  # chord symbols are reported separately
        entry: dict[str, Any] = {
            "offset": round(float(el.getOffsetInHierarchy(measure)), 4),
            "ql": round(float(el.duration.quarterLength), 4),
        }
        voice = el.getContextByClass(stream.Voice)
        if voice is not None:
            entry["voice"] = str(voice.id)
        if isinstance(el, chord.Chord):
            entry["kind"] = "chord" if len(el.pitches) > 1 else "note"
            entry["midi"] = sorted(p.midi for p in el.pitches)
            entry["names"] = sorted(p.nameWithOctave for p in el.pitches)
        elif isinstance(el, note.Note):
            entry["kind"] = "note"
            entry["midi"] = [el.pitch.midi]
            entry["names"] = [el.pitch.nameWithOctave]
        else:
            entry["kind"] = "rest"
        events.append(entry)
    events.sort(key=lambda e: (e["offset"], e.get("voice", ""), str(e.get("midi"))))
    return events


def _measure_info(measure: stream.Measure) -> dict[str, Any]:
    """Normalize one measure: events plus attributes and annotations."""
    info: dict[str, Any] = {"events": _events(measure)}

    clefs = [c.classes[0] for c in measure.getElementsByClass(clef.Clef)]
    if clefs:
        info["clef"] = clefs
    keys = [ks.sharps for ks in measure.recurse().getElementsByClass(key.KeySignature)]
    if keys:
        info["key"] = keys
    times = [
        ts.ratioString for ts in measure.recurse().getElementsByClass(TimeSignature)
    ]
    if times:
        info["time"] = times
    figures = [
        h.figure for h in measure.recurse().getElementsByClass(harmony.ChordSymbol)
    ]
    if figures:
        info["harmony"] = figures
    dyns = [d.value for d in measure.recurse().getElementsByClass(dynamics.Dynamic)]
    if dyns:
        info["dynamics"] = dyns
    marks = [
        {"number": mm.number, "text": mm.text}
        for mm in measure.recurse().getElementsByClass(tempo.MetronomeMark)
    ]
    if marks:
        info["tempo"] = marks
    rehearsals = [
        rm.content
        for rm in measure.recurse().getElementsByClass(expressions.RehearsalMark)
    ]
    if rehearsals:
        info["rehearsal"] = rehearsals

    right = measure.rightBarline
    if right is not None:
        if isinstance(right, bar.Repeat):
            info["barline"] = f"repeat-{right.direction}"
        else:
            info["barline"] = right.type
    left = measure.leftBarline
    if isinstance(left, bar.Repeat):
        info["barline_left"] = f"repeat-{left.direction}"

    return info


def parse_snapshot(path: Path) -> Snapshot:
    """Parse an exported MusicXML file into a normalized snapshot.

    Staves are keyed "0", "1", ... in part order (matching the plugin's
    0-indexed staff numbering); measures are keyed by measure number.
    """
    score = converter.parse(str(path))
    if not isinstance(score, stream.Score):
        raise ValueError(f"Expected a Score from {path}, got {type(score).__name__}")
    staves: dict[str, dict[str, Any]] = {}
    for staff_index, part in enumerate(score.parts):
        measures: dict[str, Any] = {}
        for m in part.getElementsByClass(stream.Measure):
            measures[str(m.number)] = _measure_info(m)
        staves[str(staff_index)] = measures

    title = None
    if score.metadata is not None:
        title = score.metadata.movementName or score.metadata.title

    counts = [len(v) for v in staves.values()]
    return {
        "title": title,
        "staves": staves,
        "measure_count": max(counts) if counts else 0,
    }


def diff_snapshots(before: Snapshot, after: Snapshot) -> dict[str, dict[str, Any]]:
    """Return every difference between two snapshots.

    Keys are "s{staff}m{measure}" for changed measures (value holds the
    before/after measure dicts) plus "measure_count" when the score grew
    or shrank.
    """
    changes: dict[str, dict[str, Any]] = {}
    if before["measure_count"] != after["measure_count"]:
        changes["measure_count"] = {
            "before": before["measure_count"],
            "after": after["measure_count"],
        }
    staff_keys = set(before["staves"]) | set(after["staves"])
    for s in staff_keys:
        b_measures = before["staves"].get(s, {})
        a_measures = after["staves"].get(s, {})
        for m in set(b_measures) | set(a_measures):
            b = b_measures.get(m)
            a = a_measures.get(m)
            if b != a:
                changes[f"s{s}m{m}"] = {"before": b, "after": a}
    return changes


def measure_of_key(change_key: str) -> int:
    """Extract the measure number from a "s{staff}m{measure}" diff key."""
    return int(change_key.rpartition("m")[2])


def get_measure(snapshot: Snapshot, staff: int, measure: int) -> dict[str, Any] | None:
    """Return the normalized measure dict for one staff/measure, if present."""
    return snapshot["staves"].get(str(staff), {}).get(str(measure))

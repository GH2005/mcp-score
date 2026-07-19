"""MusicXML snapshot parsing and diffing for live MuseScore verification.

The live suite verifies every bridge command against ground truth: the score
is exported through the plugin's ``exportScore`` command and the resulting
MusicXML is parsed (via music21) into a normalized, JSON-serializable
structure. Two such snapshots can then be diffed to assert that a command
changed exactly what it claimed to change -- and nothing else.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from music21 import (
    bar,
    chord,
    clef,
    converter,
    dynamics,
    expressions,
    harmony,
    key,
    meter,
    note,
    stream,
    tempo,
)

Snapshot = dict[str, Any]

MUSESCORE_EXE = Path("C:/Program Files/MuseScore 4/bin/MuseScore4.exe")


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
        ts.ratioString
        for ts in measure.recurse().getElementsByClass(meter.TimeSignature)
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


def render_png(musicxml_path: Path, out_png: Path, dpi: int = 130) -> list[Path]:
    """Render a MusicXML file to PNG page images via the MuseScore CLI.

    Works while the MuseScore GUI is open. Returns the per-page PNG paths
    (MuseScore appends -1, -2, ... to the requested name).
    """
    subprocess.run(
        [
            str(MUSESCORE_EXE),
            str(musicxml_path),
            "-o",
            str(out_png),
            "-r",
            str(dpi),
            "--force",
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    return sorted(out_png.parent.glob(f"{out_png.stem}-*{out_png.suffix}"))

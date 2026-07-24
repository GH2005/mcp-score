"""Score analysis tools — read and understand musical content.

For MuseScore, reads go through the ground-truth path: the plugin's
``exportScore`` command snapshots the live score to MusicXML, which is
parsed with music21 (see :mod:`mcp_score.musicxml`). The plugin cursor
API cannot see chords, voices, or anything past the first element of a
measure, so cursor-walking is only used as a fallback for Dorico and
Sibelius (which expose no exporter over their Remote Control APIs).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from mcp_score import theory
from mcp_score.app import mcp
from mcp_score.bridge.musescore import MuseScoreBridge
from mcp_score.bridge.remote_control import RemoteControlBridge
from mcp_score.musicxml import Snapshot, get_measure
from mcp_score.tools import (
    NOT_CONNECTED,
    PLUGIN_OUTDATED_ERROR,
    check_measure,
    connected_bridge,
    export_dir,
    export_snapshot,
    to_json,
)

__all__: list[str] = []

_REMOTE_CONTROL_ANALYSIS_WARNING = (
    "Dorico and Sibelius provide limited data through the Remote Control "
    "WebSocket API — you will get application status rather than detailed "
    "note content. Use get_selection_properties for the best results with "
    "Dorico/Sibelius."
)

#: Formats writeScore() handles safely in MuseScore 4. "mscz" is excluded:
#: in MuseScore Studio 4.7.4 it writes a 0-byte file, never replies, and
#: raises a blocking modal dialog that must be dismissed by hand.
_EXPORT_FORMATS = frozenset({"musicxml", "mxl", "xml", "pdf", "mid", "midi"})


def _staff_indices(snapshot: Snapshot, staff: int | None) -> list[int] | str:
    """Resolve the staff filter to concrete indices, or an error message."""
    available = sorted(int(s) for s in snapshot["staves"])
    if staff is None:
        return available
    if staff not in available:
        return f"staff must be one of {available}, got: {staff}"
    return [staff]


@mcp.tool()
async def read_passage(
    start_measure: int,
    end_measure: int,
    staff: int | None = None,
) -> str:
    """Read musical content from a range of measures in the live score.

    With MuseScore this is a ground-truth read: the live score (including
    unsaved edits) is exported to MusicXML and parsed, so every note,
    chord, rest, voice, and annotation is reported. Dorico and Sibelius
    fall back to cursor navigation and return limited data.

    Args:
        start_measure: First measure to read (1-indexed).
        end_measure: Last measure to read (inclusive, 1-indexed).
        staff: Staff index to read (0-indexed). If not provided, reads all staves.
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(start_measure, "start_measure"):
        return error
    if end_measure < start_measure:
        return to_json({"error": "end_measure must be >= start_measure."})

    if isinstance(bridge, MuseScoreBridge):
        snapshot, export_error = await export_snapshot(bridge)
        if snapshot is None:
            return to_json({"error": export_error})
        if end_measure > snapshot["measure_count"]:
            return to_json(
                {
                    "error": f"end_measure {end_measure} out of range "
                    f"(score has {snapshot['measure_count']} measures)."
                }
            )
        staves = _staff_indices(snapshot, staff)
        if isinstance(staves, str):
            return to_json({"error": staves})
        elements = [
            {
                "measure": measure,
                "staves": {str(s): get_measure(snapshot, s, measure) for s in staves},
            }
            for measure in range(start_measure, end_measure + 1)
        ]
        return to_json(
            {
                "success": True,
                "start_measure": start_measure,
                "end_measure": end_measure,
                "staff": staff,
                "elements": elements,
            }
        )

    # Fallback: cursor navigation (Dorico/Sibelius).
    elements_fallback: list[dict[str, Any]] = []
    for measure_num in range(start_measure, end_measure + 1):
        navigation_result = await bridge.go_to_measure(measure_num)
        if "error" in navigation_result:
            return to_json(navigation_result)
        if staff is not None:
            navigation_result = await bridge.go_to_staff(staff)
            if "error" in navigation_result:
                return to_json(navigation_result)
        cursor_info = await bridge.get_cursor_info()
        elements_fallback.append(
            {
                "measure": measure_num,
                "content": cursor_info,
            }
        )

    result: dict[str, Any] = {
        "success": True,
        "start_measure": start_measure,
        "end_measure": end_measure,
        "staff": staff,
        "elements": elements_fallback,
    }
    if isinstance(bridge, RemoteControlBridge):
        result["warning"] = _REMOTE_CONTROL_ANALYSIS_WARNING
    return to_json(result)


@mcp.tool()
async def get_measure_content(measure: int, staff: int = 0) -> str:
    """Read the content of a specific measure and staff from the connected score.

    With MuseScore this is a ground-truth read via MusicXML export (all
    notes, chords, rests, and annotations). Dorico and Sibelius return
    limited data.

    Args:
        measure: Measure number (1-indexed).
        staff: Staff index (0-indexed, default: 0).
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(measure):
        return error

    if isinstance(bridge, MuseScoreBridge):
        snapshot, export_error = await export_snapshot(bridge)
        if snapshot is None:
            return to_json({"error": export_error})
        if measure > snapshot["measure_count"]:
            return to_json(
                {
                    "error": f"measure {measure} out of range "
                    f"(score has {snapshot['measure_count']} measures)."
                }
            )
        staves = _staff_indices(snapshot, staff)
        if isinstance(staves, str):
            return to_json({"error": staves})
        return to_json(
            {
                "success": True,
                "measure": measure,
                "staff": staff,
                "content": get_measure(snapshot, staff, measure),
            }
        )

    navigation_result = await bridge.go_to_measure(measure)
    if "error" in navigation_result:
        return to_json(navigation_result)
    navigation_result = await bridge.go_to_staff(staff)
    if "error" in navigation_result:
        return to_json(navigation_result)
    return to_json(
        {
            "warning": _REMOTE_CONTROL_ANALYSIS_WARNING,
            "measure": measure,
            "staff": staff,
        }
    )


@mcp.tool()
async def get_selection_properties() -> str:
    """Get properties of the current selection in the connected score application.

    Returns information about whatever is currently selected:

    - **MuseScore**: Returns cursor position info (measure, beat, staff).
    - **Dorico/Sibelius**: Returns properties from the Remote Control
      API's ``getproperties`` message — names, types, and values of all
      properties on the selected items. This is the closest the WebSocket
      API gets to "reading" score data.

    Requires an active connection.
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    result = await bridge.get_properties()
    return to_json(result)


@mcp.tool()
async def export_live_score(path: str | None = None, format: str = "musicxml") -> str:
    """Export a snapshot of the live score to a file (MuseScore only).

    Captures the in-memory score including unsaved edits, without
    touching the user's own file. This is the ground-truth read: parse
    the resulting MusicXML (or render it) to see exactly what is in the
    score right now.

    Args:
        path: Absolute output path. Defaults to a unique file in the
            system temp directory (the reply contains the path).
        format: One of musicxml, mxl, xml, pdf, mid, midi. "mscz" is
            rejected: it is broken in MuseScore Studio 4.7.4 (0-byte
            file, no reply, and a blocking modal dialog).
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if not isinstance(bridge, MuseScoreBridge):
        return to_json(
            {
                "error": "export_live_score is only supported with MuseScore "
                "(Dorico and Sibelius expose no export over Remote Control)."
            }
        )
    if format not in _EXPORT_FORMATS:
        if format == "mscz":
            return to_json(
                {
                    "error": "mscz export is broken in MuseScore Studio 4.7.4: "
                    "writeScore produces a 0-byte file, never replies, and "
                    "raises a blocking modal dialog. Use musicxml instead."
                }
            )
        return to_json(
            {"error": f"format must be one of {sorted(_EXPORT_FORMATS)}, got: {format}"}
        )

    if path is None:
        target = export_dir() / f"score-{uuid.uuid4().hex}.{format}"
    else:
        target = Path(path)
        if not target.is_absolute():
            return to_json({"error": f"path must be absolute, got: {path}"})

    reply = await bridge.export_score(target.as_posix(), format)
    if "error" in reply:
        error = str(reply["error"])
        if "Unknown command" in error:
            return to_json({"error": PLUGIN_OUTDATED_ERROR})
        return to_json({"error": error})
    result = reply.get("result")
    if not isinstance(result, dict) or result.get("written") is not True:
        return to_json({"error": f"exportScore did not write a file: {reply}"})
    return to_json({"success": True, "path": target.as_posix(), "format": format})


@mcp.tool()
async def realize_harmony(figure: str, key: str, octave: int = 4) -> str:
    """Turn a harmonic intention into concrete, correctly spelled pitches.

    Resolves a roman numeral in a key, or an absolute chord symbol, into
    the notes that spell it — ready to hand straight to ``add_live_notes``
    as a ``chord`` entry. This is the "I want the dominant of the
    dominant" to "these four notes" step, with music21 choosing the
    spelling (a German sixth comes back with a D-sharp, not an E-flat).

    Pure theory: no score and no MuseScore connection needed.

    Args:
        figure: A roman numeral read in *key* (``"V7"``, ``"V7/V"``,
            ``"bVII"``, ``"ii65"``, ``"Ger65"``, ``"cad64"``) or a chord
            symbol (``"E-maj7"``, ``"F#m7b5"``). Use ``-`` for a flat
            root (``"B-7"`` is B-flat dominant 7; ``"Bb7"`` would be read
            as B with a flat-7).
        key: Key to read the figure in. Uppercase is major, lowercase is
            minor (``"E-"`` = E-flat major, ``"c"`` = C minor).
        octave: Octave for the lowest note (default 4, middle C).
    """
    try:
        pitches = theory.realize(figure, key, octave)
    except ValueError as exception:
        return to_json({"error": str(exception)})
    except Exception as exception:  # noqa: BLE001 - music21 raises broadly
        return to_json({"error": f"could not realize {figure!r} in {key}: {exception}"})

    return to_json(
        {
            "success": True,
            "figure": figure,
            "key": key,
            "pitches": pitches,
            "chord_for_add_live_notes": [p["name"] for p in pitches],
        }
    )


@mcp.tool()
async def analyze_passage(
    start_measure: int,
    end_measure: int,
    staff: int | None = None,
    key: str | None = None,
) -> str:
    """Report what a passage of the live score is doing, musically.

    Advisory only — this reads the score and describes it, and never
    edits or blocks anything. Observations are offered for judgement, not
    as rules: parallel fifths are an error in a chorale, the point in
    organum, and unremarkable in power chords, so the tool reports them
    and leaves the call to you.

    Reports:

    - the key music21 detects for the passage (and how it compares to
      *key*, if you supply the one you intend),
    - a roman-numeral reading of each measure's harmony,
    - voice-leading observations between consecutive chords: parallel and
      hidden fifths/octaves, and voice crossings, each located by measure,
    - the ambitus (lowest to highest note) of each staff.

    Args:
        start_measure: First measure (1-indexed).
        end_measure: Last measure (inclusive, 1-indexed).
        staff: Staff to analyze (0-indexed). Omit to analyze all staves
            together, which is what you want for harmony.
        key: The key you intend, e.g. ``"E-"`` or ``"c"``. Optional; when
            given, harmony is read in this key rather than the detected one.
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if not isinstance(bridge, MuseScoreBridge):
        return to_json(
            {
                "error": "analyze_passage is only supported with MuseScore "
                "(it needs the MusicXML export that Dorico and Sibelius "
                "do not provide over Remote Control)."
            }
        )
    if error := check_measure(start_measure, "start_measure"):
        return error
    if end_measure < start_measure:
        return to_json({"error": "end_measure must be >= start_measure."})

    path = export_dir() / f"analyze-{uuid.uuid4().hex}.musicxml"
    reply = await bridge.export_score(path.as_posix(), "musicxml")
    if "error" in reply:
        error = str(reply["error"])
        if "Unknown command" in error:
            return to_json({"error": PLUGIN_OUTDATED_ERROR})
        return to_json({"error": error})
    try:
        report = theory.analyze_musicxml(path, start_measure, end_measure, staff, key)
    except ValueError as exception:
        return to_json({"error": str(exception)})
    finally:
        path.unlink(missing_ok=True)
    return to_json(report)

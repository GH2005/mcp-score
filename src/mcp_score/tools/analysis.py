"""Score analysis tools — read and understand musical content.

For MuseScore, reads go through the ground-truth path: the plugin's
``exportScore`` command snapshots the live score to MusicXML, which is
parsed with music21 (see :mod:`mcp_score.musicxml`). The plugin cursor
API cannot see chords, voices, or anything past the first element of a
measure, so cursor-walking is only used as a fallback for Dorico and
Sibelius (which expose no exporter over their Remote Control APIs).
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from mcp_score.app import mcp
from mcp_score.bridge.musescore import MuseScoreBridge
from mcp_score.bridge.remote_control import RemoteControlBridge
from mcp_score.musicxml import Snapshot, get_measure, parse_snapshot
from mcp_score.tools import NOT_CONNECTED, check_measure, connected_bridge, to_json

__all__: list[str] = []

_REMOTE_CONTROL_ANALYSIS_WARNING = (
    "Dorico and Sibelius provide limited data through the Remote Control "
    "WebSocket API — you will get application status rather than detailed "
    "note content. Use get_selection_properties for the best results with "
    "Dorico/Sibelius."
)

_PLUGIN_OUTDATED_ERROR = (
    "The installed mcp-score-bridge plugin does not support the exportScore "
    "command. Reinstall it with 'mcp-score install-plugin' and restart "
    "MuseScore."
)

#: Formats writeScore() handles safely in MuseScore 4. "mscz" is excluded:
#: in MuseScore Studio 4.7.4 it writes a 0-byte file, never replies, and
#: raises a blocking modal dialog that must be dismissed by hand.
_EXPORT_FORMATS = frozenset({"musicxml", "mxl", "xml", "pdf", "mid", "midi"})


def _export_dir() -> Path:
    directory = Path(tempfile.gettempdir()) / "mcp-score-exports"
    directory.mkdir(exist_ok=True)
    return directory


async def _export_snapshot(
    bridge: MuseScoreBridge,
) -> tuple[Snapshot | None, str | None]:
    """Snapshot the live score to a temp file and parse it.

    Returns (snapshot, None) on success or (None, error message).
    """
    path = _export_dir() / f"read-{uuid.uuid4().hex}.musicxml"
    reply = await bridge.export_score(path.as_posix(), "musicxml")
    if "error" in reply:
        error = str(reply["error"])
        if "Unknown command" in error:
            return None, _PLUGIN_OUTDATED_ERROR
        return None, error
    result = reply.get("result")
    if not isinstance(result, dict) or result.get("written") is not True:
        return None, f"exportScore did not write a file: {reply}"
    try:
        return parse_snapshot(path), None
    finally:
        path.unlink(missing_ok=True)


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
        snapshot, export_error = await _export_snapshot(bridge)
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
        snapshot, export_error = await _export_snapshot(bridge)
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
        target = _export_dir() / f"score-{uuid.uuid4().hex}.{format}"
    else:
        target = Path(path)
        if not target.is_absolute():
            return to_json({"error": f"path must be absolute, got: {path}"})

    reply = await bridge.export_score(target.as_posix(), format)
    if "error" in reply:
        error = str(reply["error"])
        if "Unknown command" in error:
            return to_json({"error": _PLUGIN_OUTDATED_ERROR})
        return to_json({"error": error})
    result = reply.get("result")
    if not isinstance(result, dict) or result.get("written") is not True:
        return to_json({"error": f"exportScore did not write a file: {reply}"})
    return to_json({"success": True, "path": target.as_posix(), "format": format})

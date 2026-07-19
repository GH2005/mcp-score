"""Score manipulation tools — modify the live score in a connected application."""

from typing import Any

from mcp_score.app import mcp
from mcp_score.bridge import ScoreBridge
from mcp_score.bridge.musescore import MuseScoreBridge
from mcp_score.tools import NOT_CONNECTED, check_measure, connected_bridge, to_json

__all__: list[str] = []

#: Plugin commands that crash MuseScore Studio 4.7.4 outright (the
#: newElement + cursor.add pattern is fatal for these element types).
#: Blocked server-side until the plugin reimplements them safely.
_CRASHING_ACTIONS = frozenset({"setBarline", "addChordSymbol", "addDynamic"})

_CRASH_GUARD_ERROR = (
    "{action} is temporarily disabled for MuseScore: the plugin command "
    "crashes MuseScore Studio 4.7.4 outright (verified 2026-07-18). A safe "
    "reimplementation is planned; until then this guard protects the "
    "running MuseScore instance."
)

_MUSESCORE_ONLY_ERROR = (
    "{tool} is only supported with MuseScore. {app}'s Remote Control API "
    "does not expose this operation."
)


def _require_musescore(bridge: ScoreBridge, tool: str) -> str | None:
    """Return an error JSON string when the bridge is not MuseScore."""
    if isinstance(bridge, MuseScoreBridge):
        return None
    return to_json(
        {"error": _MUSESCORE_ONLY_ERROR.format(tool=tool, app=bridge.application_name)}
    )


@mcp.tool()
async def add_live_rehearsal_mark(measure: int, text: str) -> str:
    """Add a rehearsal mark in the live score.

    Args:
        measure: Measure number (1-indexed).
        text: Rehearsal mark text (e.g. "A", "B", "Intro").
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(measure):
        return error

    await bridge.go_to_measure(measure)
    result = await bridge.add_rehearsal_mark(text)
    return to_json(result)


@mcp.tool()
async def add_live_chord_symbol(measure: int, symbol: str) -> str:
    """Add a chord symbol in the live score.

    Currently disabled for MuseScore: the underlying plugin command
    crashes MuseScore Studio 4.7.4.

    Args:
        measure: Measure number (1-indexed).
        symbol: Chord symbol (e.g. "Cmaj7", "Dm7", "G7").
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(measure):
        return error
    if isinstance(bridge, MuseScoreBridge):
        return to_json(
            {"error": _CRASH_GUARD_ERROR.format(action="add_live_chord_symbol")}
        )

    await bridge.go_to_measure(measure)
    result = await bridge.add_chord_symbol(symbol)
    return to_json(result)


@mcp.tool()
async def set_live_barline(measure: int, barline_type: str) -> str:
    """Set a barline type in the live score.

    Currently disabled for MuseScore: the underlying plugin command
    crashes MuseScore Studio 4.7.4.

    Args:
        measure: Measure number (1-indexed).
        barline_type: One of "double", "final", "startRepeat", "endRepeat".
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(measure):
        return error
    if isinstance(bridge, MuseScoreBridge):
        return to_json({"error": _CRASH_GUARD_ERROR.format(action="set_live_barline")})

    await bridge.go_to_measure(measure)
    result = await bridge.set_barline(barline_type)
    return to_json(result)


@mcp.tool()
async def set_live_key_signature(measure: int, fifths: int) -> str:
    """Set the key signature in the live score.

    Args:
        measure: Measure number (1-indexed).
        fifths: Number of sharps (positive) or flats (negative).
            Examples: 0 = C major, 2 = D major, -3 = Eb major.
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(measure):
        return error

    await bridge.go_to_measure(measure)
    result = await bridge.set_key_signature(fifths)
    return to_json(result)


@mcp.tool()
async def set_live_tempo(measure: int, bpm: int, text: str | None = None) -> str:
    """Set the tempo in the live score.

    Args:
        measure: Measure number (1-indexed).
        bpm: Beats per minute.
        text: Optional display text (e.g. "Swing", "Allegro").
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := check_measure(measure):
        return error

    await bridge.go_to_measure(measure)
    result = await bridge.set_tempo(bpm, text)
    return to_json(result)


@mcp.tool()
async def transpose_passage(
    start_measure: int,
    end_measure: int,
    staff: int,
    semitones: int,
) -> str:
    """Transpose a passage by a number of semitones in the live score.

    Args:
        start_measure: First measure (1-indexed).
        end_measure: Last measure (inclusive, 1-indexed).
        staff: Staff index (0-indexed).
        semitones: Number of semitones to transpose (positive = up, negative = down).
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if not isinstance(bridge, MuseScoreBridge):
        return to_json(
            {
                "error": (
                    "transpose_passage is only supported with MuseScore. "
                    f"{bridge.application_name}'s Remote Control API does not "
                    "support programmatic range selection and transposition."
                )
            }
        )
    if error := check_measure(start_measure, "start_measure"):
        return error
    if end_measure < start_measure:
        return to_json({"error": "end_measure must be >= start_measure."})

    # Single ranged transpose message: the plugin walks the range with a
    # cursor. (Selection-based transposition is unreliable in MuseScore 4:
    # selectRange does not produce an active selection there.)
    result = await bridge.send_command(
        "transpose",
        {
            "semitones": semitones,
            "startMeasure": start_measure,
            "endMeasure": end_measure,
            "startStaff": staff,
            "endStaff": staff,
        },
    )
    return to_json(result)


@mcp.tool()
async def undo_last_action() -> str:
    """Undo the last action in the connected score application."""
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})

    result = await bridge.undo()
    return to_json(result)


@mcp.tool()
async def set_live_time_signature(
    measure: int, numerator: int, denominator: int
) -> str:
    """Set the time signature at a measure in the live score (MuseScore only).

    Changing the meter re-bars the music from that measure onward.

    Args:
        measure: Measure number (1-indexed).
        numerator: Beats per measure (e.g. 3 for 3/4).
        denominator: Beat unit (e.g. 4 for 3/4).
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := _require_musescore(bridge, "set_live_time_signature"):
        return error
    if error := check_measure(measure):
        return error
    if numerator < 1 or denominator < 1:
        return to_json({"error": "numerator and denominator must be >= 1."})
    assert isinstance(bridge, MuseScoreBridge)

    navigation_result = await bridge.go_to_measure(measure)
    if "error" in navigation_result:
        return to_json(navigation_result)
    result = await bridge.set_time_signature(numerator, denominator)
    return to_json(result)


@mcp.tool()
async def append_live_measures(count: int = 1) -> str:
    """Append empty measures to the end of the live score (MuseScore only).

    Args:
        count: Number of measures to append (>= 1).
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := _require_musescore(bridge, "append_live_measures"):
        return error
    if count < 1:
        return to_json({"error": "count must be >= 1."})
    assert isinstance(bridge, MuseScoreBridge)

    result = await bridge.append_measures(count)
    return to_json(result)


@mcp.tool()
async def add_live_notes(measure: int, staff: int, notes: list[dict[str, int]]) -> str:
    """Write a run of notes into the live score (MuseScore only).

    Notes are written consecutively starting at beat 1 of the given
    measure — each note advances the insertion point by its duration,
    spilling into following measures when the run is longer than the
    measure. Existing content at those beats is REPLACED. The whole run
    executes as a single batch (one undo group).

    Args:
        measure: Starting measure (1-indexed).
        staff: Staff index (0-indexed).
        notes: Each note is {"pitch": <0-127 MIDI>, "numerator": 1,
            "denominator": 4}; numerator/denominator describe the
            duration and default to a quarter note.
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := _require_musescore(bridge, "add_live_notes"):
        return error
    if error := check_measure(measure):
        return error
    if staff < 0:
        return to_json({"error": "staff must be >= 0."})
    if not notes:
        return to_json({"error": "notes must be a non-empty list."})
    assert isinstance(bridge, MuseScoreBridge)

    steps: list[dict[str, Any]] = [
        {"action": "goToStaff", "params": {"staff": staff}},
        {"action": "goToMeasure", "params": {"measure": measure}},
    ]
    for index, entry in enumerate(notes):
        pitch = entry.get("pitch")
        if not isinstance(pitch, int) or not 0 <= pitch <= 127:
            return to_json({"error": f"notes[{index}].pitch must be a MIDI int 0-127."})
        numerator = entry.get("numerator", 1)
        denominator = entry.get("denominator", 4)
        if numerator < 1 or denominator < 1:
            return to_json({"error": f"notes[{index}] duration values must be >= 1."})
        steps.append(
            {
                "action": "addNote",
                "params": {
                    "pitch": pitch,
                    "duration": {
                        "numerator": numerator,
                        "denominator": denominator,
                    },
                },
            }
        )

    result = await bridge.process_sequence(steps)
    return to_json(result)


@mcp.tool()
async def process_live_sequence(steps: list[dict[str, Any]]) -> str:
    """Execute a batch of plugin actions in one undo group (MuseScore only).

    Each step is {"action": <name>, "params": {...}}. Supported actions:
    ping, goToMeasure, goToStaff, addNote, addRehearsalMark,
    setKeySignature, setTimeSignature, setTempo, appendMeasures,
    selectCurrentMeasure, selectCustomRange, transpose.

    On a failed step the reply carries failedIndex/failedAction. Note:
    rollback is currently broken in MuseScore Studio 4.7.4 (the plugin's
    undo is a no-op), so steps before the failure stay applied.

    Args:
        steps: Ordered list of {"action", "params"} dicts.
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := _require_musescore(bridge, "process_live_sequence"):
        return error
    if not steps:
        return to_json({"error": "steps must be a non-empty list."})
    for index, step in enumerate(steps):
        action = step.get("action")
        if not isinstance(action, str) or not action:
            return to_json({"error": f"steps[{index}] is missing 'action'."})
        if action in _CRASHING_ACTIONS:
            return to_json(
                {"error": _CRASH_GUARD_ERROR.format(action=f"action '{action}'")}
            )
    assert isinstance(bridge, MuseScoreBridge)

    result = await bridge.process_sequence(steps)
    return to_json(result)

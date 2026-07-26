"""Score manipulation tools — modify the live score in a connected application."""

from typing import Any

from mcp_score import theory
from mcp_score.app import mcp
from mcp_score.bridge import ScoreBridge
from mcp_score.bridge.musescore import MuseScoreBridge
from mcp_score.musicxml import get_measure
from mcp_score.theory import plan_transposition
from mcp_score.tools import (
    NOT_CONNECTED,
    check_measure,
    connected_bridge,
    export_snapshot,
    to_json,
)

__all__: list[str] = []

#: Plugin commands that crash MuseScore Studio 4.7.4 outright (the
#: newElement + cursor.add pattern is fatal for these element types).
#: Blocked server-side until the plugin reimplements them safely.
_CRASHING_ACTIONS = frozenset({"setBarline", "addChordSymbol", "addDynamic"})

#: Plugin commands that silently write corrupt data in MuseScore 4.7.4
#: (cursor.add clones the element and the clone loses/garbles the values).
_CORRUPTING_ACTIONS = frozenset({"setKeySignature", "setTempo"})

_CRASH_GUARD_ERROR = (
    "{action} is temporarily disabled for MuseScore: the plugin command "
    "crashes MuseScore Studio 4.7.4 outright (verified 2026-07-18). A safe "
    "reimplementation is planned; until then this guard protects the "
    "running MuseScore instance."
)

_CORRUPTION_GUARD_ERROR = (
    "{action} is disabled for MuseScore: cursor.add clones and corrupts "
    "the element in MuseScore Studio 4.7.4 (every inserted key signature "
    "exports as fifths=-8 and tempo text exports empty, regardless of the "
    "values written -- verified 2026-07-19). The command would silently "
    "write garbage into the score."
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

    Currently disabled for MuseScore: the plugin inserts a corrupt key
    signature (MuseScore 4.7.4 API limitation).

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
    if isinstance(bridge, MuseScoreBridge):
        return to_json(
            {"error": _CORRUPTION_GUARD_ERROR.format(action="set_live_key_signature")}
        )

    await bridge.go_to_measure(measure)
    result = await bridge.set_key_signature(fifths)
    return to_json(result)


@mcp.tool()
async def set_live_tempo(measure: int, bpm: int, text: str | None = None) -> str:
    """Set the tempo in the live score.

    Currently disabled for MuseScore: the plugin inserts an empty tempo
    mark (MuseScore 4.7.4 API limitation).

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
    if isinstance(bridge, MuseScoreBridge):
        return to_json(
            {"error": _CORRUPTION_GUARD_ERROR.format(action="set_live_tempo")}
        )

    await bridge.go_to_measure(measure)
    result = await bridge.set_tempo(bpm, text)
    return to_json(result)


@mcp.tool()
async def transpose_passage(
    start_measure: int,
    end_measure: int,
    staff: int,
    semitones: int | None = None,
    voice: int | None = None,
    degrees: int | None = None,
    key: str | None = None,
) -> str:
    """Transpose a passage in the live score, spelling it musically.

    Two ways to move the music, and they answer different requests:

    - ``semitones`` moves it *chromatically*, by a fixed distance. This
      is "put it in another key" — up a minor third is up a minor third
      from every note.
    - ``degrees`` (with ``key``) moves it *within the key*, by scale
      steps: +1 up a second, +2 up a third, -4 down a fifth. This is
      what "move that up a third" means when the music is to stay in its
      key — the interval changes size from degree to degree so it does.
      Notes foreign to the key are pulled onto the nearest scale tone in
      the direction of travel and reported back in ``snapped``.

    Pass exactly one of them. Each note's spelling is chosen by music21
    rather than by a fixed per-semitone table, so a passage moved into a
    flat key comes out with flats. The passage is read from a MusicXML
    snapshot first, the new pitches are computed here, and the plugin
    verifies every note still matches before it writes anything — a
    passage that changed since the read fails whole rather than
    half-transposed.

    Args:
        start_measure: First measure (1-indexed).
        end_measure: Last measure (inclusive, 1-indexed).
        staff: Staff index (0-indexed).
        semitones: Semitones to transpose (positive = up, negative = down).
        voice: Voice to transpose (0-3). Omit to transpose every voice on
            the staff.
        degrees: Scale steps to move within ``key`` (+2 = up a third).
        key: The key to stay inside (``"E-"`` major, ``"c"`` minor).
            Required with ``degrees``.
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
    if voice is not None and not 0 <= voice <= 3:
        return to_json({"error": "voice must be 0-3."})
    if (semitones is None) == (degrees is None):
        return to_json(
            {
                "error": "pass exactly one of semitones (chromatic) or degrees "
                "(within a key, needs key=). 'Up a third in E-flat' is "
                "degrees=2, key='E-'."
            }
        )
    if degrees is not None and not key:
        return to_json(
            {"error": "degrees needs key= — the scale it should stay inside."}
        )

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

    snapped: list[dict[str, Any]] = []
    if degrees is not None:
        assert key is not None
        diatonic = theory.plan_diatonic_transposition(
            snapshot, staff, start_measure, end_measure, degrees, key, voice
        )
        if isinstance(diatonic, str):
            return to_json({"error": diatonic})
        plans = diatonic["plans"]
        snapped = diatonic["snapped"]
    else:
        assert semitones is not None
        plans = plan_transposition(
            snapshot, staff, start_measure, end_measure, semitones, voice
        )
        if isinstance(plans, str):
            return to_json({"error": plans})
    if not plans:
        return to_json(
            {
                "success": True,
                "notes_transposed": 0,
                "detail": "No notes in that range.",
            }
        )

    applied, failure = await _apply_pitch_plans(
        bridge, staff, start_measure, end_measure, plans
    )
    if failure is not None:
        return to_json(failure)

    response: dict[str, Any] = {
        "success": True,
        "start_measure": start_measure,
        "end_measure": end_measure,
        "staff": staff,
        "notes_transposed": sum(v["notes"] for v in applied),
        "voices": applied,
    }
    if degrees is not None:
        response["degrees"] = degrees
        response["key"] = key
        response["snapped"] = snapped
        if snapped:
            response["note"] = (
                f"{len(snapped)} note(s) were foreign to {key} and were pulled "
                "onto the nearest scale tone."
            )
    else:
        response["semitones"] = semitones
    return to_json(response)


async def _apply_pitch_plans(
    bridge: MuseScoreBridge,
    staff: int,
    start_measure: int,
    end_measure: int,
    plans: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Send one ``setPitches`` call per voice, stopping at the first error.

    Returns the per-voice results and, when a voice failed, the error
    payload to return — which names the voices already applied, because
    the plugin's undo cannot take them back.
    """
    applied: list[dict[str, Any]] = []
    for plan in plans:
        reply = await bridge.set_pitches(
            staff, plan["voice"], start_measure, end_measure, plan["edits"]
        )
        if "error" in reply:
            return applied, {
                "error": reply["error"],
                "voice": plan["voice"],
                "applied_voices": applied,
            }
        result = reply.get("result", {})
        applied.append(
            {
                "voice": plan["voice"],
                "notes": result.get("notesChanged", len(plan["edits"])),
            }
        )
    return applied, None


@mcp.tool()
async def transform_passage(
    operation: str,
    start_measure: int,
    end_measure: int,
    staff: int,
    key: str | None = None,
    axis: str | None = None,
    voice: int | None = None,
    copies: int = 1,
    degrees: int = 0,
) -> str:
    """Apply a classical melodic transformation to a passage (MuseScore only).

    Operations:

    - ``"invert"`` — mirror the line around ``axis``, diatonically in
      ``key``: what went up a third now goes down a third. Only pitches
      change, so the rhythm and the barlines are untouched, and every
      voice on the staff can be inverted at once.
    - ``"retrograde"`` — write the passage backwards, pitches *and*
      rhythm. This REPLACES the passage by writing it again note by
      note, in one voice.
    - ``"sequence"`` — repeat the passage ``copies`` times into the
      measures that follow, each copy ``degrees`` scale steps higher
      (or lower) than the last. This WRITES OVER those measures.

    Retrograde and sequence have to re-enter the music note by note,
    which the wire cannot do for everything MuseScore can hold: a
    passage containing ties, tuplets, grace notes, a meter change, or a
    voice that does not fill every bar is refused with the reason rather
    than written wrong. Nothing is sent to the score unless the whole
    transformation was planned successfully.

    Args:
        operation: ``"invert"``, ``"retrograde"``, or ``"sequence"``.
        start_measure: First measure of the source passage (1-indexed).
        end_measure: Last measure of the source passage (inclusive).
        staff: Staff index (0-indexed).
        key: Key to stay inside. Required for invert and sequence.
        axis: The mirror note for invert, octave required (``"G4"``).
        voice: Voice (0-3). For invert, omit to invert every voice;
            retrograde and sequence rewrite one voice, default 0.
        copies: How many sequenced copies to write (sequence only).
        degrees: Scale steps each copy sits above the previous one
            (sequence only; +1 = a second, 0 = repeat verbatim).
    """
    bridge = connected_bridge()
    if bridge is None:
        return to_json({"error": NOT_CONNECTED})
    if error := _require_musescore(bridge, "transform_passage"):
        return error
    if operation not in {"invert", "retrograde", "sequence"}:
        return to_json(
            {
                "error": f"unknown operation: {operation!r}. Choose from: "
                "invert, retrograde, sequence."
            }
        )
    if error := check_measure(start_measure, "start_measure"):
        return error
    if end_measure < start_measure:
        return to_json({"error": "end_measure must be >= start_measure."})
    if staff < 0:
        return to_json({"error": "staff must be >= 0."})
    if voice is not None and not 0 <= voice <= 3:
        return to_json({"error": "voice must be 0-3."})
    if operation in {"invert", "sequence"} and not key:
        return to_json(
            {"error": f"{operation} needs key= — the scale it should stay inside."}
        )
    if operation == "invert" and not axis:
        return to_json(
            {
                "error": "invert needs axis= — the note to mirror around, with "
                "an octave (e.g. 'G4')."
            }
        )
    assert isinstance(bridge, MuseScoreBridge)

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

    if operation == "invert":
        assert key is not None and axis is not None
        return await _invert_passage(
            bridge, snapshot, staff, start_measure, end_measure, axis, key, voice
        )
    target_voice = 0 if voice is None else voice
    if operation == "retrograde":
        return await _retrograde_passage(
            bridge, snapshot, staff, start_measure, end_measure, target_voice
        )
    assert key is not None
    return await _sequence_passage(
        bridge,
        snapshot,
        staff,
        start_measure,
        end_measure,
        copies,
        degrees,
        key,
        target_voice,
    )


async def _invert_passage(
    bridge: MuseScoreBridge,
    snapshot: dict[str, Any],
    staff: int,
    start_measure: int,
    end_measure: int,
    axis: str,
    key: str,
    voice: int | None,
) -> str:
    """Mirror a passage around an axis, re-pitching notes in place."""
    planned = theory.plan_inversion(
        snapshot, staff, start_measure, end_measure, axis, key, voice
    )
    if isinstance(planned, str):
        return to_json({"error": planned})
    plans = planned["plans"]
    if not plans:
        return to_json(
            {"success": True, "notes_changed": 0, "detail": "No notes in that range."}
        )

    applied, failure = await _apply_pitch_plans(
        bridge, staff, start_measure, end_measure, plans
    )
    if failure is not None:
        return to_json(failure)

    response: dict[str, Any] = {
        "success": True,
        "operation": "invert",
        "start_measure": start_measure,
        "end_measure": end_measure,
        "staff": staff,
        "axis": axis,
        "key": key,
        "notes_changed": sum(v["notes"] for v in applied),
        "voices": applied,
        "snapped": planned["snapped"],
    }
    if planned["snapped"]:
        response["note"] = (
            f"{len(planned['snapped'])} note(s) were chromatic; their reflected "
            f"letters took {key}'s accidentals."
        )
    return to_json(response)


async def _retrograde_passage(
    bridge: MuseScoreBridge,
    snapshot: dict[str, Any],
    staff: int,
    start_measure: int,
    end_measure: int,
    voice: int,
) -> str:
    """Rewrite a passage backwards, pitches and rhythm together."""
    planned = theory.plan_retrograde(snapshot, staff, start_measure, end_measure, voice)
    if isinstance(planned, str):
        return to_json({"error": planned})

    steps = _entries_to_steps(start_measure, staff, voice, planned["entries"])
    if isinstance(steps, str):
        return to_json({"error": steps})

    result = await bridge.process_sequence(steps)
    if "error" in result:
        return to_json(result)
    return to_json(
        {
            "success": True,
            "operation": "retrograde",
            "start_measure": start_measure,
            "end_measure": end_measure,
            "staff": staff,
            "voice": voice,
            "events_written": len(planned["entries"]),
            "note": (
                f"measures {start_measure}-{end_measure} of staff {staff} "
                f"voice {voice} were rewritten. Read the passage back to "
                "confirm what landed."
            ),
        }
    )


async def _sequence_passage(
    bridge: MuseScoreBridge,
    snapshot: dict[str, Any],
    staff: int,
    start_measure: int,
    end_measure: int,
    copies: int,
    degrees: int,
    key: str,
    voice: int,
) -> str:
    """Repeat a motif into the following measures, shifted each time."""
    planned = theory.plan_sequence(
        snapshot, staff, start_measure, end_measure, copies, degrees, key, voice
    )
    if isinstance(planned, str):
        return to_json({"error": planned})

    steps: list[dict[str, Any]] = []
    for copy in planned["copies"]:
        compiled = _entries_to_steps(copy["measure"], staff, voice, copy["entries"])
        if isinstance(compiled, str):
            return to_json({"error": compiled})
        steps.extend(compiled)

    overwritten = _measures_with_notes(
        snapshot, staff, voice, end_measure + 1, planned["destination_end"]
    )

    result = await bridge.process_sequence(steps)
    if "error" in result:
        return to_json(result)
    return to_json(
        {
            "success": True,
            "operation": "sequence",
            "start_measure": start_measure,
            "end_measure": end_measure,
            "staff": staff,
            "voice": voice,
            "key": key,
            "destination_end": planned["destination_end"],
            "copies": [
                {"measure": copy["measure"], "shift_degrees": copy["shift_degrees"]}
                for copy in planned["copies"]
            ],
            "snapped": [item for copy in planned["copies"] for item in copy["snapped"]],
            "overwrote_existing_notes": overwritten,
            "note": (
                f"measures {end_measure + 1}-{planned['destination_end']} of "
                f"staff {staff} voice {voice} now hold the copies"
                + (
                    f"; they already held notes ({', '.join(map(str, overwritten))}), "
                    "which were replaced."
                    if overwritten
                    else "."
                )
            ),
        }
    )


def _measures_with_notes(
    snapshot: dict[str, Any],
    staff: int,
    voice: int,
    first_measure: int,
    last_measure: int,
) -> list[int]:
    """Which measures in a range already carry notes in a voice."""
    occupied: list[int] = []
    for measure in range(first_measure, last_measure + 1):
        content = get_measure(snapshot, staff, measure)
        if not content:
            continue
        if any(
            event.get("kind") != "rest" and theory.musescore_voice(event) == voice
            for event in content["events"]
        ):
            occupied.append(measure)
    return occupied


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
async def add_live_notes(
    measure: int,
    staff: int,
    notes: list[dict[str, Any]],
    voice: int = 0,
) -> str:
    """Write notes, chords and rests into the live score (MuseScore only).

    Entries are written consecutively starting at beat 1 of the given
    measure — each advances the insertion point by its duration, spilling
    into following measures when the run is longer than the measure.
    Existing content at those beats is REPLACED. The whole run executes as
    a single batch (one undo group).

    Args:
        measure: Starting measure (1-indexed).
        staff: Staff index (0-indexed).
        notes: Each entry carries a duration (``"numerator"`` and
            ``"denominator"``, default 1/4) plus one of:

            - ``{"name": "E-4"}`` — a spelled note. **Prefer this.** Use
              ``-`` or ``b`` for flats (``"E-4"``/``"Eb4"``), ``#`` for
              sharps. The spelling is preserved exactly, so an ascending
              C-sharp stays a C-sharp and a descending D-flat stays a
              D-flat.
            - ``{"chord": ["C4", "E-4", "G4"]}`` — simultaneous notes.
            - ``{"pitch": 61}`` — a bare MIDI number. Pass ``key`` (e.g.
              ``{"pitch": 61, "key": "E-"}``) to spell it for that key,
              otherwise music21's default spelling is used.
            - ``{"rest": true}`` — a rest.

        voice: Voice within the staff (0-3, default 0). Voice 1 is the
            second voice — how independent lines are written on one staff.
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
    if not 0 <= voice <= 3:
        return to_json({"error": "voice must be 0-3."})
    if not notes:
        return to_json({"error": "notes must be a non-empty list."})
    assert isinstance(bridge, MuseScoreBridge)

    steps = _entries_to_steps(measure, staff, voice, notes)
    if isinstance(steps, str):
        return to_json({"error": steps})

    result = await bridge.process_sequence(steps)
    return to_json(result)


def _entries_to_steps(
    measure: int, staff: int, voice: int, notes: list[dict[str, Any]]
) -> list[dict[str, Any]] | str:
    """Compile note entries into a positioned run of plugin steps."""
    steps: list[dict[str, Any]] = [
        {"action": "goToStaff", "params": {"staff": staff, "voice": voice}},
        {"action": "goToMeasure", "params": {"measure": measure}},
    ]
    for index, entry in enumerate(notes):
        compiled = _compile_entry(entry, index)
        if isinstance(compiled, str):
            return compiled
        steps.extend(compiled)
    return steps


def _compile_entry(entry: dict[str, Any], index: int) -> list[dict[str, Any]] | str:
    """Turn one add_live_notes entry into plugin steps, or return an error.

    Note names are resolved to (pitch, tpc) here — music21 owns the
    spelling decision, the plugin only stores the result.
    """
    numerator = entry.get("numerator", 1)
    denominator = entry.get("denominator", 4)
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        return f"notes[{index}] duration values must be integers."
    if numerator < 1 or denominator < 1:
        return f"notes[{index}] duration values must be >= 1."
    duration = {"numerator": numerator, "denominator": denominator}

    if entry.get("rest") is True:
        return [{"action": "addRest", "params": {"duration": duration}}]

    chord = entry.get("chord")
    if chord is not None:
        if not isinstance(chord, list) or not chord:
            return f"notes[{index}].chord must be a non-empty list of note names."
        steps: list[dict[str, Any]] = []
        for position, name in enumerate(chord):
            resolved = _resolve_pitch({"name": name}, index)
            if isinstance(resolved, str):
                return resolved
            params: dict[str, Any] = {
                "pitch": resolved["midi"],
                "tpc": resolved["tpc"],
                "duration": duration,
            }
            if position > 0:
                params["addToChord"] = True
            steps.append({"action": "addNote", "params": params})
        return steps

    resolved = _resolve_pitch(entry, index)
    if isinstance(resolved, str):
        return resolved
    return [
        {
            "action": "addNote",
            "params": {
                "pitch": resolved["midi"],
                "tpc": resolved["tpc"],
                "duration": duration,
            },
        }
    ]


def _resolve_pitch(entry: dict[str, Any], index: int) -> theory.SpelledPitch | str:
    """Resolve a name or MIDI entry to a spelled pitch, or an error string."""
    name = entry.get("name")
    if name is not None:
        if not isinstance(name, str):
            return f"notes[{index}].name must be a string like 'E-4'."
        try:
            return theory.name_to_pitch_tpc(name)
        except ValueError as exception:
            return f"notes[{index}]: {exception}"

    pitch = entry.get("pitch")
    if pitch is None:
        return (
            f"notes[{index}] needs one of: name, chord, pitch, or rest. "
            "Prefer 'name' (e.g. 'E-4') so the spelling is unambiguous."
        )
    if not isinstance(pitch, int) or not 0 <= pitch <= 127:
        return f"notes[{index}].pitch must be a MIDI int 0-127."
    key_context = entry.get("key")
    try:
        return theory.spell_midi(pitch, key_context if key_context else None)
    except ValueError as exception:
        return f"notes[{index}]: {exception}"


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
        if action in _CORRUPTING_ACTIONS:
            return to_json(
                {"error": _CORRUPTION_GUARD_ERROR.format(action=f"action '{action}'")}
            )
    assert isinstance(bridge, MuseScoreBridge)

    result = await bridge.process_sequence(steps)
    return to_json(result)

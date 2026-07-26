"""Composition tools — pure theory, no score connection required.

These answer musical questions and hand back notes ready to write. They
never touch the live score: the caller decides where the result goes,
which is the point — the engine proposes, the musician disposes.
"""

from typing import Any

from mcp_score import theory
from mcp_score.app import mcp
from mcp_score.tools import to_json

__all__: list[str] = []


@mcp.tool()
async def voice_progression(
    figures: list[str],
    key: str,
    num_parts: int = 4,
    bass_octave: int = 3,
    durations: list[dict[str, int]] | None = None,
    relax: list[str] | None = None,
) -> str:
    """Voice a chord progression into independent parts.

    ``realize_harmony`` answers "which notes are in this chord".
    This answers the harder question: which note does each *part* sing,
    given where it just was. music21 searches the voicings that satisfy
    the classical voice-leading rules — no parallel fifths or octaves, no
    voice crossing, sevenths resolved — and returns one that does.

    The result is a solution, not a judgement. It is the first voicing
    that breaks no rule, which is a floor on competence, not taste:
    spacing, doubling and which line carries the tune are still yours.

    Args:
        figures: Roman numerals read in ``key`` (``"I"``, ``"ii65"``,
            ``"V7/V"``, ``"Ger65"``) or absolute chord symbols
            (``"Dm7"``, ``"E-maj7"``), mixed freely. Up to 16.
        key: The key the roman numerals are read in (``"E-"`` major,
            ``"c"`` minor).
        num_parts: Parts to write, bass included (3 or 4).
        bass_octave: Where the bass part sits (default 3).
        durations: Optional per-chord ``{"numerator", "denominator"}``
            (fractions of a whole note; 1/4 is a quarter). Defaults to
            quarters throughout.
        relax: Voice-leading rules to switch off when nothing satisfies
            them all. When a progression has no solution, the reply names
            the rules that would unblock it.
    """
    if not figures:
        return to_json({"error": "figures must be a non-empty list."})
    if len(figures) > theory.MAX_PROGRESSION_FIGURES:
        return to_json(
            {
                "error": f"at most {theory.MAX_PROGRESSION_FIGURES} figures per "
                f"call, got {len(figures)}. Voice the progression in sections."
            }
        )
    if not all(figure.strip() for figure in figures):
        return to_json({"error": "every figure must be a non-empty string."})
    if num_parts not in (3, 4):
        return to_json({"error": "num_parts must be 3 or 4."})
    if durations is not None and len(durations) != len(figures):
        return to_json(
            {
                "error": f"durations must have one entry per figure "
                f"({len(figures)}), got {len(durations)}."
            }
        )
    resolved_durations = _resolve_durations(figures, durations)
    if isinstance(resolved_durations, str):
        return to_json({"error": resolved_durations})

    try:
        planned = theory.plan_progression_voicing(
            figures, key, num_parts=num_parts, bass_octave=bass_octave, relax=relax
        )
    except ValueError as exception:
        return to_json({"error": str(exception)})

    if not planned["solution_count"]:
        helpful = planned["relaxations_that_help"]
        return to_json(
            {
                "error": f"no {num_parts}-part voicing satisfies the "
                "voice-leading rules for this progression (0 solutions).",
                "solution_count": 0,
                "relaxations_that_help": helpful,
                "hint": (
                    f"retry with relax={helpful[:1]}"
                    if helpful
                    else "no single rule unblocks it — try a different "
                    "inversion, bass_octave, or num_parts=3."
                ),
            }
        )

    chords = planned["chords"]
    return to_json(
        {
            "success": True,
            "figures": figures,
            "key": key,
            "num_parts": num_parts,
            "solution_count": planned["solution_count"],
            "solution_policy": (
                f"first of {planned['solution_count']} rule-satisfying "
                "voicings (deterministic)"
            ),
            "chords": chords,
            "entries": _entry_shapes(chords, resolved_durations),
            "note": (
                "entries.chords writes the whole texture on one staff. For a "
                "grand staff, write entries.upper to the upper staff and "
                "entries.bass to the lower one at the same measure. This is "
                "the first voicing that breaks no rule, not a musical "
                "judgement — review spacing and doubling."
            ),
        }
    )


def _resolve_durations(
    figures: list[str], durations: list[dict[str, int]] | None
) -> list[dict[str, int]] | str:
    """Validate per-chord durations, defaulting to quarter notes."""
    if durations is None:
        return [{"numerator": 1, "denominator": 4} for _ in figures]
    resolved: list[dict[str, int]] = []
    for index, duration in enumerate(durations):
        numerator = duration.get("numerator", 1)
        denominator = duration.get("denominator", 4)
        if numerator < 1 or denominator < 1:
            return f"durations[{index}] values must be >= 1."
        resolved.append({"numerator": numerator, "denominator": denominator})
    return resolved


def _entry_shapes(
    chords: list[dict[str, Any]], durations: list[dict[str, int]]
) -> dict[str, list[dict[str, Any]]]:
    """Shape voiced chords three ways for the note-writing tool."""
    whole: list[dict[str, Any]] = []
    upper: list[dict[str, Any]] = []
    bass: list[dict[str, Any]] = []
    for chord, duration in zip(chords, durations, strict=False):
        names = [spelled["name"] for spelled in chord["pitches"]]
        whole.append({"chord": names, **duration})
        bass.append({"name": names[0], **duration})
        above = names[1:]
        if len(above) > 1:
            upper.append({"chord": above, **duration})
        elif above:
            upper.append({"name": above[0], **duration})
        else:
            upper.append({"rest": True, **duration})
    return {"chords": whole, "upper": upper, "bass": bass}


@mcp.tool()
async def realize_ornament(
    ornament: str,
    note: str,
    key: str,
    numerator: int = 1,
    denominator: int = 4,
) -> str:
    """Write out an ornament as the notes it stands for.

    The plugin cannot attach an ornament *symbol* to a note, but the
    notes a trill or a turn stands for can be written directly. music21
    knows the shapes and reads the key signature, so the auxiliary note
    of a mordent in E-flat is a B-flat, not a B.

    The returned run always sums to exactly the duration of the note it
    replaces, so writing it never shifts the rest of the bar.

    Args:
        ornament: ``"trill"``, ``"mordent"``, ``"inverted_mordent"``,
            ``"turn"``, or ``"inverted_turn"``.
        note: The ornamented note, octave required (``"C5"``).
        key: The key deciding the auxiliary notes (``"E-"``, ``"c"``).
        numerator: Duration numerator as a fraction of a whole note.
        denominator: Duration denominator (4 = quarter, 8 = eighth).
    """
    try:
        written = theory.realize_ornament_notes(
            ornament, note, numerator, denominator, key
        )
    except ValueError as exception:
        return to_json({"error": str(exception)})

    return to_json(
        {
            "success": True,
            "ornament": ornament,
            "note": note,
            "key": key,
            "duration": {"numerator": numerator, "denominator": denominator},
            "notes": written,
            "entries_for_add_live_notes": [
                {
                    "name": item["name"],
                    "numerator": item["numerator"],
                    "denominator": item["denominator"],
                }
                for item in written
            ],
            "note_on_use": (
                "write these in place of the plain note, at its beat and in "
                "its voice; they fill exactly its duration."
            ),
        }
    )

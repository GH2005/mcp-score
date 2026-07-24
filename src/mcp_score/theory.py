"""Music-theory helpers, powered by music21 -- the *writing* advisor.

The read path (:mod:`mcp_score.musicxml`) uses music21 to parse what
MuseScore exports. This module is the mirror image on the *write* side:
it turns musical intent into the concrete numbers the plugin needs.

Two responsibilities:

1. **Spelling.** The wire protocol carries a MIDI pitch and a MuseScore
   *tonal pitch class* (tpc) integer -- never a note name. music21 owns
   the musical decision of *which* enharmonic spelling is correct (D-flat
   vs C-sharp, key-aware); this module encodes that spelling into the tpc
   integer MuseScore expects. The QML no longer does any of this.

2. **Realization.** Roman numerals (``V7/V``) and chord symbols
   (``E-maj7``) are resolved to concrete, correctly spelled pitches via
   :mod:`music21.roman` and :mod:`music21.harmony`, so a caller can say
   "give me the dominant of the dominant in E-flat" and get notes back.

MuseScore tpc convention (verified against the plugin's apiProbe
round-trip, where MIDI 61 spelled C-sharp reads back tpc 21):

    step letters run F C G D A E B along the line of fifths;
    tpc = 7 * (alter + 2) + "FCGDAEB".index(step) - 1

giving F=13, C=14, G=15 ... Cb=7, Db=9, Eb=11 ... C#=21. MuseScore's
valid tpc range is -1 (Fbb) .. 33 (B##).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from music21 import (
    chord,
    converter,
    harmony,
    interval,
    key,
    note,
    pitch,
    roman,
    stream,
    voiceLeading,
)

from mcp_score.musicxml import Snapshot, get_measure

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "MIN_TPC",
    "MAX_TPC",
    "SpelledPitch",
    "analyze_musicxml",
    "musescore_voice",
    "name_to_pitch_tpc",
    "pitch_to_spelled",
    "pitch_tpc_to_name",
    "plan_transposition",
    "realize",
    "spell_midi",
    "tpc_of",
    "transpose_pitch_tpc",
]

#: MuseScore's valid tonal-pitch-class range: Fbb (-1) .. B## (33).
MIN_TPC = -1
MAX_TPC = 33

#: Line-of-fifths step order used by MuseScore's tpc encoding.
_TPC_STEPS = "FCGDAEB"


class SpelledPitch(TypedDict):
    """One fully-specified pitch, ready for the wire and for display."""

    name: str  # e.g. "E-4" (music21 spelling, '-' = flat)
    display: str  # e.g. "Eb4" (human spelling, 'b' = flat)
    midi: int  # 0..127
    tpc: int  # MuseScore tonal pitch class, MIN_TPC..MAX_TPC


def tpc_of(p: pitch.Pitch) -> int:
    """Encode a music21 pitch's spelling as a MuseScore tpc integer.

    Uses the pitch's *step* and *alter* only (octave-independent), so the
    enharmonic spelling music21 chose is preserved exactly. Double and
    triple accidentals outside MuseScore's range are respelled to the
    nearest in-range enharmonic (shifting by 12 fifths = same pitch).
    """
    step_index = _TPC_STEPS.index(p.step)
    tpc = 7 * (int(p.alter) + 2) + step_index - 1
    while tpc > MAX_TPC:
        tpc -= 12
    while tpc < MIN_TPC:
        tpc += 12
    return tpc


def pitch_to_spelled(p: pitch.Pitch) -> SpelledPitch:
    """Normalize a music21 pitch into a :class:`SpelledPitch`."""
    name = p.nameWithOctave  # music21 form: '-' for flats
    return {
        "name": name,
        "display": name.replace("-", "b"),
        "midi": p.midi,
        "tpc": tpc_of(p),
    }


def name_to_pitch_tpc(name: str) -> SpelledPitch:
    """Resolve a note name like ``"D-4"`` (or ``"Db4"``) to pitch + tpc.

    Accepts both music21 spelling (``-`` for flats) and the human ``b``
    form. The octave is required for a MIDI value; a bare ``"D-"`` is
    rejected because the wire needs an absolute pitch.

    Raises:
        ValueError: if the name is unparseable or lacks an octave.
    """
    raw = name.strip()
    # Translate a trailing/interior 'b' flat into music21's '-' spelling,
    # but never touch a leading note letter 'B'. music21 accepts '-'.
    m21_name = _to_music21_name(raw)
    try:
        p = pitch.Pitch(m21_name)
    except Exception as exc:  # music21 raises a variety of types
        raise ValueError(f"unparseable note name: {name!r}") from exc
    if p.octave is None:
        raise ValueError(f"note name must include an octave, got: {name!r}")
    return pitch_to_spelled(p)


def _to_music21_name(raw: str) -> str:
    """Convert a human note name to music21 spelling ('b' flat -> '-').

    The first character is the step letter (may be 'B'); every 'b' after
    it that is not part of the octave is a flat.
    """
    if not raw:
        raise ValueError("empty note name")
    head, tail = raw[0], raw[1:]
    return head + tail.replace("b", "-")


def pitch_tpc_to_name(midi: int, tpc: int) -> SpelledPitch:
    """Render a MIDI pitch + MuseScore tpc back into names.

    Inverse of :func:`tpc_of`, used to give the human-readable spelling of
    a note the plugin reported as raw ``(pitch, tpc)`` numbers. The step
    and accidental come from the tpc; the octave from the MIDI value.
    """
    idx = (tpc + 1) % 7
    step = _TPC_STEPS[idx]
    alter = (tpc + 1) // 7 - 2
    natural_pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
    octave = (midi - natural_pc - alter) // 12 - 1
    # Build from a natural-note name string (avoids music21's StepName
    # literal typing), then apply the accidental; changing the accidental
    # keeps the octave, so the final MIDI matches the input.
    p = pitch.Pitch(f"{step}{octave}")
    p.accidental = pitch.Accidental(int(alter))
    return pitch_to_spelled(p)


def spell_midi(midi: int, key_context: str | None = None) -> SpelledPitch:
    """Choose a sensible spelling for a bare MIDI pitch.

    With a *key_context* (e.g. ``"E-"`` major, ``"b-"`` minor) the pitch
    is spelled to fit that key's accidental family; without one, music21's
    default spelling is used. This is the fallback for callers who send a
    MIDI number instead of a name -- the result is still lossless on the
    wire because it carries an explicit tpc.
    """
    if not 0 <= midi <= 127:
        raise ValueError(f"midi must be 0..127, got: {midi}")
    p = pitch.Pitch(midi=midi)
    if key_context:
        k = key.Key(key_context)
        # Respell using the key's pitches when this pitch class appears
        # in the scale with a different spelling (e.g. MIDI 63 in E-flat
        # should be E-flat, not D-sharp).
        for scale_pitch in k.pitches:
            if scale_pitch.pitchClass == p.pitchClass:
                spelled = pitch.Pitch(midi=midi)
                spelled.step = scale_pitch.step
                spelled.accidental = scale_pitch.accidental
                p = spelled
                break
    return pitch_to_spelled(p)


def realize(figure: str, key_name: str, octave: int = 4) -> list[SpelledPitch]:
    """Resolve a roman numeral or chord symbol to spelled pitches.

    ``figure`` may be a roman numeral read in the given key (``"V7/V"``,
    ``"bVII"``, ``"ii65"``, ``"Ger65"``) or an absolute chord symbol
    (``"E-maj7"``, ``"F#m7b5"``). Roman numerals are tried first; if that
    fails the figure is parsed as a chord symbol. ``octave`` places the
    chord root near that octave.

    Raises:
        ValueError: if the figure parses as neither.
    """
    k = key.Key(key_name)
    pitches = _roman_pitches(figure, k) or _chord_symbol_pitches(figure)
    if pitches is None:
        raise ValueError(
            f"could not parse {figure!r} as a roman numeral in {key_name} "
            f"or as a chord symbol"
        )
    pitches = sorted(pitches, key=lambda p: p.ps)
    # Anchor the lowest pitch into the requested octave. Shifting by whole
    # octaves never changes a pitch's step, accidental, or tpc.
    shift = octave - (pitches[0].octave or 4)
    if shift:
        pitches = [_shift_octaves(p, shift) for p in pitches]
    return [pitch_to_spelled(p) for p in pitches]


def _shift_octaves(p: pitch.Pitch, octaves: int) -> pitch.Pitch:
    """Return a copy of *p* moved by whole octaves, spelling preserved."""
    shifted = pitch.Pitch(step=p.step, octave=(p.octave or 4) + octaves)
    shifted.accidental = p.accidental
    return shifted


def _roman_pitches(figure: str, k: key.Key) -> list[pitch.Pitch] | None:
    try:
        rn = roman.RomanNumeral(figure, k)
    except Exception:
        return None
    pitches = list(rn.pitches)
    return pitches or None


def _chord_symbol_pitches(figure: str) -> list[pitch.Pitch] | None:
    try:
        cs = harmony.ChordSymbol(figure)
    except Exception:
        return None
    pitches = list(cs.pitches)
    return pitches or None


def transpose_pitch_tpc(midi: int, tpc: int, semitones: int) -> tuple[int, int]:
    """Transpose a (midi, tpc) pair, keeping a musical enharmonic spelling.

    Reconstructs the spelled pitch from ``(midi, tpc)``, applies a
    chromatic interval via music21 (which spells the result sensibly),
    and re-encodes. Replaces the plugin's hand-rolled ``semitoneToTpcDelta``
    table with music21's context-aware interval spelling.

    Returns:
        The transposed ``(midi, tpc)``.
    """
    spelled = pitch_tpc_to_name(midi, tpc)
    p = pitch.Pitch(spelled["name"])
    moved = p.transpose(interval.ChromaticInterval(semitones))
    return moved.midi, tpc_of(moved)


def musescore_voice(event: dict[str, Any]) -> int:
    """Map a snapshot event's voice to MuseScore's 0-indexed voice.

    MusicXML numbers voices from 1 and numbers them across a whole part,
    so a two-staff piano uses 1-4 for the upper staff and 5-8 for the
    lower one -- while MuseScore numbers voices 0-3 within *each* staff.
    Taking the remainder maps both staves back onto 0-3.

    A measure with a single voice carries no voice marker at all, which
    means voice 0.
    """
    raw = event.get("voice")
    if raw is None:
        return 0
    try:
        return (int(raw) - 1) % 4
    except (TypeError, ValueError):
        return 0


def _spelled_ascending(event: dict[str, Any]) -> list[SpelledPitch]:
    """A chord/note event's pitches, spelled, in ascending-pitch order.

    The snapshot stores ``names`` sorted *alphabetically* and ``midi``
    sorted numerically, so the two lists do not correspond element by
    element. Names are re-sorted by their actual pitch here, which is the
    order the plugin walks a chord in (see notesByPitch in the QML).
    """
    spelled: list[SpelledPitch] = []
    for name in event.get("names", []):
        try:
            spelled.append(name_to_pitch_tpc(name))
        except ValueError:
            continue
    spelled.sort(key=lambda s: s["midi"])
    return spelled


def plan_transposition(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    semitones: int,
    voice: int | None = None,
) -> list[dict[str, Any]] | str:
    """Compute per-voice pitch edits for transposing a passage.

    Walks the snapshot in the same order the plugin walks the score
    (measure, then tick, then ascending pitch within a chord) so the
    resulting edits line up positionally with what ``setPitches`` finds.

    Args:
        snapshot: A parsed MusicXML snapshot of the live score.
        staff: Staff index (0-indexed).
        start_measure: First measure (1-indexed, inclusive).
        end_measure: Last measure (1-indexed, inclusive).
        semitones: Semitones to transpose by.
        voice: Restrict to one MuseScore voice (0-3), or ``None`` for all.

    Returns:
        A list of ``{"voice": int, "edits": [...]}`` dicts, one per voice
        that has notes, or an error string.
    """
    if str(staff) not in snapshot["staves"]:
        available = sorted(int(s) for s in snapshot["staves"])
        return f"staff must be one of {available}, got: {staff}"

    per_voice: dict[int, list[dict[str, int]]] = {}
    for measure in range(start_measure, end_measure + 1):
        content = get_measure(snapshot, staff, measure)
        if not content:
            continue
        for event in content["events"]:
            if event.get("kind") == "rest":
                continue
            event_voice = musescore_voice(event)
            if voice is not None and event_voice != voice:
                continue
            for spelled in _spelled_ascending(event):
                new_midi, new_tpc = transpose_pitch_tpc(
                    spelled["midi"], spelled["tpc"], semitones
                )
                if not 0 <= new_midi <= 127:
                    return (
                        f"transposing {spelled['display']} by {semitones} "
                        f"semitones leaves the MIDI range (0-127)."
                    )
                per_voice.setdefault(event_voice, []).append(
                    {
                        "oldPitch": spelled["midi"],
                        "newPitch": new_midi,
                        "newTpc": new_tpc,
                    }
                )

    return [
        {"voice": v, "edits": per_voice[v]} for v in sorted(per_voice) if per_voice[v]
    ]


# ── Analysis: what is this passage doing? ────────────────────────────
#
# Everything below is advisory. It describes; it never decides. Parallel
# fifths are a mistake in a chorale, the whole point in organum, and
# ordinary in power chords -- so these functions report what they see and
# leave the musical judgement to the caller.


def _excerpt(
    score: stream.Score, start_measure: int, end_measure: int, staff: int | None
) -> stream.Score:
    """Extract a measure range (and optionally one staff) as a new score."""
    parts = list(score.parts)
    if staff is not None:
        if not 0 <= staff < len(parts):
            raise ValueError(f"staff must be 0..{len(parts) - 1}, got: {staff}")
        parts = [parts[staff]]
    excerpt = stream.Score()
    for part in parts:
        excerpt.insert(0, part.measures(start_measure, end_measure))
    return excerpt


def _verticals(excerpt: stream.Score) -> list[chord.Chord]:
    """Every simultaneity in the excerpt, in time order."""
    chordified = excerpt.chordify()
    return [
        c for c in chordified.recurse().getElementsByClass(chord.Chord) if c.pitches
    ]


def _measure_of(element: Any) -> int | None:
    """The measure number an element sits in, if it is known."""
    measure = element.getContextByClass(stream.Measure)
    return None if measure is None else measure.number


def _harmony_reading(
    verticals: list[chord.Chord], tonic: key.Key
) -> list[dict[str, Any]]:
    """Read each simultaneity as a roman numeral in *tonic*."""
    reading: list[dict[str, Any]] = []
    for vertical in verticals:
        if len(vertical.pitches) < 2:
            continue  # a single note has no harmony to read
        entry: dict[str, Any] = {
            "measure": _measure_of(vertical),
            "offset": round(float(vertical.offset), 4),
            "pitches": [p.nameWithOctave for p in vertical.pitches],
            "chord": vertical.pitchedCommonName,
        }
        try:
            entry["roman"] = roman.romanNumeralFromChord(vertical, tonic).figure
        except Exception:  # noqa: BLE001 - music21 raises broadly on odd chords
            entry["roman"] = None
        reading.append(entry)
    return reading


#: Voice-leading relations worth reporting, and how to describe them.
_VOICE_LEADING_CHECKS: tuple[tuple[str, str], ...] = (
    ("parallelFifth", "parallel fifths"),
    ("parallelOctave", "parallel octaves"),
    ("parallelUnison", "parallel unisons"),
    ("hiddenFifth", "hidden (direct) fifths"),
    ("hiddenOctave", "hidden (direct) octaves"),
)


def _pair_motion(
    lower_pair: tuple[pitch.Pitch, pitch.Pitch],
    upper_pair: tuple[pitch.Pitch, pitch.Pitch],
) -> list[str]:
    """Voice-leading relations between two voices moving together.

    Each pair is (note now, note next) for one voice.
    """
    quartet = voiceLeading.VoiceLeadingQuartet(
        note.Note(upper_pair[0].nameWithOctave),
        note.Note(upper_pair[1].nameWithOctave),
        note.Note(lower_pair[0].nameWithOctave),
        note.Note(lower_pair[1].nameWithOctave),
    )
    found: list[str] = []
    for attribute, description in _VOICE_LEADING_CHECKS:
        try:
            if bool(getattr(quartet, attribute)()):
                found.append(description)
        except Exception:  # noqa: BLE001 - music21 raises broadly
            continue
    try:
        if bool(quartet.voiceCrossing()):
            found.append("voice crossing")
    except Exception:  # noqa: BLE001 - music21 raises broadly
        pass
    return found


def _voice_leading(verticals: list[chord.Chord]) -> list[dict[str, Any]]:
    """Observations about motion between consecutive simultaneities.

    Voices are paired by their position in each chord (lowest with
    lowest, and so on). That is an approximation when the texture changes
    thickness, so neighbouring slices are compared only across the voices
    they have in common.
    """
    observations: list[dict[str, Any]] = []
    for index in range(len(verticals) - 1):
        first, second = verticals[index], verticals[index + 1]
        now = sorted(first.pitches, key=lambda p: p.ps)
        nxt = sorted(second.pitches, key=lambda p: p.ps)
        shared = min(len(now), len(nxt))
        if shared < 2:
            continue
        for lower in range(shared):
            for upper in range(lower + 1, shared):
                for description in _pair_motion(
                    (now[lower], nxt[lower]), (now[upper], nxt[upper])
                ):
                    observations.append(
                        {
                            "observation": description,
                            "measure": _measure_of(first),
                            "between": [
                                f"{now[lower].nameWithOctave}"
                                f"->{nxt[lower].nameWithOctave}",
                                f"{now[upper].nameWithOctave}"
                                f"->{nxt[upper].nameWithOctave}",
                            ],
                        }
                    )
    return observations


def _ambitus(excerpt: stream.Score) -> list[dict[str, Any]]:
    """Lowest and highest sounding note of each staff in the excerpt."""
    spans: list[dict[str, Any]] = []
    for index, part in enumerate(excerpt.parts):
        pitches = [p for n in part.recurse().notes for p in n.pitches]
        if not pitches:
            spans.append({"staff": index, "lowest": None, "highest": None})
            continue
        lowest = min(pitches, key=lambda p: p.ps)
        highest = max(pitches, key=lambda p: p.ps)
        spans.append(
            {
                "staff": index,
                "lowest": lowest.nameWithOctave,
                "highest": highest.nameWithOctave,
                "semitones": int(highest.ps - lowest.ps),
            }
        )
    return spans


def _tonic_for(detected: str | None, key_name: str | None) -> key.Key:
    """The key to read harmony in: the caller's, the detected one, or C."""
    if key_name:
        try:
            return key.Key(key_name)
        except Exception as exception:  # noqa: BLE001
            raise ValueError(f"unparseable key: {key_name!r}") from exception
    if detected:
        parts = detected.split()
        if len(parts) == 2:
            return key.Key(parts[0], parts[1])
    return key.Key("C")


def analyze_musicxml(
    path: Path,
    start_measure: int,
    end_measure: int,
    staff: int | None = None,
    key_name: str | None = None,
) -> dict[str, Any]:
    """Describe a passage of a MusicXML score: key, harmony, voice leading.

    Args:
        path: MusicXML file (typically a live-score snapshot).
        start_measure: First measure (1-indexed, inclusive).
        end_measure: Last measure (1-indexed, inclusive).
        staff: Restrict to one staff (0-indexed), or ``None`` for all.
        key_name: Read harmony in this key instead of the detected one.

    Returns:
        A report dict. Every entry is an observation, not a verdict.
    """
    parsed = converter.parse(str(path))
    if not isinstance(parsed, stream.Score):
        raise ValueError(f"expected a score from {path}, got {type(parsed).__name__}")

    excerpt = _excerpt(parsed, start_measure, end_measure, staff)
    verticals = _verticals(excerpt)

    try:
        detected = str(excerpt.analyze("key"))
    except Exception:  # noqa: BLE001 - analysis fails on very short excerpts
        detected = None

    tonic = _tonic_for(detected, key_name)

    return {
        "success": True,
        "start_measure": start_measure,
        "end_measure": end_measure,
        "staff": staff,
        "key": {
            "detected": detected,
            "used_for_harmony": str(tonic),
            "requested": key_name,
        },
        "harmony": _harmony_reading(verticals, tonic),
        "voice_leading": _voice_leading(verticals),
        "ambitus": _ambitus(excerpt),
        "note": (
            "Advisory only. These are observations, not rules -- whether any "
            "of them is a problem depends on the style you are writing in."
        ),
    }

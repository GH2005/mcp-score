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

from fractions import Fraction
from typing import TYPE_CHECKING, Any, TypedDict

from music21 import (
    chord,
    converter,
    expressions,
    harmony,
    interval,
    key,
    meter,
    note,
    pitch,
    roman,
    scale,
    stream,
    voiceLeading,
)
from music21.figuredBass import realizer, rules

from mcp_score.musicxml import Snapshot, get_measure

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "DEFAULT_BASS_OCTAVE",
    "DEFAULT_MAX_PITCH",
    "MAX_PROGRESSION_FIGURES",
    "MIN_TPC",
    "MAX_TPC",
    "ORNAMENTS",
    "RELAXABLE_RULES",
    "SpelledPitch",
    "analyze_musicxml",
    "musescore_voice",
    "name_to_pitch_tpc",
    "pitch_to_spelled",
    "pitch_tpc_to_name",
    "plan_diatonic_transposition",
    "plan_inversion",
    "plan_progression_voicing",
    "plan_retrograde",
    "plan_sequence",
    "plan_transposition",
    "realize",
    "realize_detailed",
    "realize_ornament_notes",
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
    return realize_detailed(figure, key_name, octave)[0]


def realize_detailed(
    figure: str, key_name: str, octave: int = 4
) -> tuple[list[SpelledPitch], dict[str, Any]]:
    """Like :func:`realize`, but also reports what the figure *means*.

    The second element describes the chord music21 understood: which
    parser accepted it, its root and bass, and -- the part a caller
    cannot recover from the pitches alone -- its inversion and, for a
    secondary function like ``V7/V``, the key it tonicizes.

    Raises:
        ValueError: if the figure parses as neither.
    """
    k = key.Key(key_name)
    parsed: chord.Chord | None = _parse_roman(figure, k)
    kind = "roman"
    if parsed is None:
        parsed = _parse_chord_symbol(figure)
        kind = "chord_symbol"
    if parsed is None:
        raise ValueError(
            f"could not parse {figure!r} as a roman numeral in {key_name} "
            f"or as a chord symbol"
        )

    pitches = sorted(parsed.pitches, key=lambda p: p.ps)
    # Anchor the lowest pitch into the requested octave. Shifting by whole
    # octaves never changes a pitch's step, accidental, or tpc.
    shift = octave - (pitches[0].octave or 4)
    if shift:
        pitches = [_shift_octaves(p, shift) for p in pitches]
    return [pitch_to_spelled(p) for p in pitches], _figure_metadata(parsed, kind)


def _figure_metadata(parsed: chord.Chord, kind: str) -> dict[str, Any]:
    """Describe a parsed chord: root, bass, inversion, tonicized key."""
    metadata: dict[str, Any] = {"parsed_as": kind}
    for field, getter in (("root", parsed.root), ("bass", parsed.bass)):
        try:
            metadata[field] = getter().name.replace("-", "b")
        except Exception:  # music21 declines on chords it cannot stack
            metadata[field] = None
    for field, call in (
        ("inversion", parsed.inversion),
        ("inversion_name", parsed.inversionName),
    ):
        try:
            value = call()
        except Exception:
            value = None
        metadata[field] = str(value) if field == "inversion_name" and value else value
    metadata["quality"] = getattr(parsed, "quality", None)
    secondary = getattr(parsed, "secondaryRomanNumeralKey", None)
    metadata["secondary_key"] = str(secondary) if secondary is not None else None
    return metadata


def _shift_octaves(p: pitch.Pitch, octaves: int) -> pitch.Pitch:
    """Return a copy of *p* moved by whole octaves, spelling preserved."""
    shifted = pitch.Pitch(step=p.step, octave=(p.octave or 4) + octaves)
    shifted.accidental = p.accidental
    return shifted


def _parse_roman(figure: str, k: key.Key) -> roman.RomanNumeral | None:
    """Parse a figure as a roman numeral in *k*, or ``None``."""
    try:
        rn = roman.RomanNumeral(figure, k)
    except Exception:
        return None
    return rn if rn.pitches else None


def _parse_chord_symbol(figure: str) -> harmony.ChordSymbol | None:
    """Parse a figure as an absolute chord symbol, or ``None``."""
    try:
        cs = harmony.ChordSymbol(figure)
    except Exception:
        return None
    return cs if cs.pitches else None


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
    return _true_midi(moved), tpc_of(moved)


def _true_midi(p: pitch.Pitch) -> int:
    """The MIDI number of *p*, without music21's wrap into 0..127.

    ``Pitch.midi`` folds a pitch outside the MIDI range back inside it by
    octaves, so a note transposed off the top of the range comes back
    looking like a valid -- but far lower -- note. Reading pitch space
    directly keeps the out-of-range value visible, which is what lets the
    callers refuse instead of silently writing the wrong octave.
    """
    return int(p.ps)


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

    def move(spelled: SpelledPitch, _measure: int) -> tuple[int, int] | str:
        new_midi, new_tpc = transpose_pitch_tpc(
            spelled["midi"], spelled["tpc"], semitones
        )
        if not 0 <= new_midi <= 127:
            return (
                f"transposing {spelled['display']} by {semitones} "
                f"semitones leaves the MIDI range (0-127)."
            )
        return new_midi, new_tpc

    return _plan_pitch_edits(snapshot, staff, start_measure, end_measure, voice, move)


def _plan_pitch_edits(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    voice: int | None,
    transform: Callable[[SpelledPitch, int], tuple[int, int] | str],
) -> list[dict[str, Any]] | str:
    """Walk a passage and build ``setPitches`` edits from *transform*.

    Walks the snapshot in the same order the plugin walks the score
    (measure, then tick, then ascending pitch within a chord) so the
    resulting edits line up positionally with what ``setPitches`` finds.
    *transform* maps one spelled note to its replacement ``(midi, tpc)``,
    or returns an error string, which aborts the whole plan -- a passage
    is re-pitched entirely or not at all.
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
                outcome = transform(spelled, measure)
                if isinstance(outcome, str):
                    return outcome
                new_midi, new_tpc = outcome
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


# ── Diatonic motion: moving music *within* a key ─────────────────────
#
# Chromatic transposition moves every note by the same number of
# semitones. Diatonic motion moves every note by the same number of
# *scale steps*, so the music stays in its key -- "up a third" from the
# leading note is a minor third, from the tonic a major one. music21's
# scale machinery owns that decision; do not reach for GenericInterval,
# which carries the source accidental along and is wrong on six of the
# seven degrees of a flat key.


def _parse_key(key_name: str) -> key.Key | None:
    """Parse a key name (``"E-"`` major, ``"c"`` minor), or ``None``."""
    try:
        return key.Key(_to_music21_name(key_name.strip()))
    except Exception:
        return None


def _in_key(p: pitch.Pitch, k: key.Key) -> bool:
    """Whether *p*'s spelling belongs to *k*'s scale."""
    return p.name in {scale_pitch.name for scale_pitch in k.pitches}


def _step_within_key(p: pitch.Pitch, k: key.Key, degrees: int) -> pitch.Pitch | None:
    """Move *p* by signed scale *degrees* within *k*.

    ``degrees`` counts scale steps: +1 is up a second, +2 up a third,
    -4 down a fifth. A note foreign to the key is snapped onto the
    nearest scale tone in the direction of travel, which consumes the
    first step -- in E-flat, a chromatic E natural moved up one degree
    lands on F, and that is the musically right answer.
    """
    direction = scale.Direction.ASCENDING if degrees > 0 else scale.Direction.DESCENDING
    try:
        return k.nextPitch(
            p, direction=direction, stepSize=abs(degrees), getNeighbor=True
        )
    except Exception:
        return None


def plan_diatonic_transposition(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    degrees: int,
    key_name: str,
    voice: int | None = None,
) -> dict[str, Any] | str:
    """Compute pitch edits for moving a passage within a key.

    Args:
        snapshot: A parsed MusicXML snapshot of the live score.
        staff: Staff index (0-indexed).
        start_measure: First measure (1-indexed, inclusive).
        end_measure: Last measure (1-indexed, inclusive).
        degrees: Signed scale steps (+2 = up a third, -1 = down a second).
        key_name: The key to stay inside (``"E-"``, ``"c"``).
        voice: Restrict to one MuseScore voice (0-3), or ``None`` for all.

    Returns:
        ``{"plans": [...], "snapped": [...]}`` where *plans* has the same
        shape :func:`plan_transposition` returns and *snapped* lists the
        chromatic notes that were pulled onto the scale, or an error
        string.
    """
    if degrees == 0:
        return "degrees must be non-zero (+2 = up a third, -1 = down a second)."
    k = _parse_key(key_name)
    if k is None:
        return f"unparseable key: {key_name!r}. Use e.g. 'E-' major or 'c' minor."

    snapped: list[dict[str, Any]] = []

    def move(spelled: SpelledPitch, measure: int) -> tuple[int, int] | str:
        p = pitch.Pitch(spelled["name"])
        was_in_key = _in_key(p, k)
        moved = _step_within_key(p, k, degrees)
        if moved is None:
            return f"could not move {spelled['display']} by {degrees} degrees in {k}."
        if not 0 <= _true_midi(moved) <= 127:
            return (
                f"moving {spelled['display']} by {degrees} degrees "
                f"leaves the MIDI range (0-127)."
            )
        if not was_in_key:
            snapped.append(
                {
                    "measure": measure,
                    "from": spelled["display"],
                    "to": moved.nameWithOctave.replace("-", "b"),
                }
            )
        return _true_midi(moved), tpc_of(moved)

    plans = _plan_pitch_edits(snapshot, staff, start_measure, end_measure, voice, move)
    if isinstance(plans, str):
        return plans
    return {"plans": plans, "snapped": snapped}


def plan_inversion(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    axis: str,
    key_name: str,
    voice: int | None = None,
) -> dict[str, Any] | str:
    """Compute pitch edits for mirroring a passage around an axis note.

    Inversion here is diatonic: letters reflect around the axis letter
    and the key signature supplies the accidentals, so a line inverted
    in E-flat stays in E-flat. A chromatically inflected note keeps its
    reflected letter but loses the inflection -- every such note is
    reported in *snapped*. Rhythm is untouched, so this rides
    ``setPitches`` and cannot disturb the bar.

    Args:
        axis: The mirror note, octave required (``"G4"``).
        key_name: The key supplying accidentals for the reflected notes.

    Returns:
        ``{"plans": [...], "snapped": [...]}``, or an error string.
    """
    try:
        axis_spelled = name_to_pitch_tpc(axis)
    except ValueError as exception:
        return f"axis: {exception}"
    k = _parse_key(key_name)
    if k is None:
        return f"unparseable key: {key_name!r}. Use e.g. 'E-' major or 'c' minor."

    axis_dnn = pitch.Pitch(axis_spelled["name"]).diatonicNoteNum
    snapped: list[dict[str, Any]] = []

    def reflect(spelled: SpelledPitch, measure: int) -> tuple[int, int] | str:
        p = pitch.Pitch(spelled["name"])
        new_dnn = 2 * axis_dnn - p.diatonicNoteNum
        if not 1 <= new_dnn <= 70:
            return (
                f"inverting {spelled['display']} around {axis} "
                f"leaves the MIDI range (0-127)."
            )
        mirrored = pitch.Pitch()
        mirrored.diatonicNoteNum = new_dnn
        mirrored.accidental = k.accidentalByStep(mirrored.step)
        if not 0 <= _true_midi(mirrored) <= 127:
            return (
                f"inverting {spelled['display']} around {axis} "
                f"leaves the MIDI range (0-127)."
            )
        if not _in_key(p, k):
            snapped.append(
                {
                    "measure": measure,
                    "from": spelled["display"],
                    "to": mirrored.nameWithOctave.replace("-", "b"),
                    "reason": "chromatic inflection dropped; key signature applied",
                }
            )
        return _true_midi(mirrored), tpc_of(mirrored)

    plans = _plan_pitch_edits(
        snapshot, staff, start_measure, end_measure, voice, reflect
    )
    if isinstance(plans, str):
        return plans
    return {"plans": plans, "snapped": snapped}


# ── Re-entry: transforms that have to rewrite rhythm as well ─────────
#
# Inversion only re-pitches notes that are already there, so it can ride
# setPitches. Retrograde and sequence change *when* notes happen, which
# the wire can only express by writing the passage again note by note.
# That is destructive and cannot represent everything MuseScore can hold,
# so the source is validated hard first and refused with a named cause
# rather than silently flattened.


def _wire_duration(ql: float) -> tuple[int, int] | None:
    """Convert a quarter-length into a wire duration, or ``None``.

    The wire measures durations as a fraction of a *whole* note, so a
    quarter is 1/4. Denominators that are not powers of two are tuplets,
    which the plugin has no way to create.
    """
    fraction = Fraction(ql).limit_denominator(64) / 4
    denominator = fraction.denominator
    if denominator & (denominator - 1):
        return None
    return fraction.numerator, denominator


def _reentry_events(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    voice: int,
) -> list[dict[str, Any]] | str:
    """Collect one voice's events for rewriting, or refuse with a reason.

    Refuses anything the note-by-note write path cannot reproduce: ties
    (the far side would be re-attacked as a fresh onset), grace notes,
    tuplets, a voice that does not fill every bar of the range, and a
    meter change inside the range (which would move the barlines the
    rewrite has to land on).
    """
    if str(staff) not in snapshot["staves"]:
        available = sorted(int(s) for s in snapshot["staves"])
        return f"staff must be one of {available}, got: {staff}"

    collected: list[dict[str, Any]] = []
    measure_totals: list[tuple[int, Fraction]] = []
    for measure in range(start_measure, end_measure + 1):
        content = get_measure(snapshot, staff, measure)
        if not content:
            return f"measure {measure} has no content on staff {staff}."
        if measure > start_measure and content.get("time"):
            return (
                f"measure {measure} changes the time signature. Re-entering "
                "a passage across a meter change would move the barlines; "
                "transform the sections either side separately."
            )
        events = [
            event for event in content["events"] if musescore_voice(event) == voice
        ]
        events.sort(key=lambda e: float(e.get("offset", 0.0)))
        if not events:
            return (
                f"measure {measure} has nothing in voice {voice}. A rewrite "
                "needs every bar of the range filled in that voice."
            )
        position = Fraction(0)
        for event in events:
            if event.get("tie"):
                return (
                    f"measure {measure} contains a tied note. Re-entering it "
                    "would re-attack the far side of the tie as a new note; "
                    "the wire cannot write ties."
                )
            ql = float(event.get("ql", 0.0))
            if ql <= 0:
                return (
                    f"measure {measure} contains a zero-length (grace) note, "
                    "which cannot be re-entered."
                )
            duration = _wire_duration(ql)
            if duration is None:
                return (
                    f"measure {measure} contains a tuplet, which the plugin "
                    "cannot write. Transform this passage by hand."
                )
            offset = Fraction(float(event.get("offset", 0.0))).limit_denominator(64)
            if offset != position:
                return (
                    f"measure {measure} has a gap in voice {voice} at beat "
                    f"{float(position) + 1:g}. A rewrite needs a continuous line."
                )
            position += Fraction(ql).limit_denominator(64)
            numerator, denominator = duration
            collected.append(
                {
                    "measure": measure,
                    "kind": event.get("kind"),
                    "names": [spelled["name"] for spelled in _spelled_ascending(event)],
                    "numerator": numerator,
                    "denominator": denominator,
                }
            )
        measure_totals.append((measure, position))

    lengths = {total for _, total in measure_totals}
    if len(lengths) > 1:
        uneven = ", ".join(
            f"m{measure} = {float(total):g} quarters"
            for measure, total in measure_totals
        )
        return (
            f"voice {voice} does not fill every bar of the range equally "
            f"({uneven}). A rewrite needs full bars so the barlines survive."
        )
    return collected


def _entry_for(event: dict[str, Any], names: list[str] | None = None) -> dict[str, Any]:
    """Shape one collected event as an ``add_live_notes`` entry."""
    entry: dict[str, Any] = {
        "numerator": event["numerator"],
        "denominator": event["denominator"],
    }
    pitches = names if names is not None else event["names"]
    if event["kind"] == "rest" or not pitches:
        entry["rest"] = True
    elif len(pitches) == 1:
        entry["name"] = pitches[0]
    else:
        entry["chord"] = list(pitches)
    return entry


def plan_retrograde(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    voice: int = 0,
) -> dict[str, Any] | str:
    """Compute the entries that rewrite a passage backwards.

    Pitches *and* rhythm reverse. Because the source is required to fill
    every bar of the range under one meter, the reversed run tiles the
    same bars exactly -- the mirror of a barline is still a barline.

    Returns:
        ``{"entries": [...]}`` ready for the note-writing path, or an
        error string naming what made the passage unreproducible.
    """
    collected = _reentry_events(snapshot, staff, start_measure, end_measure, voice)
    if isinstance(collected, str):
        return collected
    return {"entries": [_entry_for(event) for event in reversed(collected)]}


def plan_sequence(
    snapshot: Snapshot,
    staff: int,
    start_measure: int,
    end_measure: int,
    copies: int,
    degrees: int,
    key_name: str,
    voice: int = 0,
) -> dict[str, Any] | str:
    """Compute repeated, transposed copies of a motif.

    Copy *n* starts one motif-length after copy *n-1* and sits
    ``degrees * n`` scale steps above (or below) the original, which is
    what a musician means by "sequence it up a step". ``degrees = 0``
    repeats the motif verbatim.

    Returns:
        ``{"copies": [{"measure", "shift_degrees", "entries", "snapped"}],
        "destination_end": int}``, or an error string.
    """
    if copies < 1:
        return "copies must be >= 1."
    k = _parse_key(key_name)
    if k is None:
        return f"unparseable key: {key_name!r}. Use e.g. 'E-' major or 'c' minor."

    span = end_measure - start_measure + 1
    destination_end = end_measure + copies * span
    measure_count = int(snapshot.get("measure_count", 0))
    if destination_end > measure_count:
        shortfall = destination_end - measure_count
        return (
            f"{copies} cop{'y' if copies == 1 else 'ies'} of a {span}-measure "
            f"motif would run to measure {destination_end}, but the score ends "
            f"at {measure_count}. Call append_live_measures({shortfall}) first."
        )

    collected = _reentry_events(snapshot, staff, start_measure, end_measure, voice)
    if isinstance(collected, str):
        return collected

    for measure in range(end_measure + 1, destination_end + 1):
        content = get_measure(snapshot, staff, measure)
        if content and content.get("time"):
            return (
                f"measure {measure} changes the time signature, so the copies "
                "would not line up with the barlines there."
            )

    planned: list[dict[str, Any]] = []
    for copy_index in range(1, copies + 1):
        shift = degrees * copy_index
        snapped: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        for event in collected:
            if event["kind"] == "rest" or not event["names"]:
                entries.append(_entry_for(event))
                continue
            moved_names: list[str] = []
            for name in event["names"]:
                p = pitch.Pitch(name)
                if shift == 0:
                    moved_names.append(name)
                    continue
                was_in_key = _in_key(p, k)
                moved = _step_within_key(p, k, shift)
                if moved is None or not 0 <= _true_midi(moved) <= 127:
                    return (
                        f"copy {copy_index} moves {name.replace('-', 'b')} "
                        f"by {shift} degrees, which leaves the MIDI range."
                    )
                if not was_in_key:
                    snapped.append(
                        {
                            "copy": copy_index,
                            "from": name.replace("-", "b"),
                            "to": moved.nameWithOctave.replace("-", "b"),
                        }
                    )
                moved_names.append(moved.nameWithOctave)
            entries.append(_entry_for(event, moved_names))
        planned.append(
            {
                "measure": start_measure + copy_index * span,
                "shift_degrees": shift,
                "entries": entries,
                "snapped": snapped,
            }
        )

    return {"copies": planned, "destination_end": destination_end}


# ── Voicing: from figures to actual parts ────────────────────────────
#
# realize() answers "which notes are in this chord". Voicing answers the
# harder question: which note does each *part* sing, given where it just
# was. music21's figured-bass realizer is a constraint solver for exactly
# that -- it searches the voicings that satisfy the classical
# voice-leading rules and rejects the rest.

#: Most figures we will search voicings for in one call. The solver is
#: fast, but a caller asking for a hundred chords wants a piece written,
#: not a progression voiced.
MAX_PROGRESSION_FIGURES = 16

#: Above this many figures, skip the "which rule is blocking me" probe:
#: it re-runs the solver once per rule.
PROGRESSION_PROBE_LIMIT = 8

#: Where the bass part is placed before solving. Registering an octave on
#: every element is mandatory -- see plan_progression_voicing.
DEFAULT_BASS_OCTAVE = 3

#: Ceiling for the top part, so solutions stay in a singable register.
DEFAULT_MAX_PITCH = "B5"

#: Rules a caller may switch off when nothing satisfies all of them.
#: Every name is an attribute of music21's figuredBass Rules object.
RELAXABLE_RULES = frozenset(
    {
        "forbidParallelFifths",
        "forbidParallelOctaves",
        "forbidHiddenFifths",
        "forbidHiddenOctaves",
        "forbidVoiceOverlap",
        "forbidVoiceCrossing",
        "forbidIncompletePossibilities",
        "resolveDominantSeventhProperly",
        "resolveDiminishedSeventhProperly",
        "resolveAugmentedSixthProperly",
    }
)


def _progression_line(
    figures: list[str], k: key.Key, bass_octave: int
) -> realizer.FiguredBassLine:
    """Build a figured-bass line from roman numerals or chord symbols.

    Raises:
        ValueError: if a figure parses as neither.
    """
    line = realizer.FiguredBassLine(k, meter.TimeSignature("4/4"))
    for figure in figures:
        element: chord.Chord | None = _parse_roman(figure, k)
        if element is None:
            element = _parse_chord_symbol(figure)
        if element is None:
            raise ValueError(
                f"could not parse {figure!r} as a roman numeral in {k} "
                f"or as a chord symbol"
            )
        # The solver needs to know where the bass actually sits. An
        # element whose bass carries no octave yields *zero* solutions
        # with no explanation -- registering it is what makes the search
        # work at all.
        element.bass().octave = bass_octave
        # addElement is annotated for a bass Note, but it dispatches on
        # RomanNumeral and ChordSymbol too -- that is the documented way
        # to build a line from figures rather than from a bass part.
        line.addElement(element)  # pyright: ignore[reportArgumentType]
    return line


def _first_progression(
    realization: realizer.Realization,
) -> list[tuple[pitch.Pitch, ...]]:
    """The first solution, without enumerating the others.

    ``getAllPossibilityProgressions`` materializes every solution, and a
    sixteen-chord progression can have a million of them. The solver has
    already pruned each segment's ``movements`` map to branches that
    complete, so following the first branch at every step lands on the
    same progression that method would have returned first -- verified
    against it in the test suite, which is also what guards this use of
    a private attribute against a music21 upgrade.
    """
    segments = realization._segmentList  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    current = next(iter(segments[0].movements))
    progression = [current]
    for segment in segments[:-1]:
        current = segment.movements[current][0]
        progression.append(current)
    return progression


def plan_progression_voicing(
    figures: list[str],
    key_name: str,
    num_parts: int = 4,
    bass_octave: int = DEFAULT_BASS_OCTAVE,
    max_pitch_name: str = DEFAULT_MAX_PITCH,
    relax: list[str] | None = None,
) -> dict[str, Any]:
    """Voice a progression into independent parts.

    Args:
        figures: Roman numerals read in *key_name* (``"V7/V"``, ``"ii65"``)
            or absolute chord symbols (``"Dm7"``), mixed freely.
        key_name: The key the roman numerals are read in.
        num_parts: Parts to write, bass included (3 or 4).
        bass_octave: Where the bass part sits.
        max_pitch_name: Ceiling for the top part.
        relax: Rule names from :data:`RELAXABLE_RULES` to switch off.

    Returns:
        ``{"solution_count", "chords": [{"figure", "pitches"}]}`` with
        pitches in part order, bass first. When nothing satisfies the
        rules, ``solution_count`` is 0, ``chords`` is empty, and
        ``relaxations_that_help`` names the rules that would unblock it.

    Raises:
        ValueError: on an unparseable figure, key, or rule name.
    """
    k = _parse_key(key_name)
    if k is None:
        raise ValueError(f"unparseable key: {key_name!r}")
    unknown = sorted(set(relax or ()) - RELAXABLE_RULES)
    if unknown:
        raise ValueError(
            f"unknown rule(s): {', '.join(unknown)}. "
            f"Relaxable rules are: {', '.join(sorted(RELAXABLE_RULES))}"
        )

    realization = _realize_progression(
        figures, k, num_parts, bass_octave, max_pitch_name, relax or []
    )
    count = realization.getNumSolutions()
    if not count:
        return {
            "solution_count": 0,
            "chords": [],
            "relaxations_that_help": _relaxations_that_help(
                figures, k, num_parts, bass_octave, max_pitch_name, relax or []
            ),
        }

    progression = _first_progression(realization)
    chords: list[dict[str, Any]] = []
    for figure, possibility in zip(figures, progression, strict=False):
        # music21 orders a possibility from the top part down; the rest
        # of this codebase reads chords upward from the bass.
        chords.append(
            {
                "figure": figure,
                "pitches": [pitch_to_spelled(p) for p in reversed(possibility)],
            }
        )
    return {"solution_count": count, "chords": chords}


def _realize_progression(
    figures: list[str],
    k: key.Key,
    num_parts: int,
    bass_octave: int,
    max_pitch_name: str,
    relax: list[str],
) -> realizer.Realization:
    """Run the solver once with the given relaxations."""
    line = _progression_line(figures, k, bass_octave)
    fb_rules = rules.Rules()
    for name in relax:
        setattr(fb_rules, name, False)
    return line.realize(
        fb_rules, numParts=num_parts, maxPitch=pitch.Pitch(max_pitch_name)
    )


def _relaxations_that_help(
    figures: list[str],
    k: key.Key,
    num_parts: int,
    bass_octave: int,
    max_pitch_name: str,
    already_relaxed: list[str],
) -> list[str]:
    """Which single rule, switched off, would yield a solution."""
    if len(figures) > PROGRESSION_PROBE_LIMIT:
        return []
    helpful: list[str] = []
    for name in sorted(RELAXABLE_RULES - set(already_relaxed)):
        try:
            probe = _realize_progression(
                figures,
                k,
                num_parts,
                bass_octave,
                max_pitch_name,
                [*already_relaxed, name],
            )
        except Exception:
            continue
        if probe.getNumSolutions():
            helpful.append(name)
    return helpful


# ── Ornaments: writing out what a symbol stands for ──────────────────
#
# The plugin cannot attach an ornament symbol to a note, but it can write
# the notes the symbol means. music21 knows the shapes, and knows them
# key-aware: the auxiliary note of a mordent follows the key signature.

#: Ornaments that can be written out, by the name a caller passes.
ORNAMENTS: dict[str, type[expressions.Ornament]] = {
    "trill": expressions.Trill,
    "mordent": expressions.Mordent,
    "inverted_mordent": expressions.InvertedMordent,
    "turn": expressions.Turn,
    "inverted_turn": expressions.InvertedTurn,
}


def realize_ornament_notes(
    ornament: str,
    note_name: str,
    numerator: int,
    denominator: int,
    key_name: str,
) -> list[dict[str, Any]]:
    """Write out an ornament as the notes it stands for.

    Args:
        ornament: One of :data:`ORNAMENTS`.
        note_name: The ornamented note, octave required (``"C5"``).
        numerator: Duration numerator, as a fraction of a whole note.
        denominator: Duration denominator (4 = a quarter note).
        key_name: The key, which decides the auxiliary notes.

    Returns:
        Spelled pitches with durations that sum to exactly the source
        note's duration.

    Raises:
        ValueError: on an unknown ornament, an unparseable note or key, a
            tuplet duration, or a note music21 cannot ornament.
    """
    if ornament not in ORNAMENTS:
        raise ValueError(
            f"unknown ornament: {ornament!r}. "
            f"Choose from: {', '.join(sorted(ORNAMENTS))}"
        )
    if numerator < 1 or denominator < 1:
        raise ValueError("duration values must be >= 1.")
    if denominator & (denominator - 1):
        raise ValueError(
            f"denominator {denominator} is a tuplet unit; the plugin can "
            "only write durations whose denominator is a power of two."
        )
    k = _parse_key(key_name)
    if k is None:
        raise ValueError(f"unparseable key: {key_name!r}")
    spelled = name_to_pitch_tpc(note_name)

    source_duration = Fraction(numerator, denominator)
    source = note.Note(spelled["name"])
    source.duration.quarterLength = float(source_duration * 4)
    try:
        before, main, after = ORNAMENTS[ornament]().realize(source, keySig=k)
    except Exception as exception:
        raise ValueError(f"could not write out a {ornament} here: {exception}") from (
            exception
        )

    realized = [
        element
        for element in (*before, *([main] if main is not None else []), *after)
        if isinstance(element, note.Note)
    ]
    if not realized:
        raise ValueError(f"a {ornament} on this note writes out to nothing.")

    written: list[dict[str, Any]] = []
    total = Fraction(0)
    for element in realized:
        duration = _wire_duration(float(element.duration.quarterLength))
        if duration is None:
            raise ValueError(
                f"a {ornament} here needs tuplet durations, which the plugin "
                "cannot write."
            )
        part_numerator, part_denominator = duration
        total += Fraction(part_numerator, part_denominator)
        written.append(
            {
                **pitch_to_spelled(element.pitch),
                "numerator": part_numerator,
                "denominator": part_denominator,
            }
        )
    if total != source_duration:
        # Emitting a run that does not fill the note would shift every
        # later beat in the bar.
        raise ValueError(
            f"a {ornament} here writes out to {total} of a whole note, not "
            f"the {source_duration} it replaces; refusing to shift the bar."
        )
    return written


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

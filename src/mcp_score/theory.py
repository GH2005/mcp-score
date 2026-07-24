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

from typing import TypedDict

from music21 import harmony, interval, key, pitch, roman

__all__ = [
    "MIN_TPC",
    "MAX_TPC",
    "SpelledPitch",
    "name_to_pitch_tpc",
    "pitch_to_spelled",
    "pitch_tpc_to_name",
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

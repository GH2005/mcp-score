# Authoring MusicXML — the write path the bridge cannot reach

> Reference. Every claim here was measured against MuseScore Studio 4.7.4
> on Windows 11 (2026-08-24) by generating a file, importing it, and
> diffing what came back. Re-derive with
> `mcp-score-audit/scripts/notation_probe.py` and `paste_probe.py` when
> MuseScore updates — these facts are pinned to a MuseScore version, not
> to the mcp-score server.

The live bridge writes pitches and rhythm and almost nothing else: it has
no API for ties or slurs, and `setBarline` / `addChordSymbol` /
`addDynamic` crash MuseScore outright. Writing MusicXML yourself lifts
that ceiling from roughly a quarter of notation to nearly all of it. The
cost is that a human must open or paste the result, so the choice between
the two write paths is a real judgement — see the routing table in
[`SKILL.md`](SKILL.md).

## The two file workflows

**Fragment → the user pastes.** For new or rewritten passages inside a
document the user is already working in. Their layout, title and other
edits survive; only the bars they select are replaced.

**Whole file → the user opens it as the new working doc.** For structural
work — re-voicing, hand separation, respelling, anything touching most of
the score. Carries every construct, including everything a paste drops.

Either way the user does the final step. Say which one you are handing
over and why, and give the exact bar number to click.

## Build with `scripts/mxbuild.py`, not with music21

music21 is the brain of this workflow and a bad mouth for it. Its writer
fails on exactly the material that makes this job worth doing:

- `makeRests` cannot express durations off the binary/tuplet grid — a
  1/18-of-a-quarter gap from a pedalled MIDI import raises
  `MusicXMLExportException`.
- `makeNotation` refuses complex durations and rewrites your rhythm when
  it does not refuse.
- Offsets in music21 are **per site**. `stream.remove(el)` then reading
  `el.offset` silently returns 0, collapsing every note in the measure
  onto beat 1. This bug is invisible until you diff the output; capture
  offsets _before_ removing anything.
- It cannot express pedal lines, voltas, noteheads, arbitrary tuplet
  brackets, or cross-staff assignment at all.

`scripts/mxbuild.py` writes raw MusicXML with `ElementTree`: `new_score`,
`measure`, `attributes`, `note`, `backup`, `direction`, `harmony`,
`barline`, `label`, `write`, `check_lengths`, plus direction builders
(`words`, `dynamic`, `wedge`, `pedal`, `octave_shift`, `metronome`,
`rehearsal`, `dashes`, `segno`, `coda`). It keeps `<note>` children in
schema order for you. Use `DIV = 840` divisions per quarter — divisible by
3, 5, 7 and 8, so triplets, quintuplets and septuplets all land on
integers.

**Keep using music21 for everything except serialization**: spelling
decisions, harmony, transposition, analysis, and as the independent reader
that verifies your own output. See "Verify" below.

## Gotchas that cost real debugging time

- **Child order is schema-fixed** and MuseScore is not forgiving:

  ```text
  <note>       grace, chord, pitch|rest, duration, tie, voice, type, dot,
               accidental, time-modification, stem, notehead, staff, beam,
               notations
  <notations>  tied, slur, tuplet, glissando, slide, ornaments, technical,
               articulations, dynamics, fermata, arpeggiate, non-arpeggiate
  ```

- **Grace notes carry no `<duration>`** — and an empty attribute dict is
  falsy, so test `if grace is not None`, never `if grace`. That one bug
  silently added a beat to a bar.
- **Every voice must fill its measure exactly.** MuseScore refuses the
  whole file with `Incomplete measure: measure N, staff S` and exit 40.
- **A trailing `<forward>` does not count as filling a voice** — MuseScore
  reports the measure incomplete.
- **An exact-duration rest with no `<type>` also fails.** MuseScore builds
  duration from `type` + dots + `time-modification` and treats `duration`
  as a cross-check, so a rest it cannot name is a rest it cannot place.
  Every rest you emit must be a nameable value.
- **Tuplets need complete brackets, per voice.** When a tuplet group is
  split between hands or voices, its original `<tuplet>` markers become
  orphans and MuseScore mis-sizes the bar. Strip the inherited markers,
  then re-bracket from the emitted stream: group consecutive elements
  sharing a `time-modification` and close a group as soon as it fills a
  plain rhythmic slot (a whole/half/quarter/eighth value, dotted allowed).
  That is how MuseScore writes them itself.
- **Fill gaps with tuplet-aware rests.** Inside a tuplet span, a rest must
  carry the same `time-modification` as its neighbours. Decompose in
  _written_ space: scale the gap by `actual/normal`, split it into plain
  values, then scale each part back.
- **Cap any recursive gap-filling fallback.** An uncapped
  split-the-gap-in-half retry emitted two thousand `<forward>` elements of
  one division each before anything complained.
- **`octave-shift type="down"` is 8va; `type="up"` is 8vb.** Measured, not
  inferred.
- **Do not strip `<time-modification>` when you strip `<tuplet>`** — the
  ratio is what determines the duration; the bracket is only how it draws.

## Verify before a human ever sees the file

Never hand over an unverified file. `scripts/verify_fragment.py` runs the
whole ladder:

```bash
python .claude/skills/musescore-bridge/scripts/verify_fragment.py OUT.musicxml
```

1. **Structure** — schema order, per-measure fill, no negative positions.
2. **Import** — MuseScore's own converter. `exit 0` means it loads clean;
   any other code means read the newest log in
   `%LOCALAPPDATA%\MuseScore\MuseScore4\logs`, which names the failing
   bar and staff exactly (`Incomplete measure: … measure 4, staff 2`).
   This oracle caught four separate bug classes in one session.
3. **Round-trip** — convert back out and diff feature counts, so you learn
   what the importer _downgraded_ rather than rejected.

For pitch/rhythm/harmony correctness, add a music21 parse of your output
and diff against intent (bar, offset, midi, spelled name). Use music21 for
music, raw XML for symbols — music21's object model does not represent
pedal lines, noteheads or several ornaments, so it is the wrong auditor
for those.

## What survives the import (MuseScore 4.7.4)

Of ~46 constructs in `notation_probe.py`, all but four arrive intact:
ties, slurs, tuplets (3:2, 5:4, 7:4), glissando, trill + wavy line, turn,
mordent, inverted mordent, tremolo, staccato, accent, tenuto, marcato,
staccatissimo, breath mark, caesura, fingering, fermata, grace notes and
grace chords, arpeggio and non-arpeggiate, noteheads, double sharp/flat,
cautionary accidentals in parentheses, dynamics, hairpins, pedal
down/change/up, 8va/8vb, metronome marks, staff text, dashed lines,
rehearsal marks, chord symbols, voltas, repeat barlines, barline styles,
clef/key/meter changes, four voices, cross-staff notes.

The four that are downgraded, not lost:

| Written         | Arrives as                                                |
| --------------- | --------------------------------------------------------- |
| delayed turn    | plain turn                                                |
| detached legato | staccato + tenuto (which _is_ portato)                    |
| segno           | correct glyph as text (SMuFL U+E047), not a playback jump |
| coda            | correct glyph as text (SMuFL U+E048), not a playback jump |

Separately, and not a downgrade but a mistake to avoid: **a pedal line
with no matching `stop` is dropped entirely.** Always close a pedal.

## What survives a paste between documents

Different question, different answer. **Anything attached to a note or a
staff survives; anything belonging to the measure or the system does not.**

| Survives the paste                     | Lost in the paste                           |
| -------------------------------------- | ------------------------------------------- |
| all notes, rhythms, spelling, voices   | **key signature changes**                   |
| ties, slurs, articulations, fingerings | **time signature changes**                  |
| fermatas, grace notes, noteheads       | **repeat barlines, voltas, barline styles** |
| ornaments, tremolo, arpeggios          | **rehearsal marks**                         |
| dynamics, hairpins, pedal, 8va         | **tempo / metronome marks**                 |
| staff text, chord symbols              | **dashed extension lines**                  |
| **clef changes** (yes — measured)      |                                             |

### Rules that follow

- **Match the target's key, meter and divisions.** Read the target first.
  A fragment in a different key still lands on the right pitches, but with
  the signature gone MuseScore respells everything against the old one —
  one test bar in A major arrived carrying 34 explicit accidentals.
- **Put any meter change in the last bar of the fragment**, so if it is
  dropped the re-barring spills into empty space instead of corrupting the
  middle.
- **Spanners cannot cross the boundary.** A slur or tie that starts before
  the fragment cannot be expressed in it; write one bar of overlap or
  accept the seam.
- **Restore what you can, then hand back a checklist for the rest.** Two
  of the dropped items are writable live once the paste has landed:
  `set_live_time_signature` and `add_live_rehearsal_mark`. For everything
  else tell the user exactly what to add and where — "bar 24: key
  signature to 3 sharps",
  "bar 25: repeat barline and first-ending bracket". Six clicks beats a
  silent omission.
- **Tell them to append measures first.** Paste replaces by duration; it
  does not insert. Appending a couple more bars than the fragment needs
  costs nothing and absorbs any re-barring.

### The paste instructions to give

1. Append N empty measures at the end (Add → Measures → Append Measures),
   or select the first bar to be replaced.
2. Open the fragment file, `Ctrl+A`, `Ctrl+C`.
3. In the working doc, click the target bar **on the top staff**,
   `Ctrl+V`.
4. Afterwards: re-read the live score and audit what landed —
   `verify_fragment.py FRAGMENT.musicxml --against LIVE_EXPORT.musicxml
--from-measure N`.

## Worked example

The hand-separation job (104 bars, 913 notes, 508 ties, 129 tuplet notes)
is the reference case for the whole-file path: export the live score,
analyse with music21, rebuild the MusicXML by **reusing every original
`<note>` element verbatim** and changing only `<staff>`, `<voice>`,
`<chord/>`, beams and stems. Nothing about the user's rhythm was
re-interpreted, and a MuseScore round-trip confirmed all 913 pitches at
the right bar, beat, staff and spelling.

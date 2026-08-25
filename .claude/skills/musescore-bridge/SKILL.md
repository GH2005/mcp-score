---
name: musescore-bridge
description: >
  How to read from and write to a score the user has open in MuseScore, by
  every route available: the mcp-score MCP server's live tools, the
  mcp-score-bridge plugin's WebSocket wire protocol, and hand-authored
  MusicXML the user opens or pastes -- plus the musical intelligence the
  server provides (spelled note entry, harmonic realization, four-part
  voicing, diatonic transposition, melodic transformation, ornament
  write-out, passage analysis).
  USE WHENEVER the user is composing, editing, notating, or asking about
  music in a score they already have open in MuseScore -- even when they
  name no tool, no file and no application. Musical intent alone is the
  trigger: "add a bassline under bars 9-16", "harmonize this",
  "reharmonize bar 12", "put a ii-V here", "fill out the left hand",
  "add an inner voice", "continue the phrase", "make bar 5 a Bb7",
  "voice this chord", "voice this progression", "harmonize it in four
  parts", "write it for SATB", "give each part its own line", "what
  inversion is that chord", "move that up a third", "up a step but stay in
  the key", "move it up a third in E-flat", "transpose it diatonically",
  "invert this motif", "mirror this line around G", "turn the theme upside
  down", "play it backwards", "reverse this phrase", "sequence this motif
  up a step", "repeat it rising", "write out the trill", "spell out that
  turn", "what key is this", "what chord is bar 8", "does this voice-lead
  cleanly", "check this passage", "how does bar 20 look", "is that spelled
  right", "put this in bass clef", "switch to treble here", "the left hand
  should read treble from bar 9", "this part is all ledger lines", "why
  does this staff look wrong", "there are clef changes in the middle of
  the bar", "get rid of these clef changes", "my MIDI import put clefs
  everywhere", "what clef is this staff in".
  Also trigger on NOTATION intent, which the live bridge cannot write and
  which needs the MusicXML route: "add slurs", "slur these notes", "tie
  that over the barline", "put a crescendo here", "add dynamics", "mark it
  forte", "add staccato", "articulate this", "put a trill on that note",
  "add a turn", "grace notes", "add pedal marks", "put an 8va on this",
  "add a repeat", "first and second endings", "add a rehearsal mark",
  "change the time signature here", "put a key change in", "add a tempo
  marking", "write this out properly", "notate it with", "clean up this
  MIDI import", "split this into two hands", "which hand plays what",
  "put the right hand on the top stave", "respell these accidentals",
  "fix the enharmonic spelling".
  Use BEFORE calling any of: connect_to_musescore, disconnect_from_musescore,
  connect_to_dorico, disconnect_from_dorico, connect_to_sibelius,
  disconnect_from_sibelius, ping_score_app, get_live_score_info,
  read_passage, get_measure_content, get_selection_properties,
  export_live_score, analyze_passage, realize_harmony, voice_progression,
  realize_ornament, transform_passage,
  add_live_rehearsal_mark, add_live_notes, get_live_clefs, set_live_clef,
  remove_live_clefs,
  set_live_time_signature, append_live_measures, process_live_sequence,
  transpose_passage, add_live_chord_symbol, set_live_barline,
  set_live_key_signature, set_live_tempo, or undo_last_action -- or before
  sending any raw JSON command to the plugin's WebSocket bridge
  (ws://localhost:8765, e.g. ping, getScore, goToMeasure, goToStaff,
  addNote, addRest, setPitches, addRehearsalMark, setTimeSignature,
  getClefs, setClef, removeClef,
  appendMeasures, undo, processSequence, exportScore, apiProbe) -- or
  before writing a MusicXML file for the user to open or paste into a
  score -- or before editing
  src/mcp_score/musescore/mcp-score-bridge.qml. Also trigger on phrases like "connect
  to MuseScore", "read/write the live score", "what's in the open score",
  "add notes to the score", "write a chord", "add a second voice",
  "transpose the passage", "check my voice leading", "what chord is this",
  "undo in MuseScore", "MuseScore plugin", "mcp-score-bridge",
  "live score manipulation".
  Several of these commands crash or silently corrupt MuseScore Studio
  4.7.4 if called the wrong way -- read this before guessing at
  parameters.
metadata:
  version: "2.0"
---

# MuseScore — reading and writing the open score

Two references and a script directory sit next to this file. Read the
relevant one before acting; do not guess at parameters, defaults, or which
commands are safe.

- [`agent-playbook.md`](agent-playbook.md) — the live path: every MCP tool
  and wire command, the composing loop, the restart matrix, how to re-run
  `pytest -m live tests/live`.
- [`authoring-musicxml.md`](authoring-musicxml.md) — the file path:
  authoring raw MusicXML, the verification ladder, and what survives an
  import versus a paste.
- [`scripts/`](scripts) — `mxbuild.py` (MusicXML builder) and
  `verify_fragment.py` (structure + import + round-trip audit).

Connect first (`connect_to_musescore`) if you are not already connected.
`realize_harmony`, `voice_progression` and `realize_ornament` are pure
theory and answer without a score; every other tool needs a live
connection.

## Route first — which path for this job

**Reading.** Three routes, and picking the wrong one makes you confidently
wrong about the user's music.

| To find out                                                                                                                                                                                 | Use                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| pitches, rhythm, ties, voices, chord symbols, dynamics, tempo, key, meter, barline types, rehearsal marks                                                                                   | `read_passage` — the digest, MusicXML-backed and enough for most questions          |
| slurs, articulations, ornaments, fingering, arpeggios, pedal, hairpins, octave shifts, grace notes, noteheads, tremolo, voltas, cross-staff, **any staff text**, exact ticks, tuplet ratios | `export_live_score` + parse the file yourself — the digest is blind to all of these |
| what clef actually governs a staff, mid-measure clef changes                                                                                                                                | `get_live_clefs`                                                                    |

**The digest's tempo `text` is fabricated.** music21 invents a label from
the number (88 → "maestoso") — a score marked _Andante_ will report
"maestoso". Never quote it back to the user; export if the words matter.

**Writing.** Match the route to what the edit contains, not to how big it
feels.

| The edit is                                                                                                                  | Route                                                                                                                                          |
| ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| a few pitches, a rest, a clef, appended bars, a rehearsal mark, a time signature, a diatonic transposition                   | live bridge tools — fastest, no human step                                                                                                     |
| anything carrying ties, slurs, dynamics, hairpins, articulations, ornaments, grace notes, pedal, 8va, tuplets, chord symbols | write a MusicXML **fragment**; the user pastes it                                                                                              |
| restructuring most of the score — re-voicing, hand separation, respelling, meter overhaul                                    | write the **whole file**; the user opens it as the new working doc                                                                             |
| a key signature, a tempo mark, repeat barlines, voltas, a barline style, a dashed line                                       | **a paste drops every one of these** (F3), and the bridge crashes or corrupts on most (rule 3). Whole-file route, or hand the user a checklist |

The live bridge cannot write a tie or a slur at all: it has no API for
them. That is not a limitation to work around with clever note entry — it
is the signal to switch routes.

**The routes combine.** After a paste, two of the dropped items you can
restore yourself: `add_live_rehearsal_mark` and `set_live_time_signature`
both work live. The rest — key signature, tempo mark, repeats, voltas,
barline styles, dashed lines — are the user's hand or the whole-file
route, because the bridge crashes or corrupts on them.

## Reach for the intelligence — default habits, not special requests

The server carries real musical machinery. Use it as a matter of course:
the user will describe music, not name tools, and should never have to ask
you to read the score first or to spell a note properly.

| Before you…                                               | Do this                                                                                                                                                                                                                                                       |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| write anything                                            | Read the bars you are about to touch, by the route the reading table names. Reading is your only window on the score, and writing blind overwrites the user's work.                                                                                           |
| write one chord you have named                            | `realize_harmony("V7/V", "E-")` — do not work the pitches out in your head. It handles inversion figures (`ii65`), spells augmented sixths correctly, and reports the inversion and root back.                                                                |
| write a progression as independent parts                  | `voice_progression(["I","IV","V7","I"], "C")`. Do not hand-place four parts yourself, and do not stack `realize_harmony` output per chord — that gives chords, not voice leading.                                                                             |
| write any note at all                                     | pass `{"name": "E-4"}`. A bare MIDI number discards the spelling and lets MuseScore guess (rule 2).                                                                                                                                                           |
| write a second line on one staff                          | `add_live_notes(..., voice=1)`. Stacking it into voice 0 makes a chord, not counterpoint.                                                                                                                                                                     |
| write notation the bridge has no API for                  | Do not fake it. Build a MusicXML fragment with `scripts/mxbuild.py`, verify it, hand it over to paste — see [`authoring-musicxml.md`](authoring-musicxml.md).                                                                                                 |
| restructure a whole score (hands, voicing, spelling)      | Export, rebuild the file **reusing the original `<note>` elements**, hand back a whole document. Do not re-enter 900 notes through the bridge.                                                                                                                |
| move a passage by an interval _within its key_            | `transpose_passage(..., degrees=2, key="E-")` — "up a third" is `degrees=2`, "up a step" is `degrees=1`. Use `semitones` only for a real change of key.                                                                                                       |
| invert, reverse, or sequence a motif                      | `transform_passage("invert"/"retrograde"/"sequence", ...)` after reading the range. Do not read the notes and re-enter them by hand.                                                                                                                          |
| write out a trill, turn, or mordent                       | `realize_ornament("trill", "C5", "E-")` writes the notes it stands for. For the ornament _symbol_, use the file route — the bridge cannot attach one.                                                                                                         |
| explain why a staff reads oddly, or before touching clefs | `get_live_clefs(staff)`. Entries with `atMeasureStart: false` are mid-measure clef changes — MuseScore's MIDI import inserts them to chase notes out of range, and they are invisible in `get_live_score_info` alone. Do not infer the clef from the pitches. |
| move a part that has drifted into ledger lines            | `set_live_clef(measure, "treble", staff=1)` — change the clef rather than transposing the music. Transposing changes what is played; a clef change only changes how it is written.                                                                            |
| clear an unwanted clef change                             | You cannot delete it. `set_live_clef` at that same measure **overwrites** it with the clef that should govern there; otherwise tell the user to delete it by hand. Do not call `remove_live_clefs` expecting it to work — it refuses.                         |
| tell the user an edit landed                              | `read_passage` again. The command's reply is not evidence (rule 5).                                                                                                                                                                                           |
| answer a musical question about the score                 | `analyze_passage(start, end, key=<the key they intend>)`. Always pass the key — detection on a short excerpt is unreliable and will report the wrong one.                                                                                                     |

**What these do not decide.** Judgement stays yours.

- `realize_harmony` gives pitch content, never a voicing.
- `voice_progression` returns the _first voicing that breaks no rule_ —
  a floor on competence, not taste. Spacing, doubling, register and which
  line carries the tune are still yours to review. When it finds nothing
  it says so and names the rule to `relax`; that is a prompt to think,
  not to relax the rule reflexively.
- `degrees` keeps the music in one key and pulls chromatic notes onto the
  nearest scale tone — every one it moved comes back in `snapped`. If the
  user wanted those accidentals kept, they wanted `semitones`.
- `transform_passage` with `retrograde` or `sequence` **rewrites** the
  bars note by note in one voice, replacing what was there, and refuses
  outright on ties, tuplets, grace notes, a meter change or a part-filled
  voice. `sequence` needs the destination bars to exist already — it
  names how many to `append_live_measures` rather than appending them
  itself. `invert` only re-pitches, so it never disturbs the rhythm.
- `realize_ornament` fills exactly the duration of the note it replaces,
  so it never shifts the bar — but the plain note it replaces is gone.
- `set_live_clef` changes only how the music is **written**, never what
  it sounds like. If a part is in the wrong octave, a clef is the wrong
  fix. A written clef also cannot be deleted afterwards — only overwritten
  with another — so decide the clef rather than experimenting with one.
- `get_live_clefs` hides the courtesy clefs MuseScore restates at every
  system start, because they are laid out rather than authored. What it
  reports are the clefs that actually govern the reading; pass
  `includeRedundant: true` only when debugging the layout itself.
- **music21 is the brain, not the mouth.** Use it to decide spelling,
  harmony and transposition, and to verify your own output — never as the
  MusicXML writer. Its serializer fails on the exact material that needs
  this workflow (see [`authoring-musicxml.md`](authoring-musicxml.md)).

Reach for `analyze_passage` when harmony or voice leading is genuinely in
question, not reflexively after every edit, and read rule 6 before
repeating anything it says.

The [playbook](agent-playbook.md) carries the reasoning and the full
composing loop; this table is the short form.

## The seven rules that keep MuseScore alive

The load-bearing safety rules — the ones that crash, corrupt, or silently
mislead. They live here so they are in context even before you open the
playbook; the playbook carries the full detail and the reasoning.

1. **Never use `format: "mscz"`** in `export_live_score` / `exportScore`.
   It writes a 0-byte file, never replies, and blocks MuseScore with a
   modal dialog the user must dismiss by hand. Use `"musicxml"`.
2. **Write notes by name, not by MIDI number.** `add_live_notes` takes
   `{"name": "E-4"}` and `{"chord": [...]}`; a bare `pitch` makes
   MuseScore guess the spelling from the key signature, and an ascending
   C-sharp and a descending D-flat are the same MIDI number but different
   music. On the wire, `addNote` needs an explicit `tpc`. Never set a
   pitch without its spelling — MuseScore exports the spelling, so the
   two disagreeing means the edit silently does not land.
3. **`set_live_barline` and `add_live_chord_symbol` crash MuseScore
   outright; `set_live_key_signature` and `set_live_tempo` silently
   corrupt the score.** All four MCP tools refuse and explain why. The
   wire-level `__experimental: true` flag bypasses the guard but WILL
   crash or corrupt MuseScore — use it only against a disposable,
   already-saved test score with the user's explicit go-ahead.
4. **`undo_last_action` / wire `undo` reports success but does nothing**
   in MuseScore Studio 4.7.4. Never rely on it — make an explicit
   corrective edit and confirm it with a read.
5. **Never trust a mutating command's reply as proof the edit landed.**
   Confirm with an export-backed read (`read_passage` /
   `get_measure_content` / `export_live_score`) after every mutating call.
6. **`analyze_passage` advises; it does not rule.** Its voice-leading
   observations are context-free — parallel fifths are an error in a
   chorale, the point in organum, and ordinary in power chords. Weigh
   them against the style being written; never "fix" the user's music on
   the strength of a report, and never let it override their intent.
7. **Never read notes off a picture, and never count positions by eye.**
   On a blind test, reading pitches from a rendered score scored 40%
   while parsing the same file scored 100% — and every error was
   displaced upward by a step or two, so the result looked like music
   and was wrong throughout. A render shows layout and density, nothing
   more. The same trap applies to your own arithmetic: quote the named
   value from a read (`"names": ["E-4"]`) rather than counting to "the
   fourth event" down a listing. If a user offers a photograph of a
   score, ask for the file instead.

## Four more rules for the file path

Numbered separately so the seven above keep their references.

- **F1. Never hand over an unverified file.** Run
  `scripts/verify_fragment.py`: structure, then MuseScore's own converter
  (exit 0), then a round-trip diff. The converter names the failing bar
  and staff in `%LOCALAPPDATA%\MuseScore\MuseScore4\logs`.
- **F2. Match the target's key, meter and divisions in a fragment.** Read
  the target first. Key and meter changes do **not** survive a paste, so a
  mismatched fragment lands on the right pitches spelled against the wrong
  signature.
- **F3. Account for everything the paste drops** — key signatures, time
  signatures, repeats and voltas, barline styles, rehearsal marks, tempo
  marks, dashed lines. Restore the two you can (`set_live_time_signature`,
  `add_live_rehearsal_mark`) and hand back a checklist for the rest,
  naming the bar and the change for each. A few clicks beats a silent
  omission.
- **F4. Reuse the user's own `<note>` elements when rewriting a score.**
  Copy them verbatim and change only `<staff>`, `<voice>`, `<chord/>`,
  beams and stems. Re-deriving durations re-interprets rhythm the user
  played, and MIDI-derived material is full of values no notation library
  will reproduce.

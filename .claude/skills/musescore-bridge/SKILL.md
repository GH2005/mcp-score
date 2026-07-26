---
name: musescore-bridge
description: >
  Correct usage patterns for the mcp-score MCP server's live MuseScore tools
  and the mcp-score-bridge MuseScore plugin's WebSocket wire protocol, plus
  the read/write musical intelligence the server provides (spelled note
  entry, harmonic realization, four-part voicing, diatonic transposition,
  melodic transformation, ornament write-out, passage analysis).
  USE WHENEVER the user is composing, editing, or asking about music in a
  score they already have open in MuseScore -- even when they name no tool,
  no file and no application. Musical intent alone is the trigger: "add a
  bassline under bars 9-16", "harmonize this", "reharmonize bar 12",
  "put a ii-V here", "fill out the left hand", "add an inner voice",
  "continue the phrase", "make bar 5 a Bb7", "voice this chord",
  "voice this progression", "harmonize it in four parts", "write it for
  SATB", "give each part its own line", "what inversion is that chord",
  "move that up a third", "up a step but stay in the key", "move it up a
  third in E-flat", "transpose it diatonically", "invert this motif",
  "mirror this line around G", "turn the theme upside down", "play it
  backwards", "reverse this phrase", "sequence this motif up a step",
  "repeat it rising", "write out the trill", "spell out that turn",
  "what key is this", "what chord is bar 8",
  "does this voice-lead cleanly", "check this passage", "how does bar 20
  look", "is that spelled right".
  Use BEFORE calling any of: connect_to_musescore, disconnect_from_musescore,
  connect_to_dorico, disconnect_from_dorico, connect_to_sibelius,
  disconnect_from_sibelius, ping_score_app, get_live_score_info,
  read_passage, get_measure_content, get_selection_properties,
  export_live_score, analyze_passage, realize_harmony, voice_progression,
  realize_ornament, transform_passage,
  add_live_rehearsal_mark, add_live_notes,
  set_live_time_signature, append_live_measures, process_live_sequence,
  transpose_passage, add_live_chord_symbol, set_live_barline,
  set_live_key_signature, set_live_tempo, or undo_last_action -- or before
  sending any raw JSON command to the plugin's WebSocket bridge
  (ws://localhost:8765, e.g. ping, getScore, goToMeasure, goToStaff,
  addNote, addRest, setPitches, addRehearsalMark, setTimeSignature,
  appendMeasures, undo, processSequence, exportScore, apiProbe) -- or
  before editing
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
  version: "1.6"
---

# MuseScore bridge — correct usage

The full, verified reference is [`agent-playbook.md`](agent-playbook.md),
right next to this file — the single source of truth for the support
matrix (all 28 MCP tools and every wire command), the composing loop, the
restart matrix, and how to re-run the live suite
(`pytest -m live tests/live`) if MuseScore's behavior seems to have
changed. **Read it before any mutating or wire-level call, and before
anything beyond the two sections below** — do not guess at parameters,
defaults, or which commands are safe.

Connect first (`connect_to_musescore`) if you are not already connected.
`realize_harmony`, `voice_progression` and `realize_ornament` are pure
theory and answer without a score; every other tool below needs a live
connection.

## Reach for the intelligence — default habits, not special requests

The server carries real musical machinery. Use it as a matter of course:
the user will describe music, not name tools, and should never have to ask
you to read the score first or to spell a note properly.

| Before you…                                    | Do this                                                                                                                                                                                        |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| write anything                                 | `read_passage` the bars you are about to touch. You have no other way to see the score, and writing blind overwrites the user's work.                                                          |
| write one chord you have named                 | `realize_harmony("V7/V", "E-")` — do not work the pitches out in your head. It handles inversion figures (`ii65`), spells augmented sixths correctly, and reports the inversion and root back. |
| write a progression as independent parts       | `voice_progression(["I","IV","V7","I"], "C")`. Do not hand-place four parts yourself, and do not stack `realize_harmony` output per chord — that gives chords, not voice leading.              |
| write any note at all                          | pass `{"name": "E-4"}`. A bare MIDI number discards the spelling and lets MuseScore guess (rule 2).                                                                                            |
| write a second line on one staff               | `add_live_notes(..., voice=1)`. Stacking it into voice 0 makes a chord, not counterpoint.                                                                                                      |
| move a passage by an interval _within its key_ | `transpose_passage(..., degrees=2, key="E-")` — "up a third" is `degrees=2`, "up a step" is `degrees=1`. Use `semitones` only for a real change of key.                                        |
| invert, reverse, or sequence a motif           | `transform_passage("invert"/"retrograde"/"sequence", ...)` after reading the range. Do not read the notes and re-enter them by hand.                                                           |
| write out a trill, turn, or mordent            | `realize_ornament("trill", "C5", "E-")`, then write its `entries_for_add_live_notes`. The plugin cannot attach an ornament _symbol_; this writes the notes it stands for.                      |
| tell the user an edit landed                   | `read_passage` again. The command's reply is not evidence (rule 5).                                                                                                                            |
| answer a musical question about the score      | `analyze_passage(start, end, key=<the key they intend>)`. Always pass the key — detection on a short excerpt is unreliable and will report the wrong one.                                      |

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

Reach for `analyze_passage` when harmony or voice leading is genuinely in
question, not reflexively after every edit, and read rule 6 before
repeating anything it says.

The [playbook](agent-playbook.md) carries the reasoning and the full
composing loop; this table is the short form.

## The six rules that keep MuseScore alive

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

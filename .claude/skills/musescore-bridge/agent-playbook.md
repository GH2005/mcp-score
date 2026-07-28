# Agent playbook — verified mcp-score usage patterns

> Reference — every claim here was verified against a live MuseScore
> Studio 4.7.4 (Windows 11) by the committed live test suite
> (`tests/live/`). Verification date: 2026-07-27. Plugin version: 0.4.5
> (clef support: reading clefs and writing them work; removing them is
> impossible in this MuseScore build).
> When in doubt, re-run the suite; it is the source of truth.

## The stack

```
MCP tool  →  ScoreBridge (Python)  →  ws://localhost:8765  →  mcp-score-bridge.qml  →  curScore
                   ↑
              music21 (mcp_score.theory, mcp_score.musicxml)
```

**The plugin holds no music theory.** Every musical decision — which
enharmonic spelling a note gets, what a roman numeral resolves to, how a
passage transposes — is made server-side by music21 and sent to the
plugin as plain numbers. The wire carries a MIDI pitch and a MuseScore
_tonal pitch class_ (tpc); note names exist only in Python.

- The plugin (`mcp-score-bridge.qml`) must be running inside MuseScore:
  **Plugins → MCP Score Bridge** (a dock plugin; it must be relaunched
  after every MuseScore restart).
- Wire protocol: one JSON object per message,
  `{"command": <name>, "params": {...}}` → `{"result": ...}` or
  `{"error": "..."}`. There are no message ids; correlation is strict
  request→response lock-step, so keep one request in flight per client.
- Multiple clients may connect simultaneously (verified: replies are
  routed per client), but each client must still serialize its own
  requests.

## Ground-truth doctrine (the most important rule)

**Never trust a _mutating_ command's reply as proof the edit landed.**
MuseScore 4's plugin API fails silently in several places (see the
broken-command table below). The only reliable read is an exported
snapshot: export the live score to MusicXML, then parse or render that
file.

- `read_passage`, `get_measure_content`, and `export_live_score` already
  do this internally, so their output _is_ trustworthy — prefer them over
  any raw read.
- To verify an edit, snapshot before and after and diff the two; the
  delta must be exactly the intended change.
  (`mcp_score.musicxml.parse_snapshot` and `diff_snapshots` are the
  shared helpers behind both the tools and the live suite.)

**Trust a fact that is _named_, never one you had to locate.** In
MusicXML a pitch is stated outright (`<step>G</step><octave>4</octave>`),
and in MIDI it is a number; there is no reference frame to get wrong. On
an engraved page the same pitch is _positional_ — it has to be recovered
by indexing a notehead against a staff grid, and one slip in that grid
displaces every note after it. That single distinction is why the parse
path is ground truth and a rendered image is not (measured below), and it
applies to your own reading too: counting "the fourth event" by eye down
a long `read_passage` listing is the positional operation again, in
prose. Quote the named value instead. The code paths that must align by
position are guarded — `setPitches` re-checks every `oldPitch` against
what it finds and fails whole rather than half-applying — but nothing
guards arithmetic you do in your head.

### Reading the score when you must bypass the tools

Reach for this only when the tools above are not an option — the MCP
server is disconnected but the plugin dock is still serving, you are
debugging the bridge itself, or you want to see the engraving (layout,
spacing, density) rather than the notes. It is fully automated: never ask
the user to save the file or to report what they see in MuseScore.

1. **Snapshot over the wire.** Send
   `{"command": "exportScore", "params": {"path": "C:/abs/path/out.musicxml", "format": "musicxml"}}`
   to `ws://localhost:8765` (e.g. a small script via
   `uv run --with websockets python` — on Windows a bare `python` is
   usually the Microsoft Store stub that only prints an install prompt,
   verified on this machine). Expect
   `{"result": {"written": true, "path": ..., "format": "musicxml"}}`.
   Use `format: "musicxml"`; `mscz` is rejected (see the broken-command
   table). The snapshot captures unsaved edits and works on a never-saved
   "Untitled" score without touching the user's file.
2. **Read the snapshot.** Parse the MusicXML for note-exact data. A
   render answers a different, narrower question — how the music _sits on
   the page_ — and must never be used to establish what the notes are
   (see the accuracy measurement in the gotchas below):
   `MuseScore4.exe <snapshot>.musicxml -o <out>.png -r 130 --force`
   (exit code 0 on success). This works even while the MuseScore GUI is
   open (verified). It writes one PNG per page, suffixed `-1`, `-2`, …;
   at `-r 130` a page is roughly 1100×1400 px (verified here) — small
   enough to view directly, versus MuseScore's default DPI of ~10,000+ px
   wide (verified 10200×13200 for the same page), which would need
   downscaling first.
   - From PowerShell, launch with
     `Start-Process ... -Wait -WindowStyle Hidden -PassThru` and check
     `.ExitCode`: invoked directly the exe detaches and returns before
     the render finishes, so `-Wait` is required. (Not an issue for a
     plain Python `subprocess.run([...], check=True)`, which waits on its
     own — see `render_png` in `tests/live/mxl.py`.)
3. Write snapshots and renders to the session scratchpad, and confirm any
   claimed edit by diffing a fresh export — never by trusting a reply.

## Support matrix (MuseScore Studio 4.7.4)

### Works — verified live

| Surface                                                                                 | Notes                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `connect_to_musescore(host="localhost", port=8765)`, `disconnect_from_musescore`        | Connect first; every other tool needs an active connection. The bridge auto-connects and retries once on connection loss.                                                                                                                                                                                                                                                      |
| `ping_score_app` (wire `ping`), `get_live_score_info` (wire `getScore`)                 | `getScore` reply carries `pluginVersion` (stale-plugin detection), `measureCount`, key/time signature, parts with staff ranges (derived from tracks).                                                                                                                                                                                                                          |
| `export_live_score(path?, format="musicxml")`                                           | The ground-truth snapshot. Rejects `mscz` (see limitations), relative paths, unknown formats.                                                                                                                                                                                                                                                                                  |
| `read_passage(start, end, staff?)`                                                      | Accurate: export + parse. Reports every note, chord, rest, voice, and annotation per measure/staff.                                                                                                                                                                                                                                                                            |
| `get_measure_content(measure, staff=0)`                                                 | Accurate: export + parse.                                                                                                                                                                                                                                                                                                                                                      |
| `get_selection_properties`                                                              | Cursor info only (measure/staff/beat/tick + element under cursor).                                                                                                                                                                                                                                                                                                             |
| `add_live_notes(measure, staff, notes, voice=0)`                                        | The reliable note-entry path: compiles a run into one `processSequence` batch. Entries take `{"name": "E-4"}` (**preferred** — spelling is preserved exactly), `{"chord": ["C4","E-4","G4"]}`, `{"rest": true}`, or `{"pitch": 61, "key": "E-"}`; plus `numerator`/`denominator` (default 1/4). Content at those beats is replaced, and a run spills into following measures.  |
| `process_live_sequence(steps)`                                                          | Batch of wire actions in one command group. Rejects crash/corruption actions. **Rollback on failure does not work** (undo is broken): earlier steps stay applied.                                                                                                                                                                                                              |
| `add_live_rehearsal_mark(measure, text)` (wire `addRehearsalMark`)                      | Verified in export.                                                                                                                                                                                                                                                                                                                                                            |
| `set_live_time_signature(measure, num, den)`                                            | Verified in export; re-bars from that measure onward; may add a courtesy signature to the previous measure.                                                                                                                                                                                                                                                                    |
| `append_live_measures(count)` (wire `appendMeasures`)                                   | Verified in export.                                                                                                                                                                                                                                                                                                                                                            |
| `transpose_passage(start, end, staff, semitones?, voice?, degrees?, key?)`              | Snapshot → music21 computes each new pitch **and its spelling** → verified positional edits via `setPitches`. Pass exactly one of `semitones` (chromatic, changes key) or `degrees`+`key` (diatonic, stays in key: `degrees=2` is "up a third"). G+3 comes out B-flat, not A-sharp. Diatonic replies carry `snapped` — the chromatic notes pulled onto the scale.              |
| `realize_harmony(figure, key, octave=4)`                                                | Intent → notes. A roman numeral in a key (`"V7/V"`, `"bVII"`, `"Ger65"`) or a chord symbol (`"E-maj7"`) becomes spelled pitches; `chord_for_add_live_notes` feeds straight into `add_live_notes`. `metadata` adds root, bass, inversion, quality and the tonicized key of a secondary function. **Needs no connection** — pure theory.                                         |
| `voice_progression(figures, key, num_parts=4, bass_octave=3, durations?, relax?)`       | Intent → **parts**, not just pitches. music21's figured-bass solver searches voicings that satisfy the classical rules and returns the first that does, deterministically, with `solution_count`. `entries.chords` writes the texture on one staff; `entries.upper`/`entries.bass` split it across a grand staff. Max 16 figures, 3 or 4 parts. **Needs no connection.**       |
| `transform_passage(operation, start, end, staff, key?, axis?, voice?, copies, degrees)` | `invert` mirrors diatonically around `axis` via `setPitches` (rhythm untouched, all voices unless one is named). `retrograde` and `sequence` **rewrite** one voice note by note, replacing the bars; both refuse on ties, tuplets, grace notes, a meter change, or a voice that does not fill every bar. `sequence` refuses rather than appending, naming the measures needed. |
| `realize_ornament(ornament, note, key, numerator=1, denominator=4)`                     | The notes an ornament symbol stands for: `trill`, `mordent`, `inverted_mordent`, `turn`, `inverted_turn`. Key-aware (the note below C in E-flat is B-flat). Durations sum to exactly the source note, so writing them never shifts the bar. **Needs no connection.**                                                                                                           |
| `analyze_passage(start, end, staff?, key?)`                                             | Notes → intent, plus critique: detected key, roman-numeral reading per simultaneity, voice-leading observations (parallel/hidden 5ths & 8ves, voice crossing) located by measure, per-staff ambitus. **Advisory only — never edits, never blocks.**                                                                                                                            |
| Wire navigation: `goToMeasure` (1-indexed), `goToStaff` (0-indexed, `voice?` 0-3)       | Bounds-checked. Staff **and voice** persist across commands; always set both explicitly.                                                                                                                                                                                                                                                                                       |
| Wire `addNote`                                                                          | Consecutive calls accumulate (the plugin tracks the intra-measure tick). `addToChord: true` stacks onto the previous note instead of advancing; `tpc` sets the spelling. Pitch validated 0–127, tpc −1..33.                                                                                                                                                                    |
| Wire `addRest`                                                                          | `cursor.addRest` exists in 4.7.4 and works. Same duration parameter as `addNote`.                                                                                                                                                                                                                                                                                              |
| Wire `setPitches`                                                                       | Rewrites pitch + spelling over a staff/voice/measure range. Edits are **positional** (tick order, then ascending pitch within a chord) and every `oldPitch` is verified before anything is written, so a stale request aborts whole.                                                                                                                                           |
| Wire `getCursorInfo`                                                                    | Beat computed via `measure.timesigActual`. Reports raw `(pitch, tpc)`; render names with `mcp_score.theory.pitch_tpc_to_name`. Only the element under the cursor — use the export path for full content.                                                                                                                                                                       |
| Wire `apiProbe`                                                                         | Runtime introspection, incl. `capabilities.voicePositioning` (which cursor strategy this build accepts) and `capabilities.clef` (removal APIs, writable clef properties, observed clef subtypes).                                                                                                                                                                              |
| `get_live_clefs(staff?)` (wire `getClefs`)                                              | Every clef with `staff`, `measure`, `tick`, `tickInMeasure`, `atMeasureStart`, `generated`, `subtype`, `name`. **`atMeasureStart: false` is a mid-measure clef change** — what MIDI import leaves behind. Courtesy clefs restated at each system start are hidden (a 300-bar piano score carries 78 clef glyphs and 2 real clefs); pass `includeRedundant: true` to see them.  |
| `set_live_clef(measure, clef_type, staff=0)` (wire `setClef`)                           | `treble`, `treble8vb`, `treble8va`, `alto`, `tenor`, `bass`, `bass8vb`, `percussion` — all 8 verified against the exported MusicXML sign. Works at a measure start and mid-measure (write a note first to advance the tick). **Replaces** a clef already at that position rather than stacking. Sequenceable. `subtype` takes a raw ClefType integer for unnamed variants.     |
| Clefs in `getScore` / `getCursorInfo`                                                   | `getScore` carries `clefCount` and `midMeasureClefs` (the anomalies only, so they surface without a dedicated call). `getCursorInfo` carries `clef` — the clef **governing the cursor**, not merely the score's first.                                                                                                                                                         |
| Clefs in `get_measure_content` / `read_passage`                                         | Each measure's `clef` is a list of `{sign, offset}`. The offset separates a normal staff clef (`0.0`) from a mid-measure change, and clefs nested inside a voice are included.                                                                                                                                                                                                 |

### Broken in MuseScore 4.7.4 — guarded, do not attempt to bypass

| Surface                                                                                                                                       | Failure mode                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Guard                                                                                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `setBarline`, `addChordSymbol`, `addDynamic` (tools `set_live_barline`, `add_live_chord_symbol`; `addDynamic` is wire-only, no tool wraps it) | **Crash MuseScore outright** (process death; `newElement` + `cursor.add` is fatal for these element types).                                                                                                                                                                                                                                                                                                                                                   | Tools refuse; wire commands require `__experimental: true`; `process_live_sequence` rejects the actions.                                                                                                                                |
| `setKeySignature`, `setTempo` (tools `set_live_key_signature`, `set_live_tempo`)                                                              | **Silently insert corrupt elements**: every inserted key signature exports as `fifths=-8` regardless of the value written; tempo marks export with no text and no number. The clone made by `cursor.add` loses the assigned values; re-assigning after insertion does not help. (`setTimeSignature` and rehearsal marks use the same pattern and work — the MS4 API port is that inconsistent.)                                                               | Tools refuse; `process_live_sequence` rejects the actions.                                                                                                                                                                              |
| `undo` (tool `undo_last_action`) and `processSequence` rollback                                                                               | `cmd("undo")` is a **silent no-op** from the dock-plugin context: the reply says ok, the edit stays.                                                                                                                                                                                                                                                                                                                                                          | None (reply is honest-looking but useless). Never rely on undo; verify with exports and fix mistakes with explicit edits.                                                                                                               |
| `selectCurrentMeasure`, `selectCustomRange`                                                                                                   | Both wrap `selection.selectRange`, which does not produce an _active_ selection in MS4 (`elements` stays empty, with or without a command group), so anything that reads the selection afterward sees nothing.                                                                                                                                                                                                                                                | No tool wraps them. Nothing in the bridge depends on a selection any more.                                                                                                                                                              |
| `removeClef` (tool `remove_live_clefs`)                                                                                                       | **Clefs cannot be deleted from a plugin.** MuseScore 4.7.4 exposes no score-level element removal (`removeElement`, `deleteElement`, `remove`, `cmdRemove`, `removeSelection` are all `undefined`), and the selection route cannot substitute: `selection.select(clef)` returns `false`, so `cmd("delete")` has nothing to act on. All three variants (`select`+`delete`, `select(add=false)`+`delete`, `select`+`delete-selection`) leave the clef in place. | Tool refuses and names the workarounds; wire command requires `__experimental: true`; the sequence action carries the same guard. **Workaround: `setClef` overwrites a clef at the same position** — or delete it by hand in MuseScore. |
| `newScore`                                                                                                                                    | Creates the score in a window this bridge cannot control; `curScore` never switches to it.                                                                                                                                                                                                                                                                                                                                                                    | Not exposed as a tool.                                                                                                                                                                                                                  |
| `exportScore` with `format: "mscz"`                                                                                                           | writeScore writes a 0-byte file, never replies, and raises a **blocking modal dialog** the user must dismiss by hand.                                                                                                                                                                                                                                                                                                                                         | Rejected at both the tool and the plugin level.                                                                                                                                                                                         |

### Not available on this machine

`connect_to_dorico` / `disconnect_from_dorico` (port 4560) and
`connect_to_sibelius` / `disconnect_from_sibelius` (port 1898): neither
application is installed, so only their connection-failure paths are
verified. The MuseScore-only tools refuse when another app is connected
(`_require_musescore`).

## Composing on an open score

The loop for live work with a musician. Run it by default — the user
describes music, not tools, and should never have to ask you to read
before writing or to spell a note properly. (The skill's habits table is
this loop in short imperative form; this is the reasoning behind it.)

1. **Read what is there** — `read_passage`. It reports chords, voices and
   spelling accurately, so never guess at the current state.
2. **Decide the music yourself.** music21 supplies theory mechanics, not
   taste: it will not tell you what the piece needs. The tools turn a
   decision you have already made into notes, at three levels of
   commitment:
   - `realize_harmony` — one chord's pitch content. Voicing, spacing,
     doubling and register stay yours.
   - `voice_progression` — a progression as independent parts, rule-checked.
     It picks the first voicing that breaks no rule, which settles the
     mechanics and leaves the taste: review the spacing and doubling, and
     decide which line should carry the tune.
   - `transform_passage` / `transpose_passage(degrees=…)` — operate on
     music that already exists rather than inventing new material.
     Reach for these when the user's phrasing is transformational
     ("invert it", "backwards", "sequence it up", "up a third but stay in
     the key") instead of re-deriving the notes by hand.
3. **Write it spelled** — `add_live_notes` with `name`/`chord` entries.
   Prefer names over bare MIDI: a bare pitch makes MuseScore guess, and
   an ascending C-sharp and a descending D-flat are the same MIDI number
   but different music.
4. **Verify by export**, not by the reply (see the doctrine above). This
   matters most after `retrograde` and `sequence`, which replace whole
   bars rather than re-pitching what is there.
5. **Ask for a second opinion if useful** — `analyze_passage`. Treat its
   output as observations to weigh, not corrections to apply: parallel
   fifths are an error in a chorale, the point in organum, and ordinary
   in power chords. It never edits anything.

## Running the live suite

```bash
uv run --project <repo> pytest -m live tests/live -q
```

- Requires MuseScore running with the plugin serving `ws://localhost:8765`
  (the suite skips itself otherwise).
- **The suite mutates the open score** (appends scratch measures and
  writes test content). A guard refuses to run unless the score title
  contains "untitled", "scratch", or "mcp" (override:
  `MCP_SCORE_LIVE_ANY_SCORE=1`).
- Tests allocate fresh scratch measures at the score tail at call time
  and assert delta-scoped MusicXML diffs, so a dirty score never causes
  false failures. Undo is never used for cleanup.
- Every skip/xfail reason string documents a verified MuseScore 4.7.4
  defect. A strict xfail that starts XPASSing means MuseScore fixed
  something — remove the marker and enjoy.
- Plain `pytest` (CI, the pre-push hook) excludes the live suite via
  `addopts`; no MuseScore needed.

## Restart matrix

| You changed                                 | Redeploy                                                                                                      | Restart needed                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `mcp-score-bridge.qml`                      | none — `~/Documents/MuseScore4/Plugins` is a directory junction to `src/mcp_score/musescore/` on this machine | MuseScore restart + relaunch the plugin dock. Confirm with `getScore` → `pluginVersion`. |
| Python source, exercised via the live suite | nothing (`uv run --project` uses the source tree)                                                             | none                                                                                     |
| Python source, exercised via an MCP client  | reinstall/refresh however the client launches the server                                                      | restart the MCP client (e.g. Claude Code)                                                |

## Gotchas learned the hard way

- **Three separate clef traps, each of which fails _silently_ rather than
  loudly.** They cost four MuseScore restarts to find, and every one of
  them would have shipped as a wrong answer, not an error:
  1. **`Element.subtype` is read-only.** Assigning to it throws
     `Cannot assign to read-only property`. The writable pair is
     `concertClefType` / `transposingClefType`. Worse, assigning to a
     _non-existent_ property name (`clefType`, `clefTypeConcert`) appears
     to succeed and reads back the value — JavaScript just attached an
     expando to the object and the score never saw it. Guard with
     `typeof el[name] === "number"` before assigning, as `applyClefType`
     does.
  2. **ClefType integers are not what the enum declaration says.** A
     table derived from MuseScore's `clef.h` had every value from `F`
     onwards one too high, because 4.7.4 carries fewer C-clef variants
     than the source read from. `bass` is **20**, not 21. A wrong value
     writes a real clef of the wrong kind and every reply looks correct —
     only the exported MusicXML `sign` reveals it. The live suite checks
     all 8 names against the export for exactly this reason.
  3. **`generated` does not mean "courtesy clef".** It is `true` for a
     staff's opening clef too, since that is laid out from the staff's
     own clef property. Treating `generated` as redundant reports a clean
     piano score as having **zero** clefs. What it does mean is
     `generated: false` == inserted by someone — which is precisely the
     MIDI-import leftover worth finding. Redundancy is instead derived
     from the reading: a clef restating the one already in force.
- **`Score.firstSegment` is a _function_ in 4.7.4, not a property**, and
  so is `Segment.next`. Reading them as properties yields `undefined`,
  so a segment walk silently traverses nothing — which is how clef
  enumeration first reported a two-clef score as empty. `segmentValue`
  accepts either shape. A cursor is no substitute: `cursor.next()` stops
  only at ChordRest segments and steps straight over Clef segments.
- **MuseScore exports a note's _spelling_, not its MIDI number.** The
  MusicXML exporter writes step/alter/octave derived from `tpc`. Setting
  `note.pitch` without also setting `note.tpc` produces a note that reads
  back as the new pitch through the plugin API but still _exports_ as the
  old one — the exact silent corruption this project guards against.
  `setPitches` refuses `newPitch` without `newTpc` for this reason.
- **An empty voice cannot be navigated.** `rewind`, `nextMeasure` and
  `rewindToTick` all stop only at segments holding an element for the
  cursor's track, and voices 1–3 start empty, so all three leave the
  cursor at tick 0 with no segment. ChordRest segments are shared across
  a measure's voices, so the working route is: find the segment in voice
  0 (MuseScore keeps it filled with rests), _then_ switch the cursor's
  voice. `cursorAtTick` tries three strategies and keeps the first that
  verifiably lands; `apiProbe` reports which this build accepts.
- **MusicXML numbers voices across a whole part**, so a two-staff piano
  uses 1–4 for the upper staff and 5–8 for the lower, while MuseScore
  numbers 0–3 within _each_ staff (`theory.musescore_voice` maps them).
  A measure with a single voice carries no voice marker at all.
- **A rendered score image is unreliable for pitch — measured, not
  assumed.** Blind test on 2026-07-26: a script generated a random
  four-bar piano score, hid the answer, and rendered it at `-r 130`;
  reading only the PNG (at three magnifications) scored **rhythm 25/25,
  key and meter correct, pitch 10/25 — 40%**. `parse_snapshot` on the
  same file scored 25/25. Worse than the rate: all fifteen errors were
  displaced _upward_ by one or two diatonic steps, none downward — a
  slipped staff grid, not noise, which yields plausible-looking music
  that is wrong throughout. The notes read correctly were the visually
  distinctive ones (above the staff, on ledger lines, carrying
  accidentals); the ordinary in-staff notes, which are most of any real
  score, were the misses. The test was also generous — every pitch was
  diatonic in one key and the rhythms came from a short list. Use a
  render for layout and density only; never transcribe from one, and
  never ask the user for a photograph of a score in place of a file. For
  image-to-notation, dedicated OMR (e.g. Audiveris) is the tool.
- **music21's `Pitch.midi` folds an out-of-range pitch back inside
  0–127 by octaves**, so a note transposed off the top of the range comes
  back looking like a valid — but several octaves lower — note, and a
  range guard written against `.midi` can never fire. Read `.ps` instead
  (`theory._true_midi`). This was a live bug: transposing a top-of-range
  note up an octave silently wrote it an octave _down_.
- **`degrees` counts scale steps, not interval names**: "up a third" is
  `degrees=2`, "up a step" is `degrees=1`. A note foreign to the key
  snaps onto the nearest scale tone in the direction of travel, and the
  snap consumes the first step (in E-flat, a chromatic E natural moved up
  one degree lands on F — which is musically right, since E to F is a
  second).
- **Minor keys are read as natural minor** throughout the diatonic
  helpers, so a passage moved within `"c"` uses A-flat and B-flat, never
  a raised leading note. Roman numerals are unaffected — `V` in a minor
  key is still major, because `RomanNumeral` applies the harmonic form.
- **The figured-bass solver needs a registered bass octave.** Every
  element handed to `FiguredBassLine.addElement` must have
  `element.bass().octave` set first, or the search silently returns zero
  solutions with no explanation. On one test progression that single line
  took it from 0 to 62 solutions.
- **Possibility tuples come back soprano-first, bass-last** from music21;
  `plan_progression_voicing` reverses them so the rest of the codebase
  can keep reading chords upward from the bass.
- **Retrograde and sequence re-enter music note by note**, which is the
  only thing the wire can do for a change of rhythm — so they replace the
  target bars and refuse anything they cannot reproduce (ties, tuplets,
  grace notes, a meter change inside the range, a voice that does not
  fill every bar). `plan_retrograde` is safe on barlines only because it
  requires equal, fully-tiled bars: reversing a run of total length _T_
  maps a boundary at _x_ to _T − x_, which stays a boundary exactly when
  every bar is the same length.
- Key signatures apply from their measure forward; expect the export
  diff to show only the measure that got the signature.
- Time-signature changes re-bar everything after them and may put a
  courtesy signature at the end of the previous measure.
- `goToStaff` persists across commands — and so does the **voice** it
  set. A forgotten voice switch makes later edits land in voice 2 of the
  right staff, which looks like nothing happened. Set both explicitly.
- Rehearsal marks and tempo/system text live on staff 0 in exports.
- The bridge auto-connects and retries once on connection loss
  (`RECV_TIMEOUT` 30 s). "Cannot connect" errors right after a MuseScore
  restart usually mean the plugin dock has not been relaunched.
- If MuseScore crashes, everything unsaved is gone: the wire commands
  that crash it are gated for exactly this reason. Do not pass
  `__experimental: true` outside a deliberate, saved-score experiment.

## Adding a new command end-to-end

1. QML: add the `case` in `handleMessage` + a `handle...` function
   (validate params first; wrap mutations in `startCmd`/`try`/`finally`
   `endCmd`). Add it to the `processSequence` switch too if it should be
   sequenceable — that is a second, separate switch.
2. Bridge: add a convenience method in
   `src/mcp_score/bridge/musescore.py`.
3. Tool: add the `@mcp.tool()` in `src/mcp_score/tools/` (guard with
   `connected_bridge()` / `check_measure` / `_require_musescore`).
4. Tests: mocked (CI) + live (delta-scoped MusicXML diff).
5. Bump the plugin `version`, restart MuseScore, run the live suite.
6. Update this playbook's support matrix.

Keep musical decisions out of the QML: if a step needs to know what a
note should be _called_ or which chord a figure means, that belongs in
`mcp_score.theory` (music21), and the plugin should receive the answer as
numbers.

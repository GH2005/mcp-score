# Agent playbook — verified mcp-score usage patterns

> Reference — every claim here was verified against a live MuseScore
> Studio 4.7.4 (Windows 11) by the committed live test suite
> (`tests/live/`). Verification date: 2026-07-24. Plugin version: 0.3.0.
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

### Reading the score when you must bypass the tools

Reach for this only when the tools above are not an option — the MCP
server is disconnected but the plugin dock is still serving, you are
debugging the bridge itself, or you need a rendered image (engraving and
layout), not just note data. It is fully automated: never ask the user
to save the file or to report what they see in MuseScore.

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
2. **Read the snapshot.** Parse the MusicXML for note-exact data, and/or
   render it with MuseScore's own CLI for a visual check:
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

| Surface                                                                           | Notes                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `connect_to_musescore(host="localhost", port=8765)`, `disconnect_from_musescore`  | Connect first; every other tool needs an active connection. The bridge auto-connects and retries once on connection loss.                                                                                                                                                                                                                                                     |
| `ping_score_app` (wire `ping`), `get_live_score_info` (wire `getScore`)           | `getScore` reply carries `pluginVersion` (stale-plugin detection), `measureCount`, key/time signature, parts with staff ranges (derived from tracks).                                                                                                                                                                                                                         |
| `export_live_score(path?, format="musicxml")`                                     | The ground-truth snapshot. Rejects `mscz` (see limitations), relative paths, unknown formats.                                                                                                                                                                                                                                                                                 |
| `read_passage(start, end, staff?)`                                                | Accurate: export + parse. Reports every note, chord, rest, voice, and annotation per measure/staff.                                                                                                                                                                                                                                                                           |
| `get_measure_content(measure, staff=0)`                                           | Accurate: export + parse.                                                                                                                                                                                                                                                                                                                                                     |
| `get_selection_properties`                                                        | Cursor info only (measure/staff/beat/tick + element under cursor).                                                                                                                                                                                                                                                                                                            |
| `add_live_notes(measure, staff, notes, voice=0)`                                  | The reliable note-entry path: compiles a run into one `processSequence` batch. Entries take `{"name": "E-4"}` (**preferred** — spelling is preserved exactly), `{"chord": ["C4","E-4","G4"]}`, `{"rest": true}`, or `{"pitch": 61, "key": "E-"}`; plus `numerator`/`denominator` (default 1/4). Content at those beats is replaced, and a run spills into following measures. |
| `process_live_sequence(steps)`                                                    | Batch of wire actions in one command group. Rejects crash/corruption actions. **Rollback on failure does not work** (undo is broken): earlier steps stay applied.                                                                                                                                                                                                             |
| `add_live_rehearsal_mark(measure, text)` (wire `addRehearsalMark`)                | Verified in export.                                                                                                                                                                                                                                                                                                                                                           |
| `set_live_time_signature(measure, num, den)`                                      | Verified in export; re-bars from that measure onward; may add a courtesy signature to the previous measure.                                                                                                                                                                                                                                                                   |
| `append_live_measures(count)` (wire `appendMeasures`)                             | Verified in export.                                                                                                                                                                                                                                                                                                                                                           |
| `transpose_passage(start, end, staff, semitones, voice?)`                         | Snapshot → music21 computes each new pitch **and its spelling** → verified positional edits via `setPitches`. Transposes every voice unless one is named. G+3 comes out B-flat, not A-sharp.                                                                                                                                                                                  |
| `realize_harmony(figure, key, octave=4)`                                          | Intent → notes. A roman numeral in a key (`"V7/V"`, `"bVII"`, `"Ger65"`) or a chord symbol (`"E-maj7"`) becomes spelled pitches; `chord_for_add_live_notes` feeds straight into `add_live_notes`. **Needs no connection** — pure theory.                                                                                                                                      |
| `analyze_passage(start, end, staff?, key?)`                                       | Notes → intent, plus critique: detected key, roman-numeral reading per simultaneity, voice-leading observations (parallel/hidden 5ths & 8ves, voice crossing) located by measure, per-staff ambitus. **Advisory only — never edits, never blocks.**                                                                                                                           |
| Wire navigation: `goToMeasure` (1-indexed), `goToStaff` (0-indexed, `voice?` 0-3) | Bounds-checked. Staff **and voice** persist across commands; always set both explicitly.                                                                                                                                                                                                                                                                                      |
| Wire `addNote`                                                                    | Consecutive calls accumulate (the plugin tracks the intra-measure tick). `addToChord: true` stacks onto the previous note instead of advancing; `tpc` sets the spelling. Pitch validated 0–127, tpc −1..33.                                                                                                                                                                   |
| Wire `addRest`                                                                    | `cursor.addRest` exists in 4.7.4 and works. Same duration parameter as `addNote`.                                                                                                                                                                                                                                                                                             |
| Wire `setPitches`                                                                 | Rewrites pitch + spelling over a staff/voice/measure range. Edits are **positional** (tick order, then ascending pitch within a chord) and every `oldPitch` is verified before anything is written, so a stale request aborts whole.                                                                                                                                          |
| Wire `getCursorInfo`                                                              | Beat computed via `measure.timesigActual`. Reports raw `(pitch, tpc)`; render names with `mcp_score.theory.pitch_tpc_to_name`. Only the element under the cursor — use the export path for full content.                                                                                                                                                                      |
| Wire `apiProbe`                                                                   | Runtime introspection, incl. `capabilities.voicePositioning` (which cursor strategy this build accepts).                                                                                                                                                                                                                                                                      |

### Broken in MuseScore 4.7.4 — guarded, do not attempt to bypass

| Surface                                                                                                                                       | Failure mode                                                                                                                                                                                                                                                                                                                                                                                    | Guard                                                                                                                     |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `setBarline`, `addChordSymbol`, `addDynamic` (tools `set_live_barline`, `add_live_chord_symbol`; `addDynamic` is wire-only, no tool wraps it) | **Crash MuseScore outright** (process death; `newElement` + `cursor.add` is fatal for these element types).                                                                                                                                                                                                                                                                                     | Tools refuse; wire commands require `__experimental: true`; `process_live_sequence` rejects the actions.                  |
| `setKeySignature`, `setTempo` (tools `set_live_key_signature`, `set_live_tempo`)                                                              | **Silently insert corrupt elements**: every inserted key signature exports as `fifths=-8` regardless of the value written; tempo marks export with no text and no number. The clone made by `cursor.add` loses the assigned values; re-assigning after insertion does not help. (`setTimeSignature` and rehearsal marks use the same pattern and work — the MS4 API port is that inconsistent.) | Tools refuse; `process_live_sequence` rejects the actions.                                                                |
| `undo` (tool `undo_last_action`) and `processSequence` rollback                                                                               | `cmd("undo")` is a **silent no-op** from the dock-plugin context: the reply says ok, the edit stays.                                                                                                                                                                                                                                                                                            | None (reply is honest-looking but useless). Never rely on undo; verify with exports and fix mistakes with explicit edits. |
| `selectCurrentMeasure`, `selectCustomRange`                                                                                                   | Both wrap `selection.selectRange`, which does not produce an _active_ selection in MS4 (`elements` stays empty, with or without a command group), so anything that reads the selection afterward sees nothing.                                                                                                                                                                                  | No tool wraps them. Nothing in the bridge depends on a selection any more.                                                |
| `newScore`                                                                                                                                    | Creates the score in a window this bridge cannot control; `curScore` never switches to it.                                                                                                                                                                                                                                                                                                      | Not exposed as a tool.                                                                                                    |
| `exportScore` with `format: "mscz"`                                                                                                           | writeScore writes a 0-byte file, never replies, and raises a **blocking modal dialog** the user must dismiss by hand.                                                                                                                                                                                                                                                                           | Rejected at both the tool and the plugin level.                                                                           |

### Not available on this machine

`connect_to_dorico` / `disconnect_from_dorico` (port 4560) and
`connect_to_sibelius` / `disconnect_from_sibelius` (port 1898): neither
application is installed, so only their connection-failure paths are
verified. The MuseScore-only tools refuse when another app is connected
(`_require_musescore`).

## Composing on an open score

The loop for live work with a musician, using the tools above:

1. **Read what is there** — `read_passage`. It reports chords, voices and
   spelling accurately, so never guess at the current state.
2. **Decide the music yourself.** music21 supplies theory mechanics, not
   taste: it will not tell you what the piece needs. `realize_harmony`
   turns a decision you have already made into notes.
3. **Write it spelled** — `add_live_notes` with `name`/`chord` entries.
   Prefer names over bare MIDI: a bare pitch makes MuseScore guess, and
   an ascending C-sharp and a descending D-flat are the same MIDI number
   but different music.
4. **Verify by export**, not by the reply (see the doctrine above).
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

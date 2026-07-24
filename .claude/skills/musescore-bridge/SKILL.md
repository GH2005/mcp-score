---
name: musescore-bridge
description: >
  Correct usage patterns for the mcp-score MCP server's live MuseScore tools
  and the mcp-score-bridge MuseScore plugin's WebSocket wire protocol. Use
  BEFORE calling any of: connect_to_musescore, disconnect_from_musescore,
  connect_to_dorico, disconnect_from_dorico, connect_to_sibelius,
  disconnect_from_sibelius, ping_score_app, get_live_score_info,
  read_passage, get_measure_content, get_selection_properties,
  export_live_score, analyze_passage, realize_harmony,
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
  "live score manipulation", or when composing into a score the user
  already has open.
  Several of these commands crash or silently corrupt MuseScore Studio
  4.7.4 if called the wrong way -- read this before guessing at
  parameters.
allowed-tools: [Read]
metadata:
  version: "1.4"
---

# MuseScore bridge — correct usage

The full, verified reference is [`agent-playbook.md`](agent-playbook.md),
right next to this file — the single source of truth for the support
matrix (all 25 MCP tools and every wire command), the composing loop, the
restart matrix, and how to re-run the live suite
(`pytest -m live tests/live`) if MuseScore's behavior seems to have
changed. **Read it before any mutating or wire-level call, and before
anything beyond the six rules below** — do not guess at parameters,
defaults, or which commands are safe.

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

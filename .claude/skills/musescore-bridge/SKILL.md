---
name: musescore-bridge
description: >
  Correct usage patterns for the mcp-score MCP server's live MuseScore tools
  and the mcp-score-bridge MuseScore plugin's WebSocket wire protocol. Use
  BEFORE calling any of: connect_to_musescore, disconnect_from_musescore,
  connect_to_dorico, disconnect_from_dorico, connect_to_sibelius,
  disconnect_from_sibelius, ping_score_app, get_live_score_info,
  read_passage, get_measure_content, get_selection_properties,
  export_live_score, add_live_rehearsal_mark, add_live_notes,
  set_live_time_signature, append_live_measures, process_live_sequence,
  transpose_passage, add_live_chord_symbol, set_live_barline,
  set_live_key_signature, set_live_tempo, or undo_last_action -- or before
  sending any raw JSON command to the plugin's WebSocket bridge
  (ws://localhost:8765, e.g. ping, getScore, goToMeasure, goToStaff,
  addNote, addRehearsalMark, setTimeSignature, appendMeasures, transpose,
  undo, processSequence, exportScore, apiProbe) -- or before editing
  src/mcp_score/musescore/mcp-score-bridge.qml. Also trigger on phrases like "connect
  to MuseScore", "read/write the live score", "what's in the open score",
  "add notes to the score", "transpose the passage", "undo in MuseScore",
  "MuseScore plugin", "mcp-score-bridge", "live score manipulation".
  Several of these commands crash or silently corrupt MuseScore Studio
  4.7.4 if called the wrong way -- read this before guessing at
  parameters.
allowed-tools: [Read]
metadata:
  version: "1.3"
---

# MuseScore bridge — correct usage

The full, verified reference is [`agent-playbook.md`](agent-playbook.md),
right next to this file — the single source of truth for the support
matrix (all 23 MCP tools and every wire command), the restart matrix, and
how to re-run the live suite (`pytest -m live tests/live`) if MuseScore's
behavior seems to have changed. **Read it before any mutating or
wire-level call, and before anything beyond the five rules below** — do
not guess at parameters, defaults, or which commands are safe.

## The five rules that keep MuseScore alive

The load-bearing safety rules — the ones that crash, corrupt, or silently
mislead. They live here so they are in context even before you open the
playbook; the playbook carries the full detail and the reasoning.

1. **Never use `format: "mscz"`** in `export_live_score` / `exportScore`.
   It writes a 0-byte file, never replies, and blocks MuseScore with a
   modal dialog the user must dismiss by hand. Use `"musicxml"`.
2. **`transpose_passage` / wire `transpose`** takes ranged parameters
   (`start_measure`/`end_measure`/`staff`/`semitones`, or
   `startMeasure`/`endMeasure`/`startStaff`/`endStaff` on the wire) in a
   single call. Do NOT select-then-transpose — `selectRange` never
   produces an active selection in MuseScore 4.
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
